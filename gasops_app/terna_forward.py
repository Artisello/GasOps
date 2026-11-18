"""Terna market-session forecasts. No use of realised future electricity."""
from datetime import date,datetime,timedelta,timezone
from hashlib import sha256
import json,re
import pandas as pd
from .data import ROME
from .terna_power import CATALOG,PORTAL,get_token,_json_request,_timestamp,number
from .public_data import SourceSchemaError,SourceUnavailable
from .models import utc_now
from .entsog import _start

STATE="terna_forward_v1"
ATTEMPT="terna_forward_attempt_v1"
LOAD="https://api.terna.it/market/v1.0/input/forecast-load"
WIND="https://api.terna.it/generation/v2.0/wind-production-forecast"
DOCS={"load":CATALOG+"/market/Load_Forecast","wind":CATALOG+"/generation/Wind_Production_Forecast"}
SESSION="MSD1"
ZONES={
    "nord":"NORD","north":"NORD","centronord":"CNOR","centrenorth":"CNOR","cnor":"CNOR",
    "centrosud":"CSUD","centresouth":"CSUD","csud":"CSUD","sud":"SUD","south":"SUD",
    "calabria":"CALA","cala":"CALA","sicilia":"SICI","sicily":"SICI","sici":"SICI",
    "sardegna":"SARD","sardinia":"SARD","sard":"SARD"}
REQUIRED=set(ZONES.values())
MAX_BATCHES=400
MAX_BYTES=4_000_000


