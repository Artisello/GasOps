"""Bounded public-source adapters for the map, reusing the existing HTTP/cache rules."""
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import re

from .entsog import URL, SOURCE, _start, _last_completed, gas_timestamp
from .entsog_network import INDICATORS, _amount, query_params
from .italian_network import Observation
from .models import utc_now
from .operational_sources import parse_agsi, parse_alsi, AGSI_URL, ALSI_SOURCE
from .public_data import retrieve, SourceSchemaError, SourceUnavailable

CAPACITIES = {"Firm Technical", "Firm Booked", "Firm Available"}
CATALOG_URL = "https://transparency.entsog.eu/api/v1/operatorpointdirections"


def integer(value):
    if isinstance(value, bool) or not re.fullmatch(r"\d{1,9}", str(value)):
        raise SourceSchemaError("Metadati di paginazione non validi")
    return int(value)


def timestamp(value):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError()
        return stamp.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise SourceSchemaError("Timestamp con offset richiesto") from None


def parse_catalog(text, acquired, *, cached=False, failed=False):
    payload = json.loads(text)
    rows = payload.get("operatorPointDirections", payload.get("operatorpointdirections"))
    if not isinstance(rows, list) or len(rows) > 500:
        raise SourceSchemaError("Catalogo ENTSOG non riconosciuto")
    meta = payload.get("meta", {})
    if integer(meta.get("count", len(rows))) != len(rows) or integer(meta.get("offset", 0)) != 0:
        raise SourceSchemaError("Conteggio catalogo ENTSOG incoerente")
    if len(rows) == 500 or integer(meta.get("total", len(rows))) != len(rows):
        raise SourceSchemaError("Catalogo ENTSOG parziale: associazioni non aggiornate")
    indexed = {}
    conflicts = set()
    fields = ("operatorKey", "pointKey", "directionKey", "pointLabel", "operatorLabel", "tSOCountry",
              "hasData", "isInvalid", "validFrom", "validTo", "pointType", "tsoEicCode")
    for row in rows:
        if not isinstance(row, dict) or row.get("tSOCountry") != "IT" or not str(row.get("operatorKey", "")).startswith("IT-TSO-"):
            raise SourceSchemaError("Catalogo estraneo al perimetro italiano")
        key = "".join(str(row.get(k, "")) for k in ("operatorKey", "pointKey", "directionKey"))
        item = {k: row.get(k) for k in fields}
        if key in indexed and indexed[key] != item:
            conflicts.add(key)
        indexed[key] = item
    return {"rows": [v for k, v in sorted(indexed.items()) if k not in conflicts],
            "conflicts": sorted(conflicts), "acquired": acquired, "cached": cached, "failed": failed}


def load_catalog(store, *, refresh=False):
    return retrieve(store, key="italian-map-opd-v1", name="Catalogo punti ENTSOG Italia", url=CATALOG_URL,
        params={"operatorKey": "IT-TSO-0001", "limit": 500}, parse=parse_catalog,
        ttl=timedelta(days=7), attempts=1, timeout=(5, 20), refresh=refresh, diagnostics=True, max_bytes=2_000_000)


@dataclass(frozen=True)
class Snapshot:
    point_direction: str
    records: tuple[Observation, ...]
    first: date
    last: date
    acquired: datetime
    cached: bool = False
    failed: bool = False
    partial: bool = False
    warnings: tuple[str, ...] = ()


