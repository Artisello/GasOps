"""Optional public operational context. No merging with the demand or settlement series."""
import csv
from datetime import date, datetime, timedelta
from hashlib import sha256
from io import StringIO
import json
import math
import os
import re

import pandas as pd

from .data import ROME
from .models import utc_now
from .public_data import SourceSchemaError, retrieve

AGSI_URL = "https://agsi.gie.eu/api"
AGSI_SOURCE = "https://agsi.gie.eu/"
ALSI_SOURCE = "https://alsi.gie.eu/"
IIP_SOURCE = "https://iip.gie.eu/"
GIE_TERMS = "https://iip.gie.eu/data-usage"
GIE_CREDIT = {"AGSI+": "Gas Infrastructure Europe (GIE) – AGSI+",
              "ALSI": "Gas Infrastructure Europe (GIE) – ALSI",
              "IIP": "Gas Infrastructure Europe (GIE) – IIP"}
GIE_LINKS = {"AGSI+": AGSI_SOURCE, "ALSI": ALSI_SOURCE, "IIP": IIP_SOURCE}


def gie_key(secrets=None):
    """Read the canonical key or legacy alias, without logging or exposing either."""
    for name in ("GASOPS_GIE_API_KEY","GASOPS_AGSI_API_KEY"):
        value=secrets.get(name,"") if secrets is not None else ""
        if isinstance(value,str) and value.strip():
            return value.strip()
        value=os.getenv(name,"")
        if value.strip():
            return value.strip()
    return ""


def attribution(platform):
    return {"source": GIE_CREDIT[platform], "source_url": GIE_LINKS[platform]}


def attributed_csv(result):
    return result["frame"].assign(**attribution(result["platform"]),
                                  retrieved_at=result["acquired"].isoformat()).to_csv(index=False)

JARVIS_SOURCE = "https://jarvis.snam.it/public-data?lang=it"
GME_SOURCE = "https://gme.mercatoelettrico.org/it-it/Home/Esiti/Gas/PrezzoSbilanciamento/Esiti/PrezzoSbilanciamento"
GME_TERMS = "https://www.mercatoelettrico.org/Portals/0/Documents/it-IT/20261013CONDIZIONI_GENERALI_API.pdf"
JARVIS_COLUMNS = ("gas_day","published_at","expected_withdrawal_gwh","sas_gwh","expected_linepack_gwh")
STORAGE_COLUMNS = {"gasInStorage":"stock_twh","workingGasVolume":"capacity_twh","full":"fill_pct",
                   "injection":"injection_gwh_d","withdrawal":"withdrawal_gwh_d"}


def number(value, *, signed=False):
    if value is None or str(value).strip() in ("", "-", "N/A", "n/a"):
        return None
    if isinstance(value,bool):
        raise SourceSchemaError("Valore numerico non valido.")
    if isinstance(value,str):
        value=value.strip()
        # Official GIE v007 examples use decimal commas as well as dots.
        # Do not guess thousands separators or mixed-locale formats.
        if re.fullmatch(r"[+-]?\d+,\d+",value):
            value=value.replace(",",".")
    try:
        v=float(value)
    except (ValueError,TypeError):
        raise SourceSchemaError("Valore numerico non valido.") from None
    if not math.isfinite(v) or (not signed and v<0):
        raise SourceSchemaError("Valore numerico non valido.")
    return v


def _gie_payload(text):
    payload=json.loads(text)
    if not isinstance(payload,dict):
        raise SourceSchemaError("Risposta GIE non riconosciuta")
    if payload.get("error"):
        error=str(payload.get("error","")).lower()+" "+str(payload.get("message","")).lower()
        if "access denied" in error or "api key" in error or "unauthor" in error:
            raise SourceSchemaError("Accesso GIE negato: verifica chiave e abilitazioni")
        if "too many" in error or "rate limit" in error:
            raise SourceSchemaError("Limite richieste GIE raggiunto")
        raise SourceSchemaError("Il servizio GIE ha segnalato un errore")
    return payload


