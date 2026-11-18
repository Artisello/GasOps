"""Additional Terna signals; preserve scope, units and acquisition vintage."""
from datetime import date,datetime,timedelta
from hashlib import sha256
from decimal import Decimal
import json,math
import pandas as pd
from .data import ROME
from .models import utc_now
from .terna_power import _timestamp,_json_request,get_token,number,PORTAL,CATALOG
from .entsog import _start
from .public_data import SourceUnavailable,SourceSchemaError

STATE="terna_context_v1"
ATTEMPT="terna_context_attempt_v1"
SELECT="terna_context_scopes_v1"
CAP="https://api.terna.it/adequacy/v1.0/expected-available-capacity"
IMCEI="https://api.terna.it/load/v2.0/monthly-index-industrial-electrical-consumption"
DOCS={"capacity":CATALOG+"/adequacy/Expected_Available_Capacity",
      "industry":"https://developer.terna.it/docs/apis_catalog/load/Monthly_Index_Industrial_Electrical_Consumption",
      "exchange":CATALOG+"/transmission/Scheduled_Foreign_Exchange"}
UNITS={"capacity":"MW","industry":"GWh/mese","exchange":"GWh/giorno gas"}
MAX_BYTES=10_000_000
MAX_BATCH=400
SECTORS={"ALIMENTARE","ALTRI","CARTARIA","CEMENTO CALCE E GESSO","CERAMICHE E VETRARIE","CHIMICA",
         "MECCANICA","METALLI NON FERROSI","MEZZI DI TRASPORTO","SIDERURGIA"}


def field(row,key):
    v=row.get(key)
    if not isinstance(v,str) or not v.strip() or len(v)>100 or any(ord(c)<32 for c in v):
        raise ValueError("Dimensione Terna non valida")
    return v.strip()


def get_rows(payload,key):
    if not isinstance(payload,dict) or payload.get("result",{}).get("status")!="Completed":
        raise SourceSchemaError("Risposta non completata")
    rows=payload.get(key)
    if not isinstance(rows,list) or not rows or len(rows)>30000:raise SourceSchemaError("Copertura non valida")
    return rows


def gas_days(kind,raw,first,last):
    """Exact group/day hourly coverage. No sum across unverified group scopes."""
    values={};conflicts=set()
    a,b=_start(first),_start(last+timedelta(days=1))
    for r in raw:
        try:
            if kind=="capacity":
                scope=[field(r,k) for k in ("macroarea","macrouser_name","plant_type","prevailing_fuel")]
                t=_timestamp({"date":r["market_date"],"date_offset":r["offset"],"date_tz":r["date_tz"]},60)
                val=number(r["available_capacity_MW"])
            else:
                scope=[field(r,"country")]
                t=_timestamp(r,60)
                imp,exp=number(r["import"]),number(r["export"])
                if imp is None or exp is None:continue
                val=imp-exp
                declared=Decimal(str(r["scheduled_foreign_exchange_MW"]))
                if not declared.is_finite() or abs(declared-val)>Decimal("0.01"):continue
            if val is None or not a<=t<b:continue
            key=(tuple(scope),t)
            if key in values and values[key]!=val:conflicts.add(key)
            values[key]=val
        except (ValueError,KeyError,TypeError,ArithmeticError,AttributeError,SourceSchemaError):
            continue
    groups={}
    for (scope,t),v in values.items():
        if (scope,t) not in conflicts:groups.setdefault(scope,{})[t]=v
    rows=[]
    for scope,series in sorted(groups.items()):
        for day in pd.date_range(first,last):
            d=day.date()
            hours=pd.date_range(_start(d),_start(d+timedelta(days=1)),freq="h",inclusive="left")
            if not all(t in series for t in hours):continue
            amount=sum(series[t] for t in hours)
            # Capacity is power, not energy production. Exchange is scheduled net energy.
            value=float(amount/len(hours) if kind=="capacity" else amount/1000)
            rows.append({"period":str(d),"scope":list(scope),"value":value,"hours":len(hours)})
    return rows


