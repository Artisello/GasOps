"""Portable snapshots. Acquisition is not original publication time."""
from datetime import date,datetime,timedelta
from hashlib import sha256
import json,math
import pandas as pd
from .data import ROME
from .entsog import _last_completed
from .entsog_network import check_point,INDICATORS

STATE="entsog_vintages_v1"
SELECT="entsog_vintage_point_v1"
FORWARD=("Nomination","Renomination")
MAX_BYTES=8_000_000


def validate(b,now):
    if not isinstance(b,dict) or set(b)!={"point","acquired","first","last","rows","complete"}:raise ValueError("Schema non valido")
    check_point(b["point"])
    at=datetime.fromisoformat(b["acquired"])
    a,z=date.fromisoformat(b["first"]),date.fromisoformat(b["last"])
    if at.tzinfo is None or at>now or not 0<=(z-a).days<31 or z>at.astimezone(ROME).date()+timedelta(days=2):raise ValueError("Date non valide")
    if type(b["complete"]) is not bool or not isinstance(b["rows"],list) or not 1<=len(b["rows"])<=217:raise ValueError("Copertura non valida")
    seen=set()
    for r in b["rows"]:
        if not isinstance(r,dict) or set(r)!={"day","indicator","gwh","assumed"}:raise ValueError("Record non valido")
        d=date.fromisoformat(r["day"]);key=(d,r["indicator"])
        if key in seen or not a<=d<=z or r["indicator"] not in INDICATORS:raise ValueError("Record duplicato o fuori perimetro")
        seen.add(key)
        if r["indicator"] not in FORWARD and d>_last_completed(at):raise ValueError("Consuntivo non maturo")
        if type(r["gwh"]) not in (float,int) or not math.isfinite(r["gwh"]) or abs(r["gwh"])>1e9 or type(r["assumed"]) is not bool:raise ValueError("Valore non valido")
    return b


def capture(r,now):
    if r.failed:raise ValueError("Cache dopo errore: nessun nuovo vintage")
    rows=[{"day":v["gas_day"],"indicator":v["indicator"],"gwh":float(v["value_gwh_d"]),"assumed":v["timestamp_assumed"]}
          for v in r.rows if v["quality"]=="valido" and v["value_gwh_d"] is not None and
          (v["indicator"] in FORWARD or date.fromisoformat(v["gas_day"])<=_last_completed(r.acquired))]
    return validate({"point":r.point,"acquired":r.acquired.isoformat(),"first":str(r.first),"last":str(r.last),
       "complete":not r.metadata_warning and len(r.labels)==1 and all(r.labels[0]),"rows":rows},now)