def _inventory_rows(text, platform):
    payload=_gie_payload(text)
    data=payload.get("data")
    if isinstance(data,dict):
        data=[data]
    if not isinstance(data,list) or not data:
        raise SourceSchemaError("Nessun record "+platform)
    if int(payload.get("last_page",0))!=1:
        raise SourceSchemaError("Risposta "+platform+" paginata o incompleta")
    if len(data)>92 or any(not isinstance(row,dict) for row in data):
        raise SourceSchemaError("Record "+platform+" non validi")
    if payload.get("total") is not None and int(payload["total"])!=len(data):
        raise SourceSchemaError("Conteggio record "+platform+" incoerente")
    return data


def parse_agsi(text, acquired, *, scope, cached=False, failed=False):
    data=_inventory_rows(text,"AGSI")
    today=acquired.astimezone(ROME).date()
    rows={}
    for item in data:
        if str(item["code"]).upper()!=scope:
            raise SourceSchemaError("Perimetro AGSI non riconosciuto.")
        day=date.fromisoformat(item["gasDayStart"])
        if not today-timedelta(days=91)<=day<today:
            raise SourceSchemaError("Giorno-gas AGSI fuori intervallo.")
        status=item["status"]
        if status not in ("C","E","N"):
            raise SourceSchemaError("Stato AGSI non riconosciuto.")
        row={"gas_day":day, "status":status}
        for source,target in STORAGE_COLUMNS.items():
            row[target]=None if status=="N" else number(item.get(source))
        if day in rows and rows[day]!=row:
            raise SourceSchemaError("Pubblicazioni AGSI in conflitto.")
        rows[day]=row
    frame=pd.DataFrame(list(rows.values())).sort_values("gas_day").reset_index(drop=True)
    if not frame["stock_twh"].notna().any():
        raise SourceSchemaError("Giacenze AGSI non disponibili.")
    # Keep source percentages as published (including values above 100%).
    # Show a mismatch rather than overwriting the publisher's fields.
    frame[list(STORAGE_COLUMNS.values())]=frame[list(STORAGE_COLUMNS.values())].astype(float)
    capacity=frame["capacity_twh"].where(frame["capacity_twh"]>0)
    frame["review"]=((frame["capacity_twh"]<=0) |
        ((frame["stock_twh"]/capacity*100-frame["fill_pct"]).abs()>0.5))
    return {"frame":frame,"scope":scope,"acquired":acquired,"cached":cached,"failed":failed,
            "platform":"AGSI+",**attribution("AGSI+")}


def load_agsi(store,api_key,scope="IT",*,now=None,refresh=False):
    if scope not in ("IT","EU") or not api_key or not api_key.strip():
        raise ValueError("Chiave AGSI o perimetro non valido.")
    now=now or utc_now()
    today=now.astimezone(ROME).date()
    last=today-timedelta(days=1)
    params={"from":(last-timedelta(days=89)).isoformat(),"to":last.isoformat(),"size":100,"page":1}
    params.update({"country":"IT"} if scope=="IT" else {"type":"eu"})
    def parse(text,acquired,**kwargs):
        return parse_agsi(text,acquired,scope=scope,**kwargs)
    return retrieve(store,key="agsi-public-v2-"+scope,name="GIE AGSI+",url=AGSI_URL,
                    parse=parse,ttl=timedelta(hours=24),params=params,
                    attempts=1,headers={"x-key":api_key.strip(),"Accept":"application/json"},
                    timeout=(5,20),diagnostics=True,refresh=refresh)


def jarvis_template():
    # Deliberately header-only; no fabricated source observations.
    return ",".join(JARVIS_COLUMNS)+"\n"


