"""Italian infrastructure identities, geography and observations are separate records."""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import json
import math

from .data import ROOT
from .entsog import _start

ASSETS = ROOT / "data" / "italian-network"
CATEGORIES = {"pipeline": "Gasdotti", "entry": "Ingressi e uscite", "lng": "Terminali GNL",
              "storage": "Stoccaggi", "compressor": "Compressione", "production": "Produzione",
              "power": "Centrali elettriche", "node": "Nodi"}
COLORS = {"pipeline": [91, 139, 181], "entry": [101, 223, 191], "lng": [131, 180, 255],
          "storage": [242, 190, 114], "compressor": [201, 170, 239], "production": [145, 202, 158],
          "power": [161, 175, 192], "node": [139, 157, 178]}


def valid_position(value):
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value)
            and 6.4 <= value[0] <= 19.0 and 35.3 <= value[1] <= 47.3)


def validate_geometry(geometry):
    if not isinstance(geometry, dict):
        raise ValueError("Geometria italiana WGS84 non valida")
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    if kind == "Point":
        good = valid_position(coords)
    elif kind == "LineString":
        good = isinstance(coords, list) and len(coords) >= 2 and all(map(valid_position, coords))
    elif kind == "MultiLineString":
        good = isinstance(coords, list) and bool(coords) and all(
            isinstance(line, list) and len(line) >= 2 and all(map(valid_position, line)) for line in coords)
    else:
        good = False
    if not good:
        raise ValueError("Geometria italiana WGS84 non valida")


@dataclass(frozen=True)
class Infrastructure:
    id: str
    name: str
    category: str
    operator: str | None
    regions: tuple[str, ...]
    status: str
    source_id: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Geography:
    infrastructure_id: str
    geometry: dict
    source: str
    source_url: str
    source_id: str
    retrieved_at: str
    observed_at: str
    geometry_accuracy: str
    license: str
    dataset_version: str
    quality_status: str


@dataclass(frozen=True)
class Binding:
    infrastructure_id: str
    provider: str
    external_id: str
    operator_id: str
    direction: str | None
    expected_label: str
    source_url: str
    retrieved_at: str
    mapping_confidence: str = "confirmed"
    source: str = ""
    license: str = ""
    dataset_version: str = ""

    @property
    def point_direction(self):
        return self.operator_id + self.external_id + (self.direction or "")


@dataclass(frozen=True)
class Observation:
    infrastructure_id: str
    point_direction: str
    indicator: str
    value: Decimal | None
    unit: str
    period_from: datetime
    period_to: datetime
    gas_day: date | None
    retrieved_at: datetime
    observed_at: str | None
    source: str
    source_url: str
    source_id: str
    quality_status: str
    publication_status: str
    revisions: tuple[dict, ...] = ()
    license: str = "ENTSOG TP conditions, art. 4 · attribution required"
    dataset_version: str = "API v1"
    mapping_confidence: str = "confirmed"
    source_period_from: str | None = None
    source_period_to: str | None = None
    source_unit: str = "kWh/d"


@dataclass(frozen=True)
class Network:
    infrastructure: tuple[Infrastructure, ...]
    geography: tuple[Geography, ...]
    bindings: tuple[Binding, ...]
    sources: dict

    def bindings_for(self, identifier, provider=None):
        return tuple(b for b in self.bindings if b.infrastructure_id == identifier and
                     (provider is None or b.provider == provider))


