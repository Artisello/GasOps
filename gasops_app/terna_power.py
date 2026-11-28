"""Terna power context: annual observed statistics and opt-in hourly data.
All joined series use an explicit [06:00,06:00) gas-day label convention.
"""
from datetime import date, datetime, timedelta, timezone
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic
from decimal import Decimal, InvalidOperation
from pathlib import Path
import csv
import json
import os
import re
import math
import requests
from uuid import uuid4

from .data import ROME
from .models import utc_now
from .entsog import _start, query_params as gas_query, parse_month, URL as GAS_URL
from .public_data import SourceSchemaError, SourceUnavailable, retrieve

ANNUAL_URL="https://www.terna.it/it/sistema-elettrico/statistiche/pubblicazioni-statistiche"
CATALOG="https://developer.terna.it/docs/read/apis_catalog"
GEN_DOC=CATALOG+"/generation/Actual_Generation"
LOAD_DOC=CATALOG+"/load/Total_Load"
TOKEN_DOC="https://developer.terna.it/docs/read/Access_Token"
PORTAL="https://dati.terna.it/"
TOKEN="https://api.terna.it/public-api/access-token"
GEN="https://api.terna.it/generation/v2.0/actual-generation"
LOAD="https://api.terna.it/load/v2.0/total-load"
SOURCES=("Thermal","Wind","Photovoltaic","Hydro","Geothermal")
_TOKEN_BATCH=ContextVar("terna_token_batch",default=None)
_SERVICES={
    TOKEN:"autenticazione OAuth",
    GEN:"Actual Generation",
    LOAD:"Total Load",
    "https://api.terna.it/market/v1.0/input/forecast-load":"Load Forecast",
    "https://api.terna.it/generation/v2.0/wind-production-forecast":"Wind Production Forecast",
    "https://api.terna.it/adequacy/v1.0/expected-available-capacity":"Expected Available Capacity",
    "https://api.terna.it/load/v2.0/monthly-index-industrial-electrical-consumption":"IMCEI",
}


class TernaHTTPError(SourceUnavailable):
    """Only controlled metadata; never include provider bodies or credentials."""
    def __init__(self,status,service,business_id=None):
        self.status=status
        self.service=service
        self.business_id=business_id
        auth=service==_SERVICES[TOKEN]
        hints={
            400:"Verifica credenziali e richiesta OAuth." if auth else "Verifica i parametri della richiesta.",
            401:"Verifica chiave e secret." if auth else "Token rifiutato o scaduto.",
            403:"Accesso OAuth negato; verifica chiave e applicazione Public." if auth else
                "Accesso al servizio negato; verifica abilitazione nel Developer Portal.",
            404:"Endpoint non trovato; verifica il catalogo ufficiale.",
            429:"Limite richieste raggiunto; riprova dopo il ripristino della quota.",
        }
        super().__init__(f"Terna · {service}: HTTP {status}. "+hints.get(status,"Servizio non disponibile."))



@contextmanager
def token_batch():
    """Reuse credentials only inside one explicit acquisition, never in UI/cache."""
    marker=_TOKEN_BATCH.set({})
    try:
        yield
    finally:
        _TOKEN_BATCH.reset(marker)
MAX_BYTES=2_000_000
UTC=timezone.utc
METRICS={"demand":"TWh","production_for_consumption":"TWh","net_imports":"TWh",
         "gross_generation":"TWh","net_generation":"TWh","gas_gross":"TWh",
         "gas_gross_yoy":"%","gas_share_thermal":"%","wind_gross":"TWh","hydro_gross":"TWh",
         "bioenergy_gross":"TWh","solid_fuels_gross":"TWh","installed_gross":"GW",
         "renewable_installed":"GW","pv_installed":"GW","wind_installed":"GW","thermal_installed":"GW"}


def annual_rows():
    path=Path(__file__).resolve().parents[1]/"data/terna/annual-2025-summary.csv"
    rows=[]
    seen=set()
    with path.open(encoding="utf-8",newline="") as f:
        reader=csv.DictReader(f,strict=True)
        if reader.fieldnames!=["year","metric","value","unit"]:
            raise ValueError("Schema annuale Terna non valido.")
        for r in reader:
            m=r["metric"]
            if r["year"]!="2025" or m in seen or METRICS.get(m)!=r["unit"]:
                raise ValueError("Metrica annuale non valida.")
            seen.add(m)
            amount=number(r["value"])
            if amount is None:
                raise ValueError("Valore annuale mancante.")
            rows.append({**r,"value":amount,"source":"Terna, Dati statistici 2025, sintesi web",
                         "source_url":ANNUAL_URL,"provenance":"trascrizione valori arrotondati pubblicati"})
    if seen!=set(METRICS):
        raise ValueError("Copertura annuale incompleta.")
    return rows


def credentials(secrets=None):
    def get(key):
        v=secrets.get(key,"") if secrets is not None else ""
        return v.strip() if isinstance(v,str) and v.strip() else os.getenv(key,"").strip()
    return get("GASOPS_TERNA_CLIENT_ID"),get("GASOPS_TERNA_CLIENT_SECRET")


