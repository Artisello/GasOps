"""Read-only projection of IIP messages. Never infer outages, countries or lost volumes.

Column vocabulary follows the public GIE IIP portal. Exact JSON field names
may vary; bounded, explicit aliases are compatibility mappings, not a verified
authenticated message schema. Original records remain the authoritative view.
"""
import csv
from datetime import datetime, timezone
from io import StringIO
import math
import re

from .data import ROME
from .operational_sources import attribution

MISSING = "Non indicato"
FIELDS = {
    "message_id": ("messageId","messageIdentifier","ummId","messageCode","id"),
    "published": ("publicationDateTime","publicationDate","publicationTime","publishedAt","published","publicationDateTimeUTC"),
    "start": ("eventStart","eventStartDate","eventStartDateTime","eventStartUTC"),
    "stop": ("eventStop","eventEnd","eventStopDateTime","eventStopUTC"),
    "asset": ("affectedAssetOrUnit","affectedAssetOrUnitName","affectedAsset","assetName","facilityName","asset"),
    "asset_code": ("affectedAssetOrUnitCode","assetCode","assetEic"),
    "operator": ("marketParticipant","marketParticipantName","reportingEntity","reportingEntityName","operatorName","operator"),
    "country": ("countryCode","country"),
    "kind": ("typeOfUnavailability","unavailabilityType"),
    "event_type": ("typeOfEvent","eventType"),
    "status": ("eventStatus","status"),
    "reason": ("reasonForTheUnavailability","reasonForUnavailability","unavailabilityReason","reason"),
    "remarks": ("remarks","comment","comments"),
    "direction": ("direction",),
    "unit": ("unitOfMeasurement","measurementUnit","capacityUnit","uom","unit"),
    "unavailable": ("unavailableCapacity",),
    "available": ("availableCapacity",),
    "technical": ("technicalCapacity",),
}
CONTAINERS = {"umm","message","event","report","unavailabilityofgasfacilitiesreport",
              "othermarketinformationreport","details","header","publication","asset","marketparticipant"}
TABLE_FIELDS = {
    "published_label":"Pubblicato","asset":"Asset","operator":"Operatore","country":"Paese",
    "event_type":"Tipo evento","status":"Stato UMM","start_label":"Inizio evento",
    "stop_label":"Fine evento","impact":"Capacità indisponibile","reason":"Motivo",
    "message_id":"ID messaggio",
}


def _norm(name):
    return re.sub(r"[^a-z0-9]","",name.lower())


def _scalars(record, depth=0):
    """Only visit named object containers; never flatten capacity intervals."""
    result={}
    for key,val in record.items():
        name=_norm(key)
        if isinstance(val,dict) and depth<2 and name in CONTAINERS:
            if name in {"asset","marketparticipant","reportingentity","operator"}:
                # Explicit nested names have the same meaning as their direct aliases.
                for nested_key,nested_val in val.items():
                    if _norm(nested_key)=="name" and isinstance(nested_val,str):
                        target="assetname" if name=="asset" else "marketparticipantname"
                        result.setdefault(target,[]).append(nested_val.strip())
            nested=_scalars(val,depth+1)
            for k,values in nested.items():
                result.setdefault(k,[]).extend(values)
        elif isinstance(val,(str,int,float)) and not isinstance(val,bool):
            if isinstance(val,float) and not math.isfinite(val):
                continue
            value=str(val).strip()
            if value:
                result.setdefault(name,[]).append(value)
    return result


def _pick(fields, aliases):
    values={v for alias in aliases for v in fields.get(_norm(alias),[])}
    # Ambiguous aliases are not silently resolved.
    return next(iter(values)) if len(values)==1 else None


def _timestamp(value):
    if not value:
        return None
    try:
        stamp=datetime.fromisoformat(value.replace("Z","+00:00"))
        # Without an offset the raw API format is not proved to be UTC.
        return stamp if stamp.tzinfo is not None else None
    except (ValueError,OverflowError):
        return None


def _date_label(value):
    stamp=_timestamp(value)
    if stamp is None:
        return (value+" · fuso non indicato") if value else MISSING
    return stamp.astimezone(ROME).strftime("%d/%m/%Y %H:%M %Z")


def _impact(row):
    if not row["unavailable"]:
        return "Consulta dettaglio"
    try:
        n=float(row["unavailable"].replace(",","."))
    except ValueError:
        return "Consulta dettaglio"
    if not math.isfinite(n) or n<0 or not row["unit"]:
        return "Consulta dettaglio"
    return row["unavailable"]+" "+row["unit"]


def project_messages(messages):
    """One display row for every received record (no dedup or invented labels)."""
    rows=[]
    for i,message in enumerate(messages):
        found=_scalars(message)
        row={field:_pick(found,aliases) for field,aliases in FIELDS.items()}
        # 'id' is a generic alternative; prefer an actual message identifier
        # only if explicitly labelled; never use nested unrelated ids.
        explicit=_pick(found,FIELDS["message_id"][:-1])
        row["message_id"]=explicit or (str(message["id"]) if isinstance(message.get("id"),(str,int))
                                        and not isinstance(message["id"],bool) else None)
        row.update({"record_index":i,"published_label":_date_label(row["published"]),
                    "start_label":_date_label(row["start"]),"stop_label":_date_label(row["stop"]),
                    "impact":_impact(row)})
        rows.append(row)
    # Unknown timezone/date is not sorted as if it were a true instant.
    def sort_key(row):
        stamp=_timestamp(row["published"])
        return (stamp is not None,stamp or datetime.min.replace(tzinfo=timezone.utc))
    return sorted(rows,key=sort_key,reverse=True)


def options(rows, field):
    return sorted({r[field] for r in rows if r.get(field)},key=str.casefold)


def filter_messages(rows, *, query="", countries=(), statuses=(), types=()):
    needle=query.strip().casefold()
    return [r for r in rows if (not countries or r["country"] in countries)
            and (not statuses or r["status"] in statuses)
            and (not types or r["event_type"] in types)
            and (not needle or needle in " ".join(str(v or "") for k,v in r.items()
                if k in FIELDS).casefold())]


def display_row(row):
    return {label:row.get(key) or MISSING for key,label in TABLE_FIELDS.items()}


def _safe_csv(value):
    # External UMM text is untrusted; avoid spreadsheet formula execution.
    v=str(value)
    return "'"+v if v.lstrip().startswith(("=","+","-","@")) or v.startswith(("\t","\r","\n")) else v


def export_rows(rows, result):
    out=StringIO()
    credit=attribution("IIP")
    writer=csv.DictWriter(out,fieldnames=[*TABLE_FIELDS.values(),"Fonte","URL fonte","Acquisito UTC",
                                        "Periodo da","Periodo a","Copertura richiesta"])
    writer.writeheader()
    for row in rows:
        data={**display_row(row),"Fonte":credit["source"],"URL fonte":credit["source_url"],
              "Acquisito UTC":result["acquired"].isoformat(),"Periodo da":result.get("request_from",""),
              "Periodo a":result.get("request_to",""),"Copertura richiesta":coverage(result)}
        writer.writerow({k:_safe_csv(v) for k,v in data.items()})
    return out.getvalue()


def coverage(result):
    if result.get("partial") and result.get("pages") is not None:
        return "Parziale"
    if result.get("pagination_verified") and not result.get("partial"):
        return "Completa"
    return "Non verificata"