def digest(b):
    return sha256(json.dumps(b,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def audit_rows(frame,day,now,*,batches=()):
    """Audit real versions/acquisitions; acquisition never becomes publication."""
    from decimal import Decimal,InvalidOperation
    from .gas_data import _stamp
    from .gas_calendar import gas_day_bounds
    indicators=("Nomination","Renomination","Allocation","Physical Flow")
    groups={}
    def add(point,indicator,value,unit,start,stop,published,acquired,source_id,quality,version=""):
        if unit!="GWh/d" or indicator not in indicators or not point:return
        at,issued=_stamp(acquired),_stamp(published)
        if at and at>now or issued and issued>now:return
        try:amount=Decimal(str(value)) if value is not None else None
        except InvalidOperation:amount=None
        if amount is not None and (not amount.is_finite() or abs(amount)>Decimal("1e9")):amount=None
        groups.setdefault((point,indicator,unit,start,stop),[]).append({
            "source_id":source_id or point,"gas_day":day,"point_direction":point,"indicator":indicator,
            "retrieved_at":at,"publication_timestamp":issued,"new_value":amount,"unit":unit,
            "period_from":start,"period_to":stop,"quality_flag":quality,"version":version})
    selected=frame.loc[(frame.provider=="ENTSOG")&(frame.gas_day==day)&frame.indicator.isin(indicators)]
    for r in selected.itertuples():
        versions=json.loads(r.revisions or "[]")
        for v in versions:
            add(r.point_direction,r.indicator,v.get("value"),r.unit,r.period_from,r.period_to,v.get("observed_at"),
                v.get("retrieved_at") or r.retrieved_at,v.get("source_id") or r.source_id,
                "conflict" if r.quality_status=="conflict" else v.get("quality_status") or r.quality_status)
        if not versions:
            add(r.point_direction,r.indicator,r.value,r.unit,r.period_from,r.period_to,r.observed_at,
                r.retrieved_at,r.source_id,r.quality_status)
    start,stop=gas_day_bounds(day)
    for batch in merge([],batches,now):
        for r in batch["rows"]:
            if r["day"]==day.isoformat():
                add(batch["point"],r["indicator"],r["gwh"],"GWh/d",start,stop,None,batch["acquired"],
                    batch["point"],"unaligned" if r["assumed"] else "declared_vintage" if batch["complete"] else "partial",digest(batch))
    output=[]
    for group in groups.values():
        distinct={}
        for r in group:
            key=(r["publication_timestamp"],None if r["publication_timestamp"] else r["retrieved_at"],r["new_value"])
            if key in distinct:
                old=distinct[key]
                old["source_id"]=" | ".join(dict.fromkeys((old["source_id"],r["source_id"])))
                if r["quality_flag"]=="conflict":old["quality_flag"]="conflict"
            else:distinct[key]=dict(r)
        rows=list(distinct.values())
        published=all(r["publication_timestamp"] is not None for r in rows)
        field="publication_timestamp" if published else "retrieved_at"
        rows.sort(key=lambda r:(r[field] is None,r[field] or now))
        previous=None
        for r in rows:
            tied=[x for x in rows if x[field]==r[field]]
            conflict=len({x["new_value"] for x in tied})>1 or r["quality_flag"]=="conflict"
            prior=previous if (not conflict and previous and previous[field] is not None and r[field] is not None
                and previous[field]<r[field] and previous["quality_flag"] not in ("conflict","unaligned")
                and r["quality_flag"]!="unaligned") else None
            old=prior["new_value"] if prior else None
            changed=old is not None and r["new_value"] is not None and old!=r["new_value"]
            reason=("Conflitto: ordine delle versioni non dimostrato" if conflict else
                "Revisione pubblicata" if changed and published else "Variazione tra acquisizioni" if changed else
                "Ripubblicazione invariata" if prior and published else "Acquisizione invariata" if prior else "Prima versione disponibile")
            output.append({**r,"old_value":old,"changed":changed,"reason":reason,
                "quality_flag":"conflict" if conflict else r["quality_flag"],
                "order_basis":"publication" if published else "acquisition"})
            previous=None if conflict else r
    return output


def merge(old,new,now):
    out={}
    for b in [*old,*new]:
        validate(b,now);out[digest(b)]=b
    result=sorted(out.values(),key=lambda b:(datetime.fromisoformat(b["acquired"]),digest(b)))
    if len(result)>400 or len(json.dumps(result,allow_nan=False).encode())>MAX_BYTES:raise ValueError("Archivio al limite")
    return result


def points(batches):
    return sorted({b["point"] for b in batches})


def records(batches,point,indicator,now,*,strict=False):
    groups={}
    for b in batches:
        at=datetime.fromisoformat(b["acquired"])
        if b["point"]!=point or at>now or strict and not b["complete"]:continue
        for r in b["rows"]:
            if r["indicator"]!=indicator or strict and r["assumed"]:continue
            d=r["day"];old=groups.get(d)
            if old is None or at>old[0]:groups[d]=(at,{r["gwh"]})
            elif at==old[0]:old[1].add(r["gwh"])
    return [{"day":d,"gwh":next(iter(v)),"acquired":at.isoformat()} for d,(at,v) in sorted(groups.items()) if len(v)==1]


def outlook(state,now):
    batches=state.get(STATE,[]);point=state.get(SELECT)
    today=now.astimezone(ROME).date().isoformat()
    rows=[{"indicator":ind,**r} for ind in FORWARD for r in records(batches,point,ind,now,strict=True)
          if r["day"]>=today and timedelta(0)<=now-datetime.fromisoformat(r["acquired"])<=timedelta(hours=12)]
    if not rows:return None
    days=sorted({r["day"] for r in rows})
    return {"id":"entsog_programmes","source":"ENTSOG TP Transport Data","url":"https://transparency.entsog.eu/",
        "scope":point,"horizon":2,"from":days[0],"to":days[-1],"n":len(days),"unit":"GWh/giorno gas","points":rows,
        "limitation":"Programmi di un punto/direzione; non flussi futuri osservati né sbilanciamento di rete. Timestamp importati dichiarati."}


def join_programmes(samples,batches,point,indicator,asof):
    check_point(point)
    if indicator not in FORWARD:raise ValueError("Segnale non previsionale")
    groups={}
    for b in batches:
        at=datetime.fromisoformat(b["acquired"]).astimezone(ROME).replace(tzinfo=None)
        if b["point"]!=point or not b["complete"] or at>asof:continue
        for r in b["rows"]:
            if r["indicator"]==indicator and not r["assumed"]:groups.setdefault(r["day"],[]).append((at,digest(b),r["gwh"]))
    rows=[];col="entsog_programme"
    for target,r in samples.iterrows():
        cutoff=r.origin+pd.Timedelta(15, unit="h")
        candidates=[x for x in groups.get(target.date().isoformat(),[]) if x[0]<=cutoff]
        if not candidates:continue
        latest=max(x[0] for x in candidates);same=[x for x in candidates if x[0]==latest]
        if len({x[2] for x in same})!=1:continue
        at,key,val=same[0]
        rows.append({"target":target,"power_day":target.date().isoformat(),"power_acquired":at.isoformat(),"power_sha256":key,col:val})
    if not rows:return samples.assign(**{col:float("nan")}),[col]
    return samples.join(pd.DataFrame(rows).set_index("target")),[col]