def number(value):
    if value is None or value=="":
        return None
    if isinstance(value,bool):
        raise SourceSchemaError("Valore Terna non valido.")
    try:
        d=Decimal(str(value))
    except InvalidOperation as exc:
        raise SourceSchemaError("Valore Terna non numerico.") from exc
    if not d.is_finite() or d<0 or d>Decimal("1e9"):
        raise SourceSchemaError("Valore Terna fuori limite.")
    return d


def latest_day(now):
    # End of gas day must fall on a calendar day <= D-1 (documented data lag).
    return now.astimezone(ROME).date()-timedelta(days=2)


def dates(first,last,now):
    if not 0<=(last-first).days<14 or last>latest_day(now):
        raise SourceSchemaError("Seleziona da 1 a 14 giorni gas conclusi, fino a D-2.")
    return {"dateFrom":first.strftime("%d/%m/%Y"),"dateTo":(last+timedelta(days=1)).strftime("%d/%m/%Y")}


def _json_request(method,url,*,data=None,params=None,headers=None):
    # No redirects, logs, URL/body details or token echo. Only fixed endpoints.
    if url not in _SERVICES or method!=("POST" if url==TOKEN else "GET"):
        raise SourceUnavailable("Endpoint Terna non autorizzato dal catalogo locale.")
    headers=dict(headers or {})
    business_id=None
    if method=="GET":
        business_id=str(uuid4())
        headers["businessID"]=business_id
    else:
        headers["Content-Type"]="application/x-www-form-urlencoded"
    try:
        with requests.request(method,url,data=data,params=params,headers=headers,
                              timeout=(5,25),allow_redirects=False,stream=True) as response:
            if response.status_code!=200:
                if response.status_code==401 and _TOKEN_BATCH.get() is not None:
                    _TOKEN_BATCH.get().clear()
                raise TernaHTTPError(response.status_code,_SERVICES[url],business_id)
            body=bytearray()
            for c in response.iter_content(16384):
                body.extend(c)
                if len(body)>MAX_BYTES:
                    raise SourceUnavailable("Terna: risposta superiore a 2 MB.")
            payload=json.loads(body.decode("utf-8-sig"))
    except (requests.RequestException,ValueError):
        raise SourceUnavailable(f"Terna · {_SERVICES[url]}: connessione o risposta non valida.") from None
    if not isinstance(payload,dict):
        raise SourceUnavailable("Terna: risposta non riconosciuta.")
    return payload


def get_token(client,secret):
    if not client or not secret:
        raise SourceUnavailable("Credenziali Terna non configurate.")
    cache=_TOKEN_BATCH.get()
    key=(client,secret)
    if cache is not None and key in cache:
        cached,expiry=cache[key]
        if isinstance(cached,TernaHTTPError):
            raise TernaHTTPError(cached.status,cached.service)
        if expiry>monotonic():
            return cached
    started=monotonic()
    try:
        payload=_json_request("POST",TOKEN,data={"client_id":client,"client_secret":secret,
                              "grant_type":"client_credentials"},headers={"Accept":"application/json"})
    except TernaHTTPError as error:
        # Do not repeat rejected authentication for each service in one batch.
        if cache is not None and error.status in (400,401,403,429):
            cache[key]=(TernaHTTPError(error.status,error.service),0)
        raise
    token=payload.get("access_token")
    if not isinstance(token,str) or not token or len(token)>4096 or any(c.isspace() for c in token):
        raise SourceUnavailable("Terna: token non valido.")
    lifetime=payload.get("expires_in")
    if cache is not None and isinstance(lifetime,(int,float)) and not isinstance(lifetime,bool) and math.isfinite(lifetime) and lifetime>15:
        cache[key]=(token,started+min(lifetime,300)-15)
    return token


def _timestamp(item,minutes):
    stamp,offset,tz=(item.get(k) for k in ("date","date_offset","date_tz"))
    if (tz!="Europe/Rome" or not isinstance(stamp,str) or
        not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:00",stamp) or
        not isinstance(offset,str) or not re.fullmatch(r"\+[0-9]{2}:[0-9]{2}",offset)):
        raise SourceSchemaError("Timestamp Terna non riconosciuto.")
    dt=datetime.fromisoformat(stamp+offset)
    local=dt.astimezone(ROME)
    if local.replace(tzinfo=None)!=dt.replace(tzinfo=None) or local.utcoffset()!=dt.utcoffset() or dt.minute%minutes:
        raise SourceSchemaError("Timestamp Terna incompatibile con Europe/Rome o granularità.")
    return dt.astimezone(UTC)


