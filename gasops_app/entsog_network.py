"""Daily transport data for one explicit ENTSOG operator-point-direction."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import csv
import io
import json
import re

from .entsog import URL, SOURCE, gas_timestamp, _start, _last_completed
from .public_data import retrieve, SourceSchemaError
from .models import utc_now

MANUAL = "https://transparency.entsog.eu/api/archiveDirectories/8/api-manual/ENTSOG_TP_API_UserManual_v3.0.pdf"
TERMS = "https://transparency.entsog.eu/pdf/Terms_and_Conditions_of_Use.pdf"
CATALOG = "https://transparency.entsog.eu/api/v1/operatorpointdirections.csv"
PRESET_REFERENCE = "https://energy-desk-two.vercel.app/data?commodity=natgas"
# Candidate mapping from third-party catalogue; live identity must be checked.
PRESETS = {"Mazara del Vallo (SRG, ingresso)": "IT-TSO-0001ITP-00093entry",
           "Melendugno (SRG, ingresso)": "IT-TSO-0001ITP-00008entry"}
INDICATORS = ("Physical Flow", "Nomination", "Renomination", "Allocation",
              "Firm Technical", "Firm Booked", "Firm Available")
NAMES = dict(zip(INDICATORS, ("Flusso fisico", "Nomina", "Rinomina", "Allocazione",
                            "Capacità tecnica firm", "Capacità prenotata firm",
                            "Capacità disponibile firm"), strict=True))
LIMIT = 500
SCALE = Decimal("1000000")


@dataclass(frozen=True)
class NetworkResult:
    point: str
    labels: tuple
    first: date
    last: date
    rows: tuple
    acquired: datetime
    cached: bool
    failed: bool
    metadata_warning: bool

    @property
    def credit(self):
        return f"ENTSOG TP Transport Data {self.acquired.astimezone(timezone.utc):%d-%m-%Y} {SOURCE}"


def check_point(point):
    if not isinstance(point,str) or not re.fullmatch(r"[A-Z]{2}-TSO-\d{4}ITP-\d{5}(?:entry|exit)",point):
        raise SourceSchemaError("Usa una chiave operatore-punto ITP-direzione dal catalogo ENTSOG.")
    return point


def query_params(point, first, last):
    check_point(point)
    if not isinstance(first,date) or not isinstance(last,date) or not 0 <= (last-first).days < 31:
        raise SourceSchemaError("Seleziona da 1 a 31 giorni gas.")
    return {"pointDirection":point,"from":first.isoformat(),"to":last.isoformat(),
            "indicator":",".join(INDICATORS),"periodType":"day","timeZone":"CET","limit":LIMIT}


def _meta_int(meta, field, default=None):
    value=meta.get(field,default)
    if value is None:
        return None
    if isinstance(value,bool) or not re.fullmatch(r"\d{1,10}",str(value)):
        raise SourceSchemaError("Metadati ENTSOG non validi.")
    return int(value)


def _amount(item):
    flag=str(item.get("isNA",False)).lower()
    if flag not in ("true","false","1","0","none",""):
        raise SourceSchemaError("Flag N/A ENTSOG non riconosciuto.")
    value=item.get("value")
    if flag in ("true","1") or value is None or value=="":
        return None
    if isinstance(value,bool):
        raise SourceSchemaError("Valore ENTSOG non valido.")
    try:
        amount=Decimal(str(value))
    except InvalidOperation as exc:
        raise SourceSchemaError("Valore ENTSOG non numerico.") from exc
    if not amount.is_finite() or abs(amount)>Decimal("1e15"):
        raise SourceSchemaError("Valore ENTSOG fuori limite.")
    # Preserve signs; negative rates are visible but not used in utilization ratios.
    return amount


def parse_network(payload, point, first, last, acquired, *, cached=False, failed=False):
    query_params(point,first,last)
    if not isinstance(payload,dict):
        raise SourceSchemaError("Risposta ENTSOG non valida.")
    items=payload.get("operationalData",payload.get("operationaldatas"))
    if not isinstance(items,list) or not items:
        raise SourceSchemaError("Nessun record ENTSOG restituito.")
    if len(items)>=LIMIT:
        raise SourceSchemaError("Limite record raggiunto: riduci il periodo.")
    meta=payload.get("meta",{})
    if not isinstance(meta,dict):
        raise SourceSchemaError("Metadati ENTSOG non validi.")
    count,total,offset,limit=(_meta_int(meta,k,d) for k,d in
                             (("count",None),("total",None),("offset",0),("limit",LIMIT)))
    if offset!=0 or (count is not None and count!=len(items)) or (total is not None and total<len(items)) or (limit is not None and limit<=len(items)):
        raise SourceSchemaError("Conteggi o pagina ENTSOG incoerenti.")
    warning=count is None or total is None or total!=len(items)
    groups={}
    labels=set()
    required={"operatorKey","pointKey","directionKey","indicator","periodType","unit","periodFrom","periodTo"}
    for item in items:
        if not isinstance(item,dict) or not required<=item.keys():
            raise SourceSchemaError("Campi ENTSOG obbligatori assenti.")
        identity="".join(str(item[k]) for k in ("operatorKey","pointKey","directionKey"))
        if identity.lower()!=point.lower() or item["indicator"] not in INDICATORS or str(item["periodType"]).lower()!="day":
            raise SourceSchemaError("Punto, indicatore o granularità inattesi.")
        if str(item["unit"]).strip().lower()!="kwh/d":
            raise SourceSchemaError("Unità imprevista: atteso kWh/d.")
        day,start,naive=gas_timestamp(item["periodFrom"])
        end_day,end,end_naive=gas_timestamp(item["periodTo"])
        if end_day!=day+timedelta(days=1) or end!=_start(end_day) or start!=_start(day):
            raise SourceSchemaError("Intervallo non allineato al giorno gas.")
        if not first<=day<=last:
            continue
        label=(str(item.get("operatorLabel") or "")[:100],str(item.get("pointLabel") or "")[:100])
        if any(label):
            labels.add(label)
        key=(day,item["indicator"])
        group=groups.setdefault(key,{"values":set(),"status":set(),"naive":False,"last_updates":set()})
        amount=_amount(item)
        group["values"].add(amount)
        status=str(item.get("flowStatus") or "non indicato")[:80]
        group["status"].add(status)
        group["naive"]|=naive or end_naive
        stamp=item.get("lastUpdateDateTime",item.get("lastUpdateDate"))
        if stamp:
            group["last_updates"].add(str(stamp)[:80])
    records=[]
    for i in range((last-first).days+1):
        day=first+timedelta(days=i)
        for indicator in INDICATORS:
            group=groups.get((day,indicator))
            values=group["values"] if group else set()
            value=next(iter(values)) if len(values)==1 else None
            status="conflitto" if len(values)>1 else "assente" if group is None else "N/A" if value is None else "valido"
            records.append({"gas_day":day.isoformat(),"indicator":indicator,"value_kwh_d":value,
                            "value_gwh_d":value/SCALE if value is not None else None,
                            "quality":status,"flow_status":" | ".join(sorted(group["status"])) if group else "",
                            "source_updates":" | ".join(sorted(group["last_updates"])) if group else "",
                            "timestamp_assumed":bool(group and group["naive"])})
    if not any(r["value_kwh_d"] is not None for r in records):
        raise SourceSchemaError("Nessuna osservazione numerica valida nel periodo.")
    return NetworkResult(point,tuple(sorted(labels)),first,last,tuple(records),acquired,cached,failed,warning)


def load_network(store,point,first,last,*,now=None):
    now=now or utc_now()
    params=query_params(point,first,last)
    if last>_last_completed(now):
        raise SourceSchemaError("Seleziona solo giorni gas conclusi.")
    def parser(text,when,**kwargs):
        return parse_network(json.loads(text),point,first,last,when,**kwargs)
    return retrieve(store,key=f"entsog-network-v1:{point}:{first}:{last}",name="ENTSOG Network",
                    url=URL,parse=parser,ttl=timedelta(hours=12),params=params,
                    attempts=1,timeout=(5,30),diagnostics=True,max_bytes=2_000_000)


def daily_metrics(result):
    """Reported same-point comparisons only; no participant imbalance/cross-point sum."""
    days={}
    for row in result.rows:
        days.setdefault(row["gas_day"],{})[row["indicator"]]=row["value_gwh_d"]
    output=[]
    for day,v in sorted(days.items()):
        flow,nom,ren,alloc,tech,booked,available=(v[ind] for ind in INDICATORS)
        def difference(a,b):
            return a-b if a is not None and b is not None else None
        def ratio(a,b):
            return Decimal(100)*a/b if a is not None and a>=0 and b is not None and b>0 else None
        output.append({"gas_day":day,**v,"flow_minus_nomination":difference(flow,nom),
                       "flow_minus_renomination":difference(flow,ren),
                       "allocation_minus_flow":difference(alloc,flow),
                       "technical_utilization_pct":ratio(flow,tech),
                       "booked_technical_pct":ratio(booked,tech)})
    return output


def export_csv(result):
    out=io.StringIO()
    fields=("point_direction","gas_day","indicator","value_kwh_d","value_gwh_d","quality",
            "flow_status","source_updates","timestamp_assumed","extracted_at","source")
    writer=csv.DictWriter(out,fieldnames=fields,lineterminator="\n")
    writer.writeheader()
    # Defend spreadsheet consumers against formula-like external status strings.
    def safe(text):
        return "'"+text if text.lstrip().startswith(("=","+","-","@")) else text
    for row in result.rows:
        writer.writerow({**row,"flow_status":safe(row["flow_status"]),"source_updates":safe(row["source_updates"]),
                         "point_direction":result.point,"extracted_at":result.acquired.isoformat(),"source":result.credit})
    return out.getvalue()