def parse_observations(items, binding, first, last, acquired):
    """Keep source intervals, including capacity clocks that differ from gas days."""
    grouped = {}
    for item in items:
        identity = "".join(str(item.get(k, "")) for k in ("operatorKey", "pointKey", "directionKey"))
        if identity != binding.point_direction or item.get("indicator") not in INDICATORS:
            raise SourceSchemaError("Identità punto o indicatore inatteso")
        if str(item.get("unit", "")).lower() != "kwh/d" or str(item.get("periodType", "")).lower() != "day":
            raise SourceSchemaError("Unità o granularità ENTSOG inattesa")
        start, end = timestamp(item.get("periodFrom")), timestamp(item.get("periodTo"))
        if start >= end:
            raise SourceSchemaError("Intervallo temporale ENTSOG non valido")
        if end <= _start(first) or start >= _start(last + timedelta(days=1)):
            continue
        amount = _amount(item)
        day = None
        try:
            day, _, _ = gas_timestamp(item["periodFrom"])
            end_day, _, _ = gas_timestamp(item["periodTo"])
            if end_day != day + timedelta(days=1):
                day = None
        except SourceSchemaError:
            pass
        quality = "valid" if day is not None else "capacity_interval" if item["indicator"] in CAPACITIES else "unaligned"
        if amount is None:
            quality = "N/A"
        revision = item.get("lastUpdateDateTime", item.get("lastUpdateDate"))
        if revision:
            timestamp(revision)
        row = {"value": str(amount / Decimal(1_000_000)) if amount is not None else None,
               "observed_at": revision, "publication_status": str(item.get("flowStatus") or "Non indicato")[:80],
               "source_id": str(item.get("id") or binding.point_direction)[:400], "quality_status":quality,
               "source_period_from":item["periodFrom"], "source_period_to":item["periodTo"]}
        key = (item["indicator"], start, end, day)
        if row not in grouped.setdefault(key, []):
            grouped[key].append(row)
    observations = []
    for (indicator, start, end, day), revisions in sorted(grouped.items(), key=lambda p: (p[0][1], p[0][0])):
        # A missing publication timestamp cannot resolve conflicting versions.
        stamped = all(row["observed_at"] for row in revisions)
        latest_at = max(timestamp(row["observed_at"]) for row in revisions) if stamped else None
        latest = [row for row in revisions if timestamp(row["observed_at"]) == latest_at] if stamped else revisions
        values = {row["value"] for row in latest}
        value = next(iter(values)) if len(values) == 1 else None
        row = latest[-1]
        quality = "conflict" if len(values) > 1 else row["quality_status"]
        observations.append(Observation(binding.infrastructure_id, binding.point_direction, indicator,
            Decimal(value) if value is not None else None, "GWh/d", start, end, day, acquired,
            row["observed_at"], "ENTSOG TP Transport Data", SOURCE, row["source_id"], quality,
            row["publication_status"], tuple(revisions), source_period_from=row["source_period_from"],
            source_period_to=row["source_period_to"]))
    return tuple(observations)


def coalesce_records(records):
    """Resolve duplicate revisions even when ENTSOG splits them across pages."""
    groups = {}
    for record in records:
        key = (record.point_direction, record.indicator, record.period_from, record.period_to)
        groups.setdefault(key, []).append(record)
    combined = []
    for rows in groups.values():
        revisions = []
        for row in rows:
            for revision in row.revisions:
                if revision not in revisions:
                    revisions.append(revision)
        stamped = all(r["observed_at"] for r in revisions)
        newest = max(timestamp(r["observed_at"]) for r in revisions) if stamped else None
        latest = [r for r in revisions if timestamp(r["observed_at"]) == newest] if stamped else revisions
        values = {r["value"] for r in latest}
        revision = latest[-1]
        value = next(iter(values)) if len(values) == 1 else None
        combined.append(replace(rows[-1], value=Decimal(value) if value is not None else None,
            quality_status="conflict" if len(values) > 1 else revision["quality_status"],
            observed_at=revision["observed_at"], source_id=revision["source_id"],
            publication_status=revision["publication_status"], revisions=tuple(revisions),
            source_period_from=revision["source_period_from"], source_period_to=revision["source_period_to"],
            retrieved_at=max(r.retrieved_at for r in rows)))
    return tuple(combined)


def parse_point_page(text, binding, first, last, acquired, *, offset=0, cached=False, failed=False):
    """The HTTP loader and the offline explorer validate the same cache page."""
    payload = json.loads(text)
    items = payload.get("operationalData",payload.get("operationaldatas"))
    meta = payload.get("meta",{})
    if not isinstance(items,list) or len(items)>200 or integer(meta.get("offset",offset))!=offset:
        raise SourceSchemaError("Pagina operativa ENTSOG non valida")
    if integer(meta.get("count",len(items)))!=len(items):
        raise SourceSchemaError("Conteggio pagina ENTSOG incoerente")
    total = integer(meta["total"]) if meta.get("total") is not None else None
    if total is not None and total<offset+len(items):
        raise SourceSchemaError("Totale ENTSOG incoerente")
    if not items and offset==0:
        raise SourceSchemaError("Nessuna pubblicazione restituita")
    return {"records":parse_observations(items,binding,first,last,acquired),"count":len(items),
            "total":total,"acquired":acquired,"cached":cached,"failed":failed}