def parse_jarvis(content:bytes, *, now=None):
    """Explicitly mapped public report extract, not the native publisher format.

    Preserve every publication time; same day/version conflicts fail closed.
    The input fields are estimates from the report, not recomputed SAS.
    """
    if not content or len(content)>1_000_000:
        raise ValueError("CSV vuoto o superiore a 1 MB.")
    now=now or utc_now()
    try:
        raw=content.decode("utf-8-sig")
        reader=csv.DictReader(StringIO(raw),strict=True)
        if tuple(reader.fieldnames or ())!=JARVIS_COLUMNS:
            raise ValueError("Usa esattamente le intestazioni del modello GasOps.")
        rows={}
        for i,item in enumerate(reader):
            if i>=2000 or None in item or any(v is None for v in item.values()):
                raise ValueError("CSV non valido o superiore a 2.000 record.")
            gas_day=date.fromisoformat(item["gas_day"])
            issued=datetime.fromisoformat(item["published_at"].replace("Z","+00:00"))
            if issued.tzinfo is None or issued>now:
                raise ValueError("La pubblicazione richiede data e offset, non futuri.")
            # Estimates for G only, not G+1/G+2; require the publication
            # inside the indicated Italian gas day.
            local=issued.astimezone(ROME)
            label=local.date() if local.hour>=6 else local.date()-timedelta(days=1)
            if gas_day!=label:
                raise ValueError("Pubblicazione non appartenente al giorno-gas G.")
            row={"gas_day":gas_day,"published_at":issued,
                 "expected_withdrawal_gwh":number(item["expected_withdrawal_gwh"]),
                 "sas_gwh":number(item["sas_gwh"],signed=True),
                 "expected_linepack_gwh":number(item["expected_linepack_gwh"])}
            if all(row[k] is None for k in JARVIS_COLUMNS[2:]):
                raise ValueError("Riga priva di stime.")
            key=(gas_day,issued)
            if key in rows and rows[key]!=row:
                raise ValueError("Versioni Jarvis in conflitto.")
            rows[key]=row
    except (UnicodeError,csv.Error) as exc:
        raise ValueError("CSV non leggibile.") from exc
    if not rows:
        raise ValueError("Nessuna pubblicazione importata.")
    versions=pd.DataFrame(list(rows.values())).sort_values(["gas_day","published_at"])
    latest=versions.drop_duplicates("gas_day",keep="last").reset_index(drop=True)
    return {"versions":versions,"latest":latest,"sha256":sha256(content).hexdigest()}


def parse_alsi(text, acquired, *, scope, cached=False, failed=False):
    """LNG liquid volume remains separate from energy; no assumed conversion factor."""
    data=_inventory_rows(text,"ALSI")
    today=acquired.astimezone(ROME).date()
    rows={}
    for item in data:
        if str(item["code"]).upper()!=scope:
            raise SourceSchemaError("Perimetro ALSI non riconosciuto.")
        day=date.fromisoformat(item["gasDayStart"])
        if not today-timedelta(days=91)<=day<today:
            raise SourceSchemaError("Giorno-gas ALSI fuori intervallo.")
        status=item.get("status")
        if status not in (None,"C","E","N"):
            raise SourceSchemaError("Stato ALSI non riconosciuto.")
        stock=item.get("inventory")
        # v007 documents scalar inventory in 10^3 m3 LNG; newer responses
        # may separate liquid volume (lng) and energy (gwh).
        liquid=stock.get("lng") if isinstance(stock,dict) else stock
        energy=stock.get("gwh") if isinstance(stock,dict) else None
        maximum=item.get("dtmi")
        if isinstance(maximum,dict):
            maximum=maximum.get("lng")
        row={"gas_day":day,"status":status or "non indicato"}
        for name,value in {"inventory_1000m3_lng":liquid,"inventory_gwh":energy,
                           "dtmi_1000m3_lng":maximum,"sendout_gwh_d":item.get("sendOut"),
                           "dtrs_gwh_d":item.get("dtrs")}.items():
            row[name]=None if status=="N" else number(value)
        if day in rows and rows[day]!=row:
            raise SourceSchemaError("Pubblicazioni ALSI in conflitto.")
        rows[day]=row
    frame=pd.DataFrame(list(rows.values())).sort_values("gas_day").reset_index(drop=True)
    measure_columns=[c for c in frame.columns if c not in ("gas_day","status")]
    frame[measure_columns]=frame[measure_columns].astype(float)
    if not frame[["sendout_gwh_d","inventory_1000m3_lng","inventory_gwh"]].notna().any().any():
        raise SourceSchemaError("Dati ALSI non disponibili.")
    denominator=frame["dtrs_gwh_d"].where(frame["dtrs_gwh_d"]>0)
    frame["sendout_reference_pct"]=100*frame["sendout_gwh_d"]/denominator
    return {"frame":frame,"scope":scope,"acquired":acquired,"cached":cached,"failed":failed,
            "platform":"ALSI",**attribution("ALSI")}


