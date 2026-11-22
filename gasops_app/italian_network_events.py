"""Exact asset matching only. A published zero interruption is not an outage."""
from datetime import timedelta
from decimal import Decimal
import json

from .entsog import SOURCE, _start
from .entsog_network import _amount, query_params
from .iip_view import project_messages, _timestamp
from .italian_network_sources import integer, timestamp
from .public_data import retrieve, SourceSchemaError
from .italian_network import verified_bindings

INTERRUPTIONS_URL = "https://transparency.entsog.eu/api/v1/interruptions"


def parse_interruptions(text, acquired, binding, first, last, *, cached=False, failed=False):
    payload = json.loads(text)
    rows, meta = payload.get("interruptions"), payload.get("meta", {})
    if not isinstance(rows, list) or len(rows) > 200 or integer(meta.get("offset", 0)) != 0:
        raise SourceSchemaError("Pagina interruzioni ENTSOG non valida")
    if integer(meta.get("count", len(rows))) != len(rows):
        raise SourceSchemaError("Conteggio interruzioni ENTSOG incoerente")
    total = integer(meta["total"]) if meta.get("total") is not None else None
    if total is not None and total < len(rows):
        raise SourceSchemaError("Totale interruzioni ENTSOG incoerente")
    records = {}
    for row in rows:
        identity = "".join(str(row.get(k, "")) for k in ("operatorKey", "pointKey", "directionKey"))
        if identity != binding.point_direction or str(row.get("unit", "")).lower() != "kwh/d":
            raise SourceSchemaError("Identità o unità interruzione ENTSOG inattesa")
        start, end = timestamp(row.get("periodFrom")), timestamp(row.get("periodTo"))
        if start >= end:
            raise SourceSchemaError("Intervallo interruzione ENTSOG non valido")
        value = _amount(row)
        if value is not None and value < 0:
            raise SourceSchemaError("Capacità interrotta ENTSOG negativa")
        if end <= _start(first) or start >= _start(last + timedelta(days=1)):
            continue
        published = timestamp(row["lastUpdateDateTime"]) if row.get("lastUpdateDateTime") else None
        identifier = str(row.get("id") or "")
        if not identifier:
            raise SourceSchemaError("Identificativo interruzione ENTSOG assente")
        event = {"infrastructure_id":binding.infrastructure_id, "point_direction":binding.point_direction,
                 "source":"ENTSOG TP Interruptions", "source_url":SOURCE, "source_id":identifier,
                 "period_from":start, "period_to":end, "observed_at":published, "retrieved_at":acquired,
                 "source_period_from":row["periodFrom"], "source_period_to":row["periodTo"], "source_unit":row["unit"],
                 "value":value / Decimal(1_000_000) if value is not None else None, "unit":"GWh/d",
                 "kind":str(row.get("interruptionType") or "Non indicato"),
                 "capacity_type":str(row.get("capacityType") or "Non indicato"),
                 "status":"Pubblicato", "quality_status":"valid" if value is not None else "N/A",
                 "mapping_confidence":"confirmed", "license":"ENTSOG TP conditions, art. 4"}
        prior = records.get(identifier)
        if prior and prior != event:
            # Resolve only explicitly ordered source revisions, otherwise withhold.
            if not published or not prior["observed_at"] or published == prior["observed_at"]:
                raise SourceSchemaError("Versioni interruzione ENTSOG in conflitto")
            if published < prior["observed_at"]:
                continue
        records[identifier] = event
    return {"records":tuple(records.values()), "acquired":acquired, "first":first, "last":last,
            "point_direction":binding.point_direction, "cached":cached, "failed":failed,
            "partial":len(rows) == 200 or total is None or total != len(rows)}


def load_interruptions(store, binding, first, last, *, refresh=False):
    query_params(binding.point_direction, first, last)
    def parse(text, when, **kwargs):
        return parse_interruptions(text, when, binding, first, last, **kwargs)
    return retrieve(store, key=f"italian-map-interruptions-v1:{binding.point_direction}:{first}:{last}",
        name="Interruzioni ENTSOG", url=INTERRUPTIONS_URL,
        params={"operatorKey":binding.operator_id, "pointKey":binding.external_id,
                "directionKey":binding.direction, "from":first.isoformat(),
                "to":(last+timedelta(days=1)).isoformat(), "limit":200, "timeZone":"CET"},
        parse=parse, ttl=timedelta(hours=12), attempts=1, timeout=(5,20),
        refresh=refresh, diagnostics=True, max_bytes=2_000_000)