def parse_power(payload,kind,first,last):
    key,step=("actual_generation",60) if kind=="generation" else ("total_load",15)
    if not isinstance(payload,dict) or not isinstance(payload.get("result"),dict) or payload["result"].get("status")!="Completed":
        raise SourceSchemaError("Stato risposta Terna non completato.")
    rows=payload.get(key)
    if not isinstance(rows,list) or not rows or len(rows)>12000:
        raise SourceSchemaError("Array Terna assente o troppo grande.")
    groups={}
    start,end=_start(first),_start(last+timedelta(days=1))
    for item in rows:
        if not isinstance(item,dict):
            raise SourceSchemaError("Record Terna non valido.")
        stamp=_timestamp(item,step)
        if kind=="generation":
            field=item.get("primary_source")
            if field=="Self-consumption":
                continue  # not added to other categories; possible overlap
            if field not in SOURCES or "actual_generation_GWh" not in item:
                raise SourceSchemaError("Fonte o quantità Terna inattesa.")
            vals={field:number(item["actual_generation_GWh"])}
        else:
            if item.get("bidding_zone")!="Italy" or "total_load_MW" not in item:
                raise SourceSchemaError("Perimetro o quantità Terna inattesi.")
            vals={"load":number(item["total_load_MW"]),"load_forecast":number(item.get("forecast_total_load_MW"))}
        if not start<=stamp<end:
            continue
        for field,value in vals.items():
            groups.setdefault((stamp,field),set()).add(value)
    result=[]
    fields=SOURCES if kind=="generation" else ("load","load_forecast")
    for i in range((last-first).days+1):
        day=first+timedelta(days=i)
        begin,finish=_start(day),_start(day+timedelta(days=1))
        expected=int((finish-begin).total_seconds()//(step*60))
        for field in fields:
            values=[]
            for slot in range(expected):
                candidates=groups.get((begin+timedelta(minutes=slot*step),field),set())
                if len(candidates)==1:
                    val=next(iter(candidates))
                    if val is not None:
                        values.append(val)
            value=sum(values,Decimal(0)) if len(values)==expected else None
            if value is not None and kind=="load":
                value*=Decimal("0.00025") # MW × 0.25 h / 1000
            result.append({"gas_day":day.isoformat(),"metric":field,"gwh":value,
                           "valid_slots":len(values),"expected_slots":expected})
    if not any(r["gwh"] is not None for r in result):
        raise SourceSchemaError("Terna: nessuna serie giorno gas completa.")
    return result


def load_power(client,secret,first,last,*,now=None):
    now=now or utc_now()
    params=dates(first,last,now)
    token=get_token(client,secret)
    headers={"Authorization":"Bearer "+token,"Accept":"application/json"}
    # Independent services: neither denial can erase the other's validated data.
    rows=[];notes=[]
    for kind,url,filters in (("generation",GEN,{"type":list(SOURCES)}),
                             ("load",LOAD,{"biddingZone":"Italy"})):
        try:
            payload=_json_request("GET",url,params={**params,**filters},headers=headers)
            rows.extend(parse_power(payload,kind,first,last))
        except SourceUnavailable as error:
            notes.append(str(error))
            if isinstance(error,TernaHTTPError) and error.status in (401,429):
                break
        except (ValueError,TypeError,KeyError):
            notes.append(f"Terna · {_SERVICES[url]}: copertura o schema non validabile.")
    if not rows:
        raise SourceUnavailable(" · ".join(notes))
    return {"rows":rows,"acquired":now.isoformat(),"first":first,"last":last,
            "warning":" · ".join(notes) or None}


def load_gas(store,first,last,*,now=None):
    # Reuse validated SRG mapping; query one bounded period, not 13 months.
    now=now or utc_now()
    dates(first,last,now)
    def parse(text,when,**kwargs):
        return parse_month(json.loads(text),first,last,when,allow_partial=True,**kwargs)
    month=retrieve(store,key=f"terna-gas-srg-v1:{first}:{last}",name="ENTSOG SRG",
                   url=GAS_URL,parse=parse,params=gas_query(first,last),
                   ttl=timedelta(hours=12),attempts=1,timeout=(5,20),diagnostics=True)
    return {"gas":{day.isoformat():value for (day,field),value in month.values.items()
                   if field=="power_gwh" and value is not None},
            "cached":month.cached,"failed":month.failed,"acquired":month.retrieved_at.isoformat(),
            "metadata_warning":month.metadata_warning}


def paired(rows,gas):
    result=[]
    by={}
    for row in rows:
        by.setdefault(row["gas_day"],{})[row["metric"]]=row["gwh"]
    for day,v in sorted(by.items()):
        thermal=v.get("Thermal")
        observed=gas.get(day)
        if thermal is not None and observed is not None and math.isfinite(observed):
            result.append({"gas_day":day,"thermal_gwh":float(thermal),"sr_gas_gwh":float(observed)})
    return result


def correlation(rows):
    if len(rows)<7:
        return None
    x=[r["thermal_gwh"] for r in rows]
    y=[r["sr_gas_gwh"] for r in rows]
    mx,my=sum(x)/len(x),sum(y)/len(y)
    dx,dy=[v-mx for v in x],[v-my for v in y]
    denom=math.sqrt(sum(v*v for v in dx)*sum(v*v for v in dy))
    if denom==0:
        return None
    return sum(a*b for a,b in zip(dx,dy,strict=True))/denom