def load_alsi(store,api_key,scope="IT",*,now=None,refresh=False):
    if scope not in ("IT","EU") or not api_key or not api_key.strip():
        raise ValueError("Chiave ALSI o perimetro non valido.")
    now=now or utc_now()
    last=now.astimezone(ROME).date()-timedelta(days=1)
    params={"from":(last-timedelta(days=89)).isoformat(),"to":last.isoformat(),"size":100,"page":1}
    params.update({"country":"IT"} if scope=="IT" else {"type":"eu"})
    def parse(text,acquired,**kwargs):
        return parse_alsi(text,acquired,scope=scope,**kwargs)
    return retrieve(store,key="alsi-public-v2-"+scope,name=GIE_CREDIT["ALSI"],url=ALSI_SOURCE+"api",
                    parse=parse,ttl=timedelta(hours=24),params=params,
                    attempts=1,headers={"x-key":api_key.strip(),"Accept":"application/json"},
                    timeout=(5,20),diagnostics=True,refresh=refresh)


IIP_PAGE_SIZE = 20
IIP_MAX_PAGE_SIZE = 50  # Actual GIE meta.per_page observed in deployment.


def _page_count(value, field="last_page"):
    if value is None:
        return None
    if isinstance(value,bool) or not re.fullmatch(r"[0-9]{1,9}",str(value)):
        raise SourceSchemaError(f"IIP: {field} non è un intero non negativo")
    return int(value)


def iip_pagination_diagnostic(payload, pages, record_count):
    """Metadata-only diagnostic, without message content, URLs or credentials."""
    # List known paging fields and safe structural names, never arbitrary
    # response values. Numeric values are limited to known paging fields.
    numeric_names={"lastpage","totalpages","pagecount","total","count","totalcount",
                   "totalrecords","recordcount","currentpage","page","size","pagesize",
                   "perpage","limit","offset","last","current","records","numberofpages",
                   "numberofrecords","totalitems","itemcount"}
    container_names={"pagination","paging","pageinfo","meta","metadata","page"}
    def normalized(name):
        return re.sub(r"[^a-z0-9]","",name.lower())
    def describe(obj):
        result={}
        for key,val in obj.items():
            name=normalized(key)
            if name in numeric_names and isinstance(val,(int,str)) and not isinstance(val,bool):
                if re.fullmatch(r"[0-9]{1,9}",str(val)):
                    result[key]=int(val)
        return result
    safe_keys=[key for key in payload if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,39}",key)
               and not any(x in normalized(key) for x in ("key","token","secret","password","auth","credential"))]
    details={"source":GIE_CREDIT["IIP"],"source_url":IIP_SOURCE,
             "returned_records":record_count,"requested_page":1,"requested_size":IIP_PAGE_SIZE,
             "recognized_last_page":pages,"top_level_fields":sorted(safe_keys)[:40],
             "numeric_pagination_fields":describe(payload),"nested_pagination_fields":{}}
    for key in safe_keys:
        if normalized(key) in container_names and isinstance(payload[key],dict):
            details["nested_pagination_fields"][key]=describe(payload[key])
    return details