def iip_events(network, result, first, last):
    """Do not match by name, company EIC, text, or a virtual storage group."""
    if not result:
        return (), 0
    mapping = {}
    for b in network.bindings:
        if b.provider in ("AGSI+", "ALSI") and b.mapping_confidence == "confirmed":
            mapping.setdefault(b.external_id, set()).add(b.infrastructure_id)
    for point in network.sources["points"]:
        for b in verified_bindings(network):
            if b.external_id == point["pointKey"] and point.get("pointEicCode"):
                mapping.setdefault(point["pointEicCode"], set()).add(b.infrastructure_id)
    projected = project_messages(result["messages"])
    # Multiple versions require an unambiguous publication order. Withhold ties.
    grouped, events, unresolved = {}, [], 0
    for row in projected:
        if not row["message_id"]:
            unresolved += 1
            continue
        grouped.setdefault(row["message_id"], []).append(row)
    for rows in grouped.values():
        stamps = [_timestamp(r["published"]) for r in rows]
        if len(rows) > 1 and (any(t is None for t in stamps) or stamps.count(max(stamps)) > 1):
            unresolved += 1
            continue
        row = rows[stamps.index(max(stamps))] if len(rows) > 1 else rows[0]
        # Unknown statuses do not establish an active event.
        status = str(row["status"] or "").casefold()
        if status in ("cancelled", "canceled", "inactive", "revoked"):
            continue
        if status not in ("active", "attivo", "confirmed", "confirmed event"):
            unresolved += 1
            continue
        matches = mapping.get(str(row["asset_code"] or "").upper(), set())
        start, end = _timestamp(row["start"]), _timestamp(row["stop"])
        if len(matches) != 1 or not start or not end or start >= end or row["country"] not in (None, "IT", "Italy", "Italia"):
            unresolved += 1
            continue
        if end <= _start(first) or start >= _start(last+timedelta(days=1)):
            continue
        events.append({"infrastructure_id":next(iter(matches)), "point_direction":None,
            "source":"GIE IIP", "source_url":result["source_url"], "source_id":row["message_id"],
            "period_from":start, "period_to":end, "observed_at":_timestamp(row["published"]),
            "source_period_from":row["start"], "source_period_to":row["stop"], "source_unit":row["unit"],
            "retrieved_at":result["acquired"], "value":None, "unit":None,
            "impact_label":row["impact"], "kind":row["event_type"] or row["kind"] or "Avviso",
            "status":row["status"], "quality_status":"published_message", "mapping_confidence":"confirmed",
            "license":"GIE attribution required"})
    return tuple(events), unresolved


def relevant_events(records, first, last):
    return tuple(r for r in records if r["period_from"] < _start(last+timedelta(days=1))
                 and r["period_to"] > _start(first)
                 and (r["source"] == "GIE IIP" or r["value"] is not None and r["value"] > 0))


def verified_events(network, records, first, last, now):
    """Deduplicate releases and withhold unknown locations or tied conflicts."""
    ids = {i.id for i in network.infrastructure}
    bindings = {b.point_direction:b.infrastructure_id for b in verified_bindings(network)}
    iip_ids = set(bindings.values())|{b.infrastructure_id for b in network.bindings
        if b.provider in ("AGSI+","ALSI") and b.mapping_confidence == "confirmed"}
    grouped, unresolved = {}, 0
    for event in relevant_events(records,first,last):
        at, retrieved = _timestamp(event.get("observed_at")), _timestamp(event.get("retrieved_at"))
        point = event.get("point_direction")
        if (event.get("mapping_confidence") != "confirmed" or event.get("infrastructure_id") not in ids
                or point is not None and bindings.get(point) != event["infrastructure_id"]
                or point is None and (event.get("source") != "GIE IIP" or event["infrastructure_id"] not in iip_ids)
                or not retrieved or retrieved > now or at and at > now):
            unresolved += 1
            continue
        key = (event["source"],event["source_id"],event["infrastructure_id"],point)
        grouped.setdefault(key,[]).append(event)
    events = []
    for rows in grouped.values():
        latest = max((_timestamp(r.get("observed_at")) for r in rows if _timestamp(r.get("observed_at"))),default=None)
        versions = [r for r in rows if _timestamp(r.get("observed_at")) == latest]
        if len({(r.get("value"),r["period_from"],r["period_to"],r.get("status")) for r in versions}) == 1:
            events.append(max(versions,key=lambda r:r["retrieved_at"]))
        else:
            unresolved += 1
    return tuple(events), unresolved