def load_network_assets(directory=ASSETS):
    features = json.loads((Path(directory) / "infrastructure.geojson").read_text())["features"]
    infrastructure, geography, ids = [], [], set()
    for feature in features:
        props = feature["properties"]
        identifier = feature["id"]
        if identifier in ids or props["country_code"] != "IT" or props["category"] not in CATEGORIES:
            raise ValueError("Identità o perimetro geografico non valido")
        ids.add(identifier)
        validate_geometry(feature["geometry"])
        infrastructure.append(Infrastructure(identifier, props["name"], props["category"], props.get("operator"),
            tuple(props.get("regions", [])), props["status"], props["source_id"], props.get("metadata", {})))
        geography.append(Geography(identifier, feature["geometry"], **{key: props[key] for key in (
            "source", "source_url", "source_id", "retrieved_at", "observed_at", "geometry_accuracy", "license", "dataset_version", "quality_status")}))
    payload = json.loads((Path(directory) / "catalog.json").read_text())
    bindings = tuple(Binding(**row) for row in payload["bindings"])
    keys = set()
    for binding in bindings:
        key = (binding.provider, binding.operator_id, binding.external_id, binding.direction)
        if (binding.infrastructure_id not in ids or key in keys or binding.mapping_confidence != "confirmed"
                or not binding.source or not binding.license or not binding.dataset_version):
            raise ValueError("Mapping non confermato, duplicato o privo di infrastruttura")
        keys.add(key)
        if binding.provider in ("AGSI+", "ALSI"):
            matches = [r for r in payload["sources"]["gie_facilities"] if r["provider"] == binding.provider
                       and r["eic"] == binding.external_id and r["company"] == binding.operator_id]
            if len(matches) != 1 or matches[0]["is_group"] or matches[0]["country"] != "IT":
                raise ValueError("Il mapping GIE deve identificare un singolo impianto italiano")
    return Network(tuple(infrastructure), tuple(geography), bindings, payload["sources"])


def filter_infrastructure(network, categories, *, operators=(), regions=(), statuses=(), event_ids=None):
    return tuple(item for item in network.infrastructure if item.category in categories
        and (not operators or item.operator in operators)
        and (not regions or set(item.regions) & set(regions))
        and (not statuses or item.status in statuses)
        and (event_ids is None or item.id in event_ids))


def selected_id(event, visible_ids):
    """Never trust a stale picked object after a filter changes."""
    selection = event.get("selection", {}) if isinstance(event, dict) else {}
    objects = selection.get("objects", {})
    if not isinstance(objects, dict):
        return None
    for items in objects.values():
        for item in items if isinstance(items, list) else []:
            identifier = item.get("infra_id") if isinstance(item, dict) else None
            if identifier is None and isinstance(item, dict):
                identifier = item.get("properties", {}).get("infra_id")
            if identifier in visible_ids:
                return identifier
    return None


def applicable_observations(observations, point_direction, day, indicator):
    """A capacity rate must cover the whole same gas day; no clock correction."""
    first, last = _start(day), _start(day + timedelta(days=1))
    if indicator in ("Firm Technical", "Firm Booked", "Firm Available") and any(
            o.point_direction == point_direction and o.indicator == indicator
            and o.period_from < last and o.period_to > first
            and (o.value is None or o.quality_status == "conflict") for o in observations):
        return ()
    candidates = [o for o in observations if o.point_direction == point_direction and o.indicator == indicator
                  and o.unit == "GWh/d"
                  and o.value is not None and o.quality_status not in ("conflict", "N/A", "unaligned")
                  and (o.gas_day == day if indicator not in ("Firm Technical", "Firm Booked", "Firm Available")
                       else o.period_from <= first and o.period_to >= last)]
    values = {o.value for o in candidates}
    return tuple(candidates) if len(values) == 1 else ()


def applicable(observations, point_direction, day, indicator):
    rows = applicable_observations(observations,point_direction,day,indicator)
    return rows[0].value if rows else None


def merge_observations(snapshots):
    """A newer successful response replaces its window, including new N/A or holes.

    A failed refresh has the original acquisition timestamp and never makes old
    records appear fresh. Revisions from one response stay in the observation.
    """
    records = []
    for snapshot in sorted(snapshots, key=lambda s: s.acquired):
        start, stop = _start(snapshot.first), _start(snapshot.last + timedelta(days=1))
        records = [o for o in records if not (o.point_direction == snapshot.point_direction
                   and o.period_from < stop and o.period_to > start)]
        records.extend(snapshot.records)
    return tuple(records)