def parse_iip(text,acquired,*,cached=False,failed=False):
    """Keep original UMM records. Unknown pagination is explicitly unverified."""
    payload=_gie_payload(text)
    legacy_pages=_page_count(payload.get("last_page"))
    meta=payload.get("meta")
    if meta is not None and not isinstance(meta,dict):
        raise SourceSchemaError("IIP: meta non valido")
    meta=meta or {}
    nested_pages=_page_count(meta.get("last_page"))
    if legacy_pages is not None and nested_pages is not None and legacy_pages!=nested_pages:
        raise SourceSchemaError("IIP: metadati di paginazione in conflitto")
    pages=nested_pages if nested_pages is not None else legacy_pages
    current=_page_count(meta.get("current_page"),"current_page")
    per_page=_page_count(meta.get("per_page"),"per_page")
    total=_page_count(meta.get("total"),"total")
    if current is not None and current!=1:
        raise SourceSchemaError("IIP: la pagina restituita non è la prima")
    if per_page is not None and not 1<=per_page<=IIP_MAX_PAGE_SIZE:
        raise SourceSchemaError("IIP: dimensione della pagina fuori dal limite supportato (50)")
    if "data" not in payload:
        raise SourceSchemaError("IIP: campo data assente nella risposta JSON")
    data=payload["data"]
    record_keys=None
    if data is None or data=={}:
        if pages!=0 and not (total==0 and pages==1 and current==1 and per_page is not None):
            raise SourceSchemaError("IIP: data vuoto senza conferma di zero risultati")
        messages=[]
    elif isinstance(data,list):
        messages=data
    elif isinstance(data,dict):
        # Accept a single identifiable record or an associative collection.
        # This compatibility path preserves source records and keys; it does
        # not claim the authenticated publisher schema has been verified.
        ids={"messageid","messageidentifier","ummid","id"}
        fields={re.sub(r"[^a-z0-9]","",k.lower()) for k in data}
        if ids & fields:
            messages=[data]
        elif data and all(isinstance(v,dict) and v for v in data.values()):
            record_keys=list(data.keys())
            messages=list(data.values())
        else:
            raise SourceSchemaError("IIP: oggetto data non riconducibile a messaggi")
    else:
        raise SourceSchemaError("IIP: data non è una lista o un oggetto JSON")
    if len(messages)>(per_page if per_page is not None else IIP_PAGE_SIZE):
        raise SourceSchemaError("IIP: la risposta supera la dimensione di pagina supportata")
    if any(not isinstance(r,dict) or not r for r in messages):
        raise SourceSchemaError("IIP: uno o più record non sono oggetti JSON validi")
    if (pages==0 and messages) or (pages is not None and pages>1 and not messages):
        raise SourceSchemaError("IIP: paginazione incompatibile con il numero di record")
    if not messages and (pages is None or payload.get("message")):
        raise SourceSchemaError("IIP: risposta vuota non confermata; consultare il portale")
    if total is not None:
        if total<len(messages) or (total>0 and not messages):
            raise SourceSchemaError("IIP: totale incompatibile con i messaggi ricevuti")
        if pages==0 and total!=0:
            raise SourceSchemaError("IIP: zero pagine con totale positivo")
        if pages==1 and total!=len(messages):
            raise SourceSchemaError("IIP: pagina unica con conteggio incompleto")
        if pages is not None and per_page is not None:
            expected=(total+per_page-1)//per_page
            if pages!=expected and not (total==0 and pages==1):
                raise SourceSchemaError("IIP: totale e numero di pagine incoerenti")
            if len(messages)!=min(total,per_page):
                raise SourceSchemaError("IIP: conteggio della prima pagina incoerente")
    verified=(nested_pages is not None and current==1 and per_page is not None and total is not None)
    return {"messages":messages,"record_keys":record_keys,"pages":pages,
            "reported_total":total,"server_page_size":per_page,"pagination_verified":verified,
            "partial":pages is None or pages>1,"acquired":acquired,"cached":cached,"failed":failed,
            "pagination_diagnostic":iip_pagination_diagnostic(payload,pages,len(messages)),
            "platform":"IIP",**attribution("IIP")}


def load_iip(store,api_key,*,now=None,refresh=False):
    if not api_key or not api_key.strip():
        raise ValueError("Chiave IIP non valida.")
    now=now or utc_now()
    today=now.astimezone(ROME).date()
    # Bounded active messages intersecting the requested period. First page
    # only: no claim of complete event coverage or available capacity.
    params={"from":today.isoformat(),"to":(today+timedelta(days=7)).isoformat(),
            "status":"active","size":IIP_PAGE_SIZE,"page":1}
    return retrieve(store,key="iip-active-v2-"+today.isoformat(),name=GIE_CREDIT["IIP"],
                    url=IIP_SOURCE+"api",parse=parse_iip,ttl=timedelta(hours=2),
                    params=params,attempts=1,headers={"x-key":api_key.strip(),"Accept":"application/json"},
                    timeout=(5,20),diagnostics=True,refresh=refresh,max_bytes=2_000_000)


def attributed_iip_json(result):
    return json.dumps({**attribution("IIP"),"retrieved_at":result["acquired"].isoformat(),
                       "pages":result["pages"],"partial":result["partial"],
                       "reported_total":result.get("reported_total"),"server_page_size":result.get("server_page_size"),
                       "pagination_verified":result.get("pagination_verified",False),
                       "record_keys":result.get("record_keys"),"pagination_diagnostic":result.get("pagination_diagnostic"),
                       "messages":result["messages"]},ensure_ascii=False,indent=2,allow_nan=False)