def parse_industry(payload,ref):
    raw=get_rows(payload,"monthly_index_industrial_electrical_consumption")
    values={};conflicts=set()
    for r in raw:
        try:
            if int(r["year"])!=ref.year or int(r["month"])!=ref.month:continue
            scope=(field(r,"region"),field(r,"sector"),field(r,"tension_type"))
            if scope[1] not in SECTORS or scope[2] not in ("AT","MT"):continue
            consumption=number(r["consumption_Gwh"])
            index=number(r["monthly_imcei"])
            if consumption is None and index is None:continue
            val=(float(consumption) if consumption is not None else None,float(index) if index is not None else None)
            if scope in values and values[scope]!=val:conflicts.add(scope)
            values[scope]=val
        except (ValueError,KeyError,TypeError,AttributeError,SourceSchemaError):
            continue
    return [{"period":str(ref),"scope":list(k),"value":v[0],"imcei":v[1]} for k,v in sorted(values.items()) if k not in conflicts]


def batch(kind,rows,at):
    if kind not in UNITS or not rows:raise ValueError("Nessun dato completo")
    return {"kind":kind,"acquired":at.isoformat(),"rows":rows}


def validate(b,now):
    if not isinstance(b,dict) or set(b)!={"kind","acquired","rows"} or b["kind"] not in UNITS:
        raise ValueError("Schema non valido")
    at=datetime.fromisoformat(b["acquired"])
    if at.tzinfo is None or at>now:raise ValueError("Timestamp non valido")
    kind=b["kind"];today=at.astimezone(ROME).date();seen=set()
    if not isinstance(b["rows"],list) or not 1<=len(b["rows"])<=10000:raise ValueError("Limite record")
    for r in b["rows"]:
        keys={"period","scope","value"}|({"imcei"} if kind=="industry" else {"hours"})
        if not isinstance(r,dict) or set(r)!=keys:raise ValueError("Record non valido")
        scope=r["scope"];d=date.fromisoformat(r["period"])
        if not isinstance(scope,list) or len(scope)!={"capacity":4,"industry":3,"exchange":1}[kind] or any(field({"s":s},"s")!=s for s in scope):raise ValueError("Perimetro non valido")
        k=(d,tuple(scope))
        if k in seen:raise ValueError("Record duplicato")
        seen.add(k)
        v=r["value"]
        if kind=="industry":
            if d.day!=1 or d>=today.replace(day=1) or scope[1] not in SECTORS or scope[2] not in ("AT","MT"):raise ValueError("Mese o perimetro non valido")
            if v is None and r["imcei"] is None:raise ValueError("Valore assente")
            for val in (v,r["imcei"]):
                if val is not None and (type(val) not in (float,int) or not math.isfinite(val) or not 0<=val<=1e9):raise ValueError("Valore non valido")
        else:
            hours=int((_start(d+timedelta(days=1))-_start(d)).total_seconds()/3600)
            if d>today+timedelta(days=2) or r["hours"]!=hours or type(v) not in (float,int) or not math.isfinite(v) or abs(v)>1e9 or kind=="capacity" and v<0:raise ValueError("Giorno non valido")
    return b