def stamp_local(value):
    if not isinstance(value,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:00",value):
        raise SourceSchemaError("Timestamp di previsione non valido")
    dt=datetime.fromisoformat(value)
    # Wind has no offset in the documented contract: reject ambiguous and missing local times.
    a,b=dt.replace(tzinfo=ROME,fold=0),dt.replace(tzinfo=ROME,fold=1)
    if a.utcoffset()!=b.utcoffset() or a.astimezone(timezone.utc).astimezone(ROME).replace(tzinfo=None)!=dt:
        raise SourceSchemaError("Ora locale ambigua o inesistente")
    return a.astimezone(timezone.utc)


def parse(payload,kind,first,last,acquired):
    if kind not in DOCS or payload.get("result",{}).get("status")!="Completed":
        raise SourceSchemaError("Risposta Terna non completata")
    raw=payload.get("forecast_load")
    if not isinstance(raw,list) or not raw or len(raw)>24000:
        raise SourceSchemaError("Previsioni Terna assenti o oltre limite")
    hourly={}
    start,end=_start(first),_start(last+timedelta(days=1))
    invalid=set()
    for row in raw:
        if not isinstance(row,dict):continue
        if row.get("date_tz")!="Europe/Rome" or row.get("session_type")!=SESSION:
            continue
        zone=ZONES.get(re.sub(r"[^a-z]","",str(row.get("zone","")).lower()))
        if not zone:continue
        try:
            if kind=="load":
                t=_timestamp({"date":row.get("reference_date"),"date_tz":row["date_tz"],
                              "date_offset":row.get("offset")},15)
            else:
                t=stamp_local(row.get("reference_date"))
                issue=stamp_local(row.get("prevision_date"))
                pub=date.fromisoformat(row["publication_date"])
                if issue>acquired or pub>acquired.astimezone(ROME).date() or issue>t:
                    continue
            if not start<=t<end:continue
            value=number(row["load_MW"])
            if value is None:continue
        except (ValueError,KeyError,TypeError,SourceSchemaError):
            continue
        key=(t,zone)
        # Without a single authenticated run identifier, conflicting values are excluded.
        if key in hourly and hourly[key]!=value:invalid.add(key)
        hourly[key]=value
    for key in invalid:hourly.pop(key,None)
    out=[]
    for day in pd.date_range(first,last):
        d=day.date()
        a,b=_start(d),_start(d+timedelta(days=1))
        for minutes in (15,60):
            slots=pd.date_range(a,b,freq=f"{minutes}min",inclusive="left")
            in_day={t for t,z in hourly if a<=t<b}
            if in_day!=set(slots):continue
            if not all((t,z) in hourly for t in slots for z in REQUIRED):continue
            val=sum(hourly[t,z] for t in slots for z in REQUIRED)*minutes/60000
            out.append({"day":d.isoformat(),"metric":kind,"gwh":float(val),"slots":len(slots),"minutes":minutes})
            break
    return out


def validate(batch):
    if set(batch)!={"acquired","first","last","rows","session"} or batch["session"]!=SESSION:
        raise ValueError("Schema previsioni non valido")
    at=datetime.fromisoformat(batch["acquired"])
    first,last=date.fromisoformat(batch["first"]),date.fromisoformat(batch["last"])
    if at.tzinfo is None or not 0<=(last-first).days<7 or last>at.astimezone(ROME).date()+timedelta(days=2):
        raise ValueError("Intervallo non valido")
    seen=set()
    if not isinstance(batch["rows"],list) or not 1<=len(batch["rows"])<=14:
        raise ValueError("Copertura non valida")
    for r in batch["rows"]:
        if set(r)!={"day","metric","gwh","slots","minutes"}:raise ValueError("Record non valido")
        d=date.fromisoformat(r["day"])
        key=(d,r["metric"])
        if key in seen or not first<=d<=last or r["metric"] not in DOCS or r["minutes"] not in (15,60):
            raise ValueError("Record duplicato o non valido")
        seen.add(key)
        n=int((_start(d+timedelta(days=1))-_start(d)).total_seconds()/(60*r["minutes"]))
        if r["slots"]!=n or number(r["gwh"]) is None:raise ValueError("Copertura non valida")
    return batch


def digest(b):
    return sha256(json.dumps(b,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def merge(old,new,now):
    items={}
    for b in [*old,*new]:
        validate(b)
        if datetime.fromisoformat(b["acquired"])>now:raise ValueError("Acquisizione futura")
        items[digest(b)]=b
    if len(items)>MAX_BATCHES:raise ValueError("Limite archivio raggiunto; esporta prima di svuotare.")
    return sorted(items.values(),key=lambda b:(datetime.fromisoformat(b["acquired"]),digest(b)))


def acquire(client,secret,first,last,now=None,clock=utc_now):
    now=now or utc_now()
    if not 0<=(last-first).days<7 or last>now.astimezone(ROME).date()+timedelta(days=2):
        raise ValueError("Intervallo massimo 7 giorni, fino a D+2")
    token=get_token(client,secret)
    params={"dateFrom":first.strftime("%d/%m/%Y"),"dateTo":(last+timedelta(days=1)).strftime("%d/%m/%Y"),"sessionType":SESSION}
    rows=[];notes=[]
    for kind,url in (("load",LOAD),("wind",WIND)):
        try:
            payload=_json_request("GET",url,params=params,headers={"Authorization":"Bearer "+token,"Accept":"application/json"})
            part=parse(payload,kind,first,last,clock())
            if not part:notes.append(kind+": copertura zonale/oraria incompleta")
            rows.extend(part)
        except (SourceUnavailable,ValueError,TypeError,KeyError):
            notes.append(kind+": fonte non disponibile")
    if not rows:raise SourceUnavailable("Nessuna previsione giornaliera completa disponibile")
    return validate({"acquired":clock().isoformat(),"first":str(first),"last":str(last),"session":SESSION,"rows":rows}),notes


def paired(batch):
    by={}
    for r in batch["rows"]:by.setdefault(r["day"],{})[r["metric"]]=r["gwh"]
    return [{"day":d,**v,"load_minus_wind_gwh":v["load"]-v["wind"]} for d,v in sorted(by.items()) if set(v)==set(DOCS)]


def outlook(state,now):
    today=now.astimezone(ROME).date().isoformat()
    eligible=[b for b in state.get(STATE,[]) if timedelta(0)<=now-datetime.fromisoformat(b["acquired"])<=timedelta(hours=24)]
    # Latest acquisition containing forward data. Do not silently use earlier run.
    if not eligible:return None
    b=eligible[-1]
    by={}
    for r in b["rows"]:
        if r["day"]>=today:by.setdefault(r["day"],{})[r["metric"]]=r["gwh"]
    points=[{"day":d,**v,**({"load_minus_wind_gwh":v["load"]-v["wind"]} if set(v)==set(DOCS) else {})} for d,v in sorted(by.items())]
    if not points:return None
    return {"id":"terna_forward","source":"Terna · MSD1","url":PORTAL,"horizon":2,
        "from":points[0]["day"],"to":points[-1]["day"],"n":len(points),"acquired":b["acquired"],"points":points,
        "limitation":"Carico meno eolico previsto, non residual load completo; niente fotovoltaico, import o altre fonti. Metriche disponibili anche separatamente; proxy soltanto su coppie complete. Dati zonali completi, timestamp assunti inizio intervallo; versioni all'acquisizione."}


def join_forward(samples,batches,asof):
    """Only captured versions at or before each Snam origin 15:00 cutoff."""
    rows=[]
    grouped={}
    for b in batches:
        validate(b)
        at=datetime.fromisoformat(b["acquired"]).astimezone(ROME).replace(tzinfo=None)
        if at>asof:continue
        for r in paired(b):
            grouped.setdefault(r["day"],[]).append((at,digest(b),r))
    for target,r in samples.iterrows():
        cutoff=r.origin+pd.Timedelta(hours=15)
        eligible=[x for x in grouped.get(target.date().isoformat(),[]) if x[0]<=cutoff]
        if not eligible:continue
        newest=max(x[0] for x in eligible)
        same=[x for x in eligible if x[0]==newest]
        if len({(x[2]["load"],x[2]["wind"]) for x in same})!=1:continue
        at,key,v=same[0]
        rows.append({"target":target,"power_day":target.date().isoformat(),"power_acquired":at.isoformat(),"power_sha256":key,
                     "forward_load":v["load"],"forward_wind":v["wind"]})
    cols=["forward_load","forward_wind"]
    if not rows:return samples.assign(**{k:float("nan") for k in cols}),cols
    return samples.join(pd.DataFrame(rows).set_index("target")),cols