def load_point(store, binding, first, last, *, refresh=False, now=None):
    now = now or utc_now()
    params = query_params(binding.point_direction, first, last)
    if last > _last_completed(now):
        raise SourceSchemaError("Seleziona solo giorni gas conclusi")
    records, warnings, times = [], [], []
    cached = failed = partial = False
    for page in range(3):
        offset = page * 200
        def parse(text, when, *, cached=False, failed=False):
            return parse_point_page(text,binding,first,last,when,offset=offset,cached=cached,failed=failed)
        try:
            result = retrieve(store, key=f"italian-map-ops-v1:{binding.point_direction}:{first}:{last}:{offset}",
                name="ENTSOG · infrastruttura selezionata", url=URL, parse=parse,
                params={**params, "offset": offset, "limit": 200}, ttl=timedelta(hours=12),
                attempts=1, timeout=(5, 20), refresh=refresh, diagnostics=True, max_bytes=2_000_000)
        except SourceUnavailable:
            if not records:
                raise
            partial = True
            warnings.append("Pagina successiva non disponibile")
            break
        records.extend(result["records"])
        times.append(result["acquired"])
        cached |= result["cached"]
        failed |= result["failed"]
        if result["count"] < 200:
            partial |= result["total"] is None or result["total"] != offset + result["count"]
            break
    else:
        partial = True
        warnings.append("Limite di tre pagine raggiunto")
    records = coalesce_records(records)
    if not records:
        raise SourceUnavailable("Nessuna osservazione ENTSOG nel periodo richiesto.")
    if any(o.quality_status in ("unaligned", "conflict") for o in records):
        partial = True
    if any(o.indicator in CAPACITIES and o.gas_day is None for o in records):
        warnings.append("Le capacità mantengono gli intervalli originali della fonte")
    return Snapshot(binding.point_direction, tuple(records), first, last, min(times), cached, failed, partial, tuple(warnings))


def load_facility(store, api_key, binding, first, last, *, refresh=False):
    """Only explicit single-facility EIC pairs; never transform a VGS into a site."""
    if binding.provider not in ("AGSI+", "ALSI") or not api_key:
        raise ValueError("Fonte o accesso GIE non disponibile")
    if not re.fullmatch(r"[A-Z0-9-]{16}", binding.external_id) or not re.fullmatch(r"[A-Z0-9-]{16}", binding.operator_id):
        raise ValueError("Codici EIC non validi")
    if not 0 <= (last - first).days <= 89:
        raise ValueError("Periodo GIE non valido")
    parser = parse_agsi if binding.provider == "AGSI+" else parse_alsi
    def parse(text, when, **kwargs):
        result = parser(text, when, scope=binding.external_id, **kwargs)
        if not result["frame"].gas_day.between(first, last).all():
            raise SourceSchemaError("Periodo GIE estraneo alla richiesta")
        return {**result, "company_eic": binding.operator_id, "facility_eic": binding.external_id}
    return retrieve(store, key=f"italian-map-gie-v1:{binding.provider}:{binding.operator_id}:{binding.external_id}:{first}:{last}",
        name="GIE · singolo impianto", url=AGSI_URL if binding.provider == "AGSI+" else ALSI_SOURCE + "api",
        params={"country":"IT", "company":binding.operator_id, "facility":binding.external_id,
                "from":first.isoformat(), "to":last.isoformat(), "size":100, "page":1},
        parse=parse, ttl=timedelta(hours=24), refresh=refresh, attempts=1, timeout=(5,20), diagnostics=True,
        headers={"x-key":api_key.strip(), "Accept":"application/json"})


def encode_snapshot(snapshot):
    def default(value):
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        raise TypeError("Unsupported snapshot value")
    return json.dumps(asdict(snapshot), default=default, ensure_ascii=False)


def decode_snapshot(payload):
    p = json.loads(payload) if isinstance(payload, str) else payload
    records = []
    for item in p["records"]:
        records.append(Observation(**{**item, "value":Decimal(item["value"]) if item["value"] is not None else None,
            "period_from":timestamp(item["period_from"]), "period_to":timestamp(item["period_to"]),
            "gas_day":date.fromisoformat(item["gas_day"]) if item["gas_day"] else None,
            "retrieved_at":timestamp(item["retrieved_at"]), "revisions":tuple(item.get("revisions", []))}))
    return Snapshot(**{**p, "records":tuple(records), "first":date.fromisoformat(p["first"]),
        "last":date.fromisoformat(p["last"]), "acquired":timestamp(p["acquired"]), "warnings":tuple(p.get("warnings", []))})