def digest(b):
    return sha256(json.dumps(b,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def merge(old,new,now):
    data={}
    for b in [*old,*new]:
        validate(b,now)
        data[digest(b)]=b
    result=sorted(data.values(),key=lambda b:(datetime.fromisoformat(b["acquired"]),digest(b)))
    if len(result)>MAX_BATCH or len(json.dumps(result,allow_nan=False).encode())>MAX_BYTES:raise ValueError("Archivio al limite: esporta prima di svuotare.")
    return result


def acquire(client,secret,kind,first,last,now=None,clock=utc_now):
    now=now or utc_now()
    today=now.astimezone(ROME).date()
    if kind=="capacity":
        if not 0<=(last-first).days<3 or last>today+timedelta(days=2):raise ValueError("Finestra capacità: massimo tre giorni, fino a D+2.")
        url=CAP;params={"dateFrom":first.strftime("%d/%m/%Y"),"dateTo":(last+timedelta(days=1)).strftime("%d/%m/%Y")}
    elif kind=="industry":
        if first!=last or first.day!=1 or first>=today.replace(day=1):raise ValueError("Seleziona un mese concluso.")
        url=IMCEI;params={"year":first.year,"month":first.month}
    else:raise ValueError("Fonte non automatizzata")
    token=get_token(client,secret)
    payload=_json_request("GET",url,params=params,headers={"Authorization":"Bearer "+token,"Accept":"application/json"})
    rows=gas_days(kind,get_rows(payload,"expected_available_capacity"),first,last) if kind=="capacity" else parse_industry(payload,first)
    at=clock()
    return validate(batch(kind,rows,at),at)


def import_exchange(payload,first,last,now):
    if not 0<=(last-first).days<14 or last>now.astimezone(ROME).date()+timedelta(days=2):raise ValueError("Finestra scambi: massimo 14 giorni, fino a D+2.")
    return validate(batch("exchange",gas_days("exchange",get_rows(payload,"scheduled_foreign_exchange"),first,last),now),now)


def scopes(batches,kind):
    return sorted({tuple(r["scope"]) for b in batches if b["kind"]==kind for r in b["rows"]})


def latest_rows(batches,kind,scope,now,fieldname="value"):
    """Only the latest acquired unambiguous value for each date and exact scope."""
    groups={}
    for b in batches:
        at=datetime.fromisoformat(b["acquired"])
        if b["kind"]!=kind or at>now:continue
        for r in b["rows"]:
            if tuple(r["scope"])!=tuple(scope):continue
            v=r.get(fieldname);k=r["period"]
            old=groups.get(k)
            if old is None or at>old[0]:groups[k]=(at,{v})
            elif at==old[0]:old[1].add(v)
    return [{"period":d,"value":next(iter(v)),"acquired":at.isoformat()}
            for d,(at,v) in sorted(groups.items()) if len(v)==1 and next(iter(v)) is not None]


def join_context(samples,batches,kind,scope,asof):
    """No historical backfill leakage. Industry uses latest completed month at origin."""
    groups={}
    for b in batches:
        if b["kind"]!=kind:continue
        at=datetime.fromisoformat(b["acquired"]).astimezone(ROME).replace(tzinfo=None)
        if at>asof:continue
        for r in b["rows"]:
            if tuple(r["scope"])==tuple(scope):
                groups.setdefault(r["period"],[]).append((at,digest(b),r["imcei"] if kind=="industry" else r["value"]))
    rows=[]
    col="context_"+kind
    for target,r in samples.iterrows():
        cutoff=r.origin+pd.Timedelta(hours=15)
        if kind=="industry":
            first=r.origin.replace(day=1)
            periods=[p for p in groups if pd.Timestamp(p)<first and (first-pd.Timestamp(p)).days<=93]
        else:periods=[target.date().isoformat()]
        candidates=[(p,*v) for p in periods for v in groups.get(p,[]) if v[0]<=cutoff]
        if not candidates:continue
        period=max(v[0] for v in candidates)
        candidates=[v for v in candidates if v[0]==period]
        newest=max(v[1] for v in candidates)
        same=[v for v in candidates if v[1]==newest]
        if len({v[3] for v in same})!=1 or same[0][3] is None:continue
        p,at,key,val=same[0]
        rows.append({"target":target,"power_day":p,"power_acquired":at.isoformat(),"power_sha256":key,col:val})
    if not rows:return samples.assign(**{col:float("nan")}),[col]
    return samples.join(pd.DataFrame(rows).set_index("target")),[col]