def map_kpis(network, visible, observations, day):
    ids = {i.id for i in visible}
    points = [b for b in network.bindings if b.provider == "ENTSOG" and b.infrastructure_id in ids and b.direction == "entry"
              and b.external_id.startswith("ITP-")]
    values, comparable, evidence = [], [], {}
    def collect(point, indicator):
        rows = applicable_observations(observations,point.point_direction,day,indicator)
        for row in rows:
            evidence[(row.point_direction,row.indicator,row.period_from,row.period_to,row.source_id)] = row
        return rows[0].value if rows else None
    for point in points:
        flow = collect(point, "Physical Flow")
        capacity = applicable(observations, point.point_direction, day, "Firm Technical")
        if flow is not None:
            values.append(flow)
        if flow is not None and flow >= 0 and capacity is not None and capacity > 0:
            comparable.append((flow, capacity))
            collect(point,"Firm Technical")
    all_points = [b for b in network.bindings if b.provider == "ENTSOG" and b.infrastructure_id in ids]
    valid_ids = {b.infrastructure_id for b in all_points
                 if collect(b,"Physical Flow") is not None}
    return {"mapped": len(ids), "categories": {c: sum(i.category == c for i in visible) for c in CATEGORIES},
            "valid_points": len(valid_ids), "mapped_points": len({b.infrastructure_id for b in all_points}),
            "valid_entry_points": len(values), "mapped_entry_points": len(points),
            "entry_flow_gwh_d": sum(values) if values else None,
            "utilization_pct": 100 * sum(f for f, _ in comparable) / sum(c for _, c in comparable) if comparable else None,
            "comparable_points": len(comparable),"observations":tuple(evidence.values())}


def evidence_status(records, day, now, *, complete=False, failed=False, current_day=None):
    """Dates refer only to records actually supporting the displayed measures.

    A recent refresh of another indicator/day cannot freshen these records.
    Cache expiry follows the operational adapter's 12-hour TTL.
    """
    records = tuple(records)
    if not records:
        return {"status":"Non disponibile","oldest":None,"newest":None,"age":None,
                "published_oldest":None,"published_newest":None,"failed":failed,"complete":False}
    oldest=min(o.retrieved_at for o in records)
    newest=max(o.retrieved_at for o in records)
    publications=[]
    for row in records:
        if row.observed_at:
            try:
                stamp=datetime.fromisoformat(row.observed_at.replace("Z","+00:00"))
                if stamp.tzinfo is not None:publications.append(stamp.astimezone(timezone.utc))
            except (ValueError,AttributeError):pass
    historical=(current_day is not None and day<current_day) or now-oldest>timedelta(hours=12)
    confirmed=all(o.publication_status.casefold() in ("confirmed","final","definitive") for o in records)
    future = newest > now or (current_day is not None and day > current_day)
    status="Storico" if historical else "Aggiornato" if complete and confirmed and not failed and not future else "Parziale"
    return {"status":status,"oldest":oldest,"newest":newest,"age":max(timedelta(0),now-oldest),
            "published_oldest":min(publications) if publications else None,
            "published_newest":max(publications) if publications else None,"failed":failed,"complete":complete}


def kpi_status(metrics, snapshots, day, now, *, current_day, failures=()):
    records=metrics["observations"]
    points={o.point_direction for o in records}
    latest={}
    for snapshot in sorted(snapshots,key=lambda s:s.acquired):
        if snapshot.point_direction in points and snapshot.first<=day<=snapshot.last:
            latest[snapshot.point_direction]=snapshot
    complete=(metrics["valid_points"] == metrics["mapped_points"] and bool(points)
              and points<=set(latest) and not any(s.partial for s in latest.values()))
    failed = any(s.failed for s in latest.values()) or bool(points & set(failures))
    return evidence_status(records,day,now,complete=complete,failed=failed,current_day=current_day)


def point_metrics(observations, point, first, last):
    """Latest usable gas day in the chosen window, plus same-day capacity rates.

    Never use a newer nomination or an unrelated day to date the physical flow.
    The previous calendar day's flow is required for the daily change.
    """
    days = (last-timedelta(days=n) for n in range((last-first).days+1))
    day = next((d for d in days if applicable(observations,point,d,"Physical Flow") is not None),last)
    values, evidence = {}, []
    for indicator in ("Physical Flow","Firm Technical","Firm Available","Nomination","Renomination"):
        rows = applicable_observations(observations,point,day,indicator)
        if rows:
            values[indicator] = rows[0].value
            evidence.extend(rows)
    flow, capacity = values.get("Physical Flow"), values.get("Firm Technical")
    utilization = 100*flow/capacity if flow is not None and flow >= 0 and capacity is not None and capacity > 0 else None
    previous = applicable(observations,point,day-timedelta(days=1),"Physical Flow")
    change = flow-previous if flow is not None and previous is not None and day > first else None
    if change is not None:
        evidence.extend(applicable_observations(observations,point,day-timedelta(days=1),"Physical Flow"))
    return {"day":day,"values":values,"utilization_pct":utilization,"change_gwh_d":change,"observations":tuple(evidence)}
