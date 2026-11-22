"""Read-only system status from existing, dated evidence. No provider or store I/O.

Coverage counts observable components, never a share of the physical balance.
Sectoral withdrawals, border flows, LNG and storage remain distinct perimeters.
"""
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from statistics import median

import pandas as pd
import json

from .gas_calendar import closed_gas_day, gas_day_bounds
from .italian_network import applicable_observations, evidence_status, map_kpis, merge_observations, point_metrics
from .italian_network_events import iip_events, relevant_events
from .models import Agent, Kind, Run
from .source_health import session_health, stamp

BALANCE = (
    ("imports", "Importazioni", "supply"), ("lng", "Send-out GNL", "supply"),
    ("withdrawal", "Erogazione stoccaggi", "supply"), ("production", "Produzione nazionale", "supply"),
    ("conventional", "Domanda convenzionale", "outflow"), ("power", "Domanda termoelettrica", "outflow"),
    ("exports", "Esportazioni", "outflow"), ("injection", "Iniezione stoccaggi", "outflow"),
    ("linepack", "Δ linepack fisico", "outflow"),
)
ENTSOG = "https://transparency.entsog.eu/"


@dataclass(frozen=True)
class StatusPolicy:
    capacity_pct: float = 90
    deviation_pct: float = 30
    baseline_days: int = 28
    baseline_min_days: int = 14
    network_ttl_hours: float = 12
    inventory_ttl_hours: float = 24
    event_ttl_hours: float = 2

    def __post_init__(self):
        if not (0 < self.capacity_pct <= 200 and 0 < self.deviation_pct <= 1000
                and 3 <= self.baseline_min_days <= self.baseline_days <= 90
                and 0 < self.network_ttl_hours <= 168 and 0 < self.inventory_ttl_hours <= 168
                and 0 < self.event_ttl_hours <= 168):
            raise ValueError("Soglie diagnostiche non valide")


@dataclass(frozen=True)
class Coverage:
    valid: int = 0
    expected: int = 0


@dataclass(frozen=True)
class Measure:
    value: Decimal | None
    unit: str
    gas_day: date
    source_id: str
    source: str
    observed_at: datetime | None = None
    retrieved_at: datetime | None = None
    status: str = "unavailable"
    freshness: str = "unavailable"
    coverage: Coverage = field(default_factory=Coverage)
    scope: str = ""
    warnings: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class BalanceComponent:
    id: str
    label: str
    side: str
    measure: Measure


@dataclass(frozen=True)
class Attention:
    id: str
    category: str
    severity: str
    description: str
    rule: str
    threshold: Decimal | None
    observed_value: Decimal | None
    unit: str
    source_id: str
    observed_at: datetime | None
    retrieved_at: datetime | None
    infrastructure_id: str | None = None
    direction: str | None = None
    evidence_ids: tuple[str, ...] = ()
    baseline: Decimal | None = None
    baseline_n: int = 0


@dataclass(frozen=True)
class OverviewStatus:
    gas_day: date
    gas_day_status: str
    active_gas_day: date
    last_completed_gas_day: date
    latest_observed_gas_day: date | None
    observed_at: datetime | None
    retrieved_at: datetime | None
    source_id: tuple[str, ...]
    source_status: str
    source_coverage: Coverage
    entry_flow_observed: Measure
    storage_level: Measure
    lng_sendout: Measure
    demand_actual: Measure
    demand_forecast: Measure
    active_events: tuple[dict, ...]
    quality_flags: tuple[str, ...]
    components: tuple[BalanceComponent, ...]
    attention: tuple[Attention, ...]
    source_health: tuple[dict, ...]
    event_coverage: Coverage
    hours: int
    reconcilable: bool = False
    balance_message: str = "Bilancio non riconciliabile con i dati disponibili"


def _stamp(value):
    try:
        return stamp(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _number(value):
    try:
        result = Decimal(str(value))
        return result if not isinstance(value, bool) and result.is_finite() and result >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _missing(day, source_id, source, warning, *, unit="GWh/d", expected=1, scope=""):
    return Measure(None, unit, day, source_id, source, coverage=Coverage(0, expected),
                   scope=scope, warnings=(warning,))


def _network_measure(bindings, observations, snapshots, day, now, policy, code, label, *, network=None):
    records, values = [], []
    for binding in bindings:
        rows = applicable_observations(observations, binding.point_direction, day, "Physical Flow")
        if rows:
            values.append(rows[0].value)
            records.extend(rows)
    if not records:
        return _missing(day, code, label, "Nessun flusso valido nella copia disponibile", expected=len(bindings))
    points = {r.point_direction for r in records}
    latest = {}
    for s in snapshots:
        if s.point_direction in points and s.first <= day <= s.last:
            latest[s.point_direction] = s
    confirmed = all(r.publication_status.casefold() in ("confirmed", "final", "definitive") for r in records)
    estimated = any(r.publication_status.casefold() == "estimated" for r in records)
    missing_points = len(values) < len(bindings)
    partial_response = any(s.partial for s in latest.values())
    partial = missing_points or partial_response or not confirmed
    failed = any(s.failed for s in latest.values())
    dates = evidence_status(records, day, now, complete=not partial, current_day=closed_gas_day(now))
    stale = failed or now-dates["oldest"] > timedelta(hours=policy.network_ttl_hours)
    warnings = tuple(t for t, active in (("Copertura parziale dei punti mappati", missing_points),
        ("Risposta della fonte parziale", partial_response),
        ("Ultima copia valida · da aggiornare", stale), ("Aggiornamento non riuscito", failed),
        ("Pubblicazione provvisoria o stato non confermato", not confirmed)) if active)
    published = [_stamp(r.observed_at) for r in records]
    # Border imports use the existing map KPI; other directions/categories are
    # new balance components. Only physical-flow records date this measure.
    if network is not None:
        ids = {b.infrastructure_id for b in bindings}
        visible = tuple(i for i in network.infrastructure if i.id in ids)
        value = map_kpis(network, visible, observations, day)["entry_flow_gwh_d"]
    else:
        value = sum(values)
    return Measure(value, "GWh/d", day, code, label,
        min(published) if all(published) else None, dates["oldest"],
        "estimated" if estimated else "historical" if day < closed_gas_day(now) else "observed",
        "stale" if stale else "partial" if partial else "fresh", Coverage(len(values), len(bindings)),
        "Punti italiani mappati · perimetro parziale", warnings, tuple(sorted({r.source_id for r in records})))


def _inventory(state, platform, column, day, now, policy, *, unit="GWh/d", previous=False):
    code, label = "GIE:"+platform+":IT", "GIE "+platform
    saved = state.get(platform+"_IT", {})
    result = saved.get("result")
    absent = _missing(day, code, label, "Aggregato Italia non disponibile per il giorno gas", unit=unit, scope="Italia")
    if not result or result.get("scope") != "IT":
        return absent
    frame, acquired = result.get("frame"), _stamp(result.get("acquired"))
    if not isinstance(frame, pd.DataFrame) or column not in frame or "gas_day" not in frame:
        return absent
    if acquired is None or acquired > now:
        return absent
    dates = frame.gas_day.map(_day)
    target = max((d for d in dates if d is not None and d <= day), default=None) if previous else day
    matches = frame.loc[dates == target] if target is not None else frame.iloc[:0]
    if matches.empty:
        return absent
    candidates = {(_number(r.get(column)), str(r.get("status", "non indicato"))) for _, r in matches.iterrows()}
    if len(candidates) != 1:
        return _missing(day, code, label, "Pubblicazioni giornaliere in conflitto", unit=unit, scope="Italia")
    value, status = next(iter(candidates))
    if value is None or status == "N":
        return absent
    if unit == "GWh/d" and target > closed_gas_day(now) and status != "E":
        return absent
    stale = bool(result.get("failed") or saved.get("error") or now-acquired > timedelta(hours=policy.inventory_ttl_hours))
    warnings = tuple(t for t, active in (("Ultima copia valida · da aggiornare", stale),
        ("Giorno diverso dal bilancio selezionato", target != day),
        ("Valore da verificare", "review" in matches and matches.review.any())) if active)
    return Measure(value, unit, target, code, label, None, acquired,
        "estimated" if status == "E" else "historical" if target < closed_gas_day(now) else "observed",
        "stale" if stale else "partial" if target > closed_gas_day(now) else "fresh", Coverage(1, 1), "Italia · aggregato GIE", warnings)


def _demand(state, day, now, inspections, policy):
    from .live_sources import BUNDLES, validated_inspection
    bundle = state.get(BUNDLES, {}).get("daily")
    source_id, label = "ENTSOG:SRG:sectors", "ENTSOG · prelievi SRG"
    missing = lambda: _missing(day, source_id, label, "Prelievi settoriali SRG non disponibili", scope="SRG · tre aggregati")
    if (day > closed_gas_day(now) or bundle is None or bundle.origin.url != ENTSOG or bundle.origin.archive
            or bundle.origin.kind not in (Kind.LIVE, Kind.HISTORICAL) or bundle.origin.retrieved_at > now):
        return (missing(), missing(), missing()), None
    try:
        checked = validated_inspection(bundle, now, "daily", inspections=inspections)
    except (ValueError, TypeError, KeyError):
        return (missing(), missing(), missing()), None
    frame, source = checked.usable, bundle.origin
    def measure(fields):
        if pd.Timestamp(day) not in frame.index or not set(fields) <= set(source.fields):
            return missing()
        values = [_number(frame.loc[pd.Timestamp(day), f]) for f in fields]
        if any(v is None for v in values):
            return missing()
        return Measure(sum(values), "GWh/d", day, source_id, label, source.published_at, source.retrieved_at,
            "historical" if day < closed_gas_day(now) else "observed",
            "stale" if source.refresh_failed or now-source.retrieved_at > timedelta(hours=policy.network_ttl_hours) else "fresh",
            Coverage(len(fields), len(fields)), "SRG · aggregati settoriali",
            ("Perimetro SRG, non domanda nazionale certificata",), (bundle.fingerprint,))
    conventional = measure(("distribution_gwh", "industry_gwh"))
    power = measure(("power_gwh",))
    total = measure(("distribution_gwh", "industry_gwh", "power_gwh"))
    return (total, conventional, power), frame


def _forecast(state, day, now, policy):
    absent = _missing(day, "IGOR:forecast:SRG", "I.G.O.R. · previsione", "Nessuna previsione compatibile già calcolata")
    run = state.get("last_briefing") or state.get("last_run")
    if (not isinstance(run, Run) or run.source.archive or run.source.kind not in (Kind.LIVE, Kind.HISTORICAL)
            or run.source.url != ENTSOG or run.source.grain != "daily"
            or run.source.retrieved_at > now or run.started_at > now or run.finished_at and run.finished_at > now):
        return absent
    train_end = _day(run.source.latest_period)
    if train_end is None or train_end >= day:
        return absent
    result = run.results.get(Agent.FORECAST)
    if result is None:
        return absent
    points = result.values.get("forecast", {}).get("points", ())
    values = {_number(p.get("estimate")) for p in points if p.get("period") == day.isoformat()}
    if len(values) != 1 or None in values:
        return absent
    return Measure(next(iter(values)), "GWh/d", day, absent.source_id, absent.source,
        run.finished_at or run.started_at, run.source.retrieved_at, "estimated",
        "stale" if run.source.refresh_failed or now-run.source.retrieved_at > timedelta(hours=policy.network_ttl_hours) else "partial", Coverage(1, 1),
        "Prelievi SRG · stima I.G.O.R.", ("Stima da un bollettino già calcolato; perimetro SRG",), (run.id,))


def _event_records(network, state, interruptions, day, now):
    saved = state.get("italian_network_data_v1", {})
    copies = {s["point_direction"]: s for s in interruptions}
    copies.update(saved.get("interruptions", {}))
    iip_result = state.get("gie_iip", {}).get("result")
    if iip_result:
        unique = {json.dumps(m, sort_keys=True, default=str):m for m in iip_result["messages"]}
        iip_result = {**iip_result, "messages":list(unique.values())}
    iip, unresolved = iip_events(network, iip_result, day, day)
    candidates = relevant_events((*iip, *(r for s in copies.values() for r in s["records"])), day, day)
    ids = {i.id for i in network.infrastructure}
    grouped = {}
    for event in candidates:
        at, retrieved = _stamp(event.get("observed_at")), _stamp(event.get("retrieved_at"))
        if (event.get("mapping_confidence") != "confirmed" or event.get("infrastructure_id") not in ids
                or not retrieved or retrieved > now or at and at > now):
            continue
        key = (event["source"], event["source_id"], event["infrastructure_id"], event.get("point_direction"))
        grouped.setdefault(key, []).append(event)
    events = []
    for rows in grouped.values():
        latest = max((_stamp(r.get("observed_at")) for r in rows if _stamp(r.get("observed_at"))), default=None)
        versions = [r for r in rows if _stamp(r.get("observed_at")) == latest]
        # A tied, contradictory release is not an established event.
        if len({(r.get("value"), r["period_from"], r["period_to"], r.get("status")) for r in versions}) == 1:
            events.append(max(versions, key=lambda r: r["retrieved_at"]))
        else:
            unresolved += 1
    queried = {s["point_direction"] for s in copies.values() if s["first"] <= day <= s["last"]
               and _stamp(s.get("acquired")) and s["acquired"] <= now}
    expected = {b.point_direction for b in network.bindings if b.provider == "ENTSOG"}
    return tuple(events), Coverage(len(queried & expected), len(expected)), unresolved


def build_status(network, snapshots, state, now, *, gas_day=None, interruptions=(), policy=None):
    """Normalize only evidence in memory; preserve missing values and timestamps."""
    if _stamp(now) is None:
        raise ValueError("Timestamp con fuso richiesto")
    policy = policy or StatusPolicy()
    closed = closed_gas_day(now)
    active = closed+timedelta(days=1)
    snapshots = tuple(sorted((s for s in snapshots if s.acquired <= now), key=lambda s: s.acquired))
    identities = {(b.infrastructure_id, b.point_direction) for b in network.bindings if b.provider == "ENTSOG"}
    observations = tuple(o for o in merge_observations(snapshots)
        if (o.infrastructure_id, o.point_direction) in identities and o.mapping_confidence == "confirmed" and o.retrieved_at <= now
        and (o.indicator != "Physical Flow" or o.period_to <= now)
        and (_stamp(o.observed_at) is None or _stamp(o.observed_at) <= now)
        and (o.value is None or _number(o.value) is not None)
        and (o.gas_day is None or gas_day_bounds(o.gas_day) == (o.period_from, o.period_to)))
    days = {o.gas_day for o in observations if o.indicator == "Physical Flow" and o.unit == "GWh/d" and o.gas_day is not None
            and o.gas_day <= closed and o.value is not None and o.quality_status not in ("conflict", "N/A", "unaligned")}
    inspections = {}
    (_, _, _), demand_frame = _demand(state, closed, now, inspections, policy)
    if demand_frame is not None:
        days.update(t.date() for t in demand_frame.index if t.date() <= closed and pd.notna(demand_frame.loc[t, "demand_gwh"]))
    for platform, column, unit in (("AGSI+", "stock_twh", "TWh"), ("ALSI", "sendout_gwh_d", "GWh/d")):
        result = state.get(platform+"_IT", {}).get("result")
        if result and isinstance(result.get("frame"), pd.DataFrame) and "gas_day" in result["frame"]:
            candidates = sorted({d for d in result["frame"].gas_day.map(_day) if d is not None and d <= closed}, reverse=True)
            for candidate in candidates:
                if _inventory(state, platform, column, candidate, now, policy, unit=unit).value is not None:
                    days.add(candidate)
                    break
    latest_day = max(days, default=None)
    day = gas_day if gas_day is not None else latest_day or closed
    if not isinstance(day, date) or isinstance(day, datetime) or day > active:
        raise ValueError("Giorno gas futuro o non valido")
    categories = {i.id:i.category for i in network.infrastructure}
    group = lambda category, direction: tuple(b for b in network.bindings if b.provider == "ENTSOG"
        and b.mapping_confidence == "confirmed" and b.direction == direction
        and categories.get(b.infrastructure_id) == category
        and (category != "entry" or b.external_id.startswith("ITP-")))
    imports = _network_measure(group("entry", "entry"), observations, snapshots, day, now, policy,
        "ENTSOG:border-entry", "ENTSOG · frontiere", network=network)
    lng = _inventory(state, "ALSI", "sendout_gwh_d", day, now, policy)
    if lng.value is None:
        lng = _network_measure(group("lng", "entry"), observations, snapshots, day, now, policy, "ENTSOG:LNG-entry", "ENTSOG · terminali GNL")
    exports = _network_measure(group("entry", "exit"), observations, snapshots, day, now, policy, "ENTSOG:border-exit", "ENTSOG · frontiere in uscita")
    storage = _inventory(state, "AGSI+", "stock_twh", day, now, policy, unit="TWh", previous=True)
    withdrawal = _inventory(state, "AGSI+", "withdrawal_gwh_d", day, now, policy)
    injection = _inventory(state, "AGSI+", "injection_gwh_d", day, now, policy)
    (demand, conventional, power), _ = _demand(state, day, now, inspections, policy)
    forecast = _forecast(state, day, now, policy)
    measures = {"imports": imports, "lng": lng, "withdrawal": withdrawal, "exports": exports,
        "conventional": conventional, "power": power, "injection": injection,
        "production": _missing(day, "MASE:daily", "MASE", "Consuntivo giornaliero non associato; il modulo MASE usa dati mensili"),
        "linepack": _missing(day, "SNAM:physical-linepack", "Snam · misure fisiche", "Mancano misure fisiche ai due estremi del giorno gas", unit="GWh")}
    failed_points = set(state.get("italian_network_data_v1", {}).get("failures", {}))
    for key, bindings in (("imports", group("entry", "entry")), ("lng", group("lng", "entry")), ("exports", group("entry", "exit"))):
        m = measures[key]
        if m.value is not None and m.source_id.startswith("ENTSOG:") and any(b.point_direction in failed_points for b in bindings):
            measures[key] = replace(m, freshness="stale", warnings=(*m.warnings, "Aggiornamento non riuscito · ultima copia valida"))
    imports, lng, exports = (measures[k] for k in ("imports", "lng", "exports"))
    components = tuple(BalanceComponent(key, label, side, measures[key]) for key, label, side in BALANCE)
    coverage = Coverage(sum(c.measure.value is not None for c in components), len(BALANCE))
    events, event_coverage, unresolved = _event_records(network, state, interruptions, day, now)
    findings, flags = [], []
    def finding(category, description, rule, source_id, *, value=None, threshold=None, unit="", observed=None,
                retrieved=None, infrastructure=None, direction=None, evidence=(), identity="", baseline=None, baseline_n=0):
        stable = sha256(f"{rule}|{source_id}|{day}|{infrastructure}|{direction}|{identity}".encode()).hexdigest()[:20]
        findings.append(Attention(stable, category, "info", description, rule, threshold, value, unit,
            source_id, observed, retrieved, infrastructure, direction, tuple(evidence), baseline, baseline_n))
    if coverage.valid < coverage.expected:
        flags.append("balance:partial")
        finding("quality", f"{coverage.expected-coverage.valid} componenti del bilancio non disponibili", "missing_balance_components",
            "IGOR:coverage", value=Decimal(coverage.valid), threshold=Decimal(coverage.expected), unit="componenti")
    seen = set()
    for measure in (*measures.values(), storage, forecast):
        if measure.value is None:
            flags.append("missing:"+measure.source_id)
        elif measure.freshness == "stale" and measure.source_id not in seen:
            seen.add(measure.source_id)
            flags.append("stale:"+measure.source_id)
            finding("quality", measure.source+" · copia non recente o aggiornamento fallito", "stale_critical_source", measure.source_id,
                value=Decimal(str((now-measure.retrieved_at).total_seconds()/3600)),
                threshold=Decimal(str(policy.inventory_ttl_hours if measure.source_id.startswith("GIE:") else policy.network_ttl_hours)),
                unit="ore", observed=measure.observed_at, retrieved=measure.retrieved_at, evidence=measure.evidence_ids)
        if measure.value is not None and measure.coverage.valid < measure.coverage.expected:
            flags.append("partial:"+measure.source_id)
    for binding in (*group("entry", "entry"), *group("lng", "entry")):
        point = point_metrics(observations, binding.point_direction, day, day)
        flow, ratio = point["values"].get("Physical Flow"), point["utilization_pct"]
        evidence = point["observations"]
        dates = evidence_status(evidence, day, now)
        meta = dict(observed=dates["published_oldest"], retrieved=dates["oldest"], infrastructure=binding.infrastructure_id,
                    direction=binding.direction, evidence=tuple(r.source_id for r in evidence))
        if ratio is not None and ratio > policy.capacity_pct:
            finding("capacity", binding.expected_label+" · utilizzo capacità oltre soglia", "capacity_utilization",
                "ENTSOG:"+binding.point_direction, value=ratio, threshold=Decimal(str(policy.capacity_pct)), unit="%", **meta)
        relevant = [s for s in snapshots if s.point_direction == binding.point_direction and s.first <= day <= s.last]
        if flow is None and relevant:
            finding("quality", binding.expected_label+" · flusso atteso non disponibile nella copia", "missing_expected_flow",
                "ENTSOG:"+binding.point_direction, retrieved=relevant[-1].acquired,
                infrastructure=binding.infrastructure_id, direction=binding.direction)
        baseline, baseline_evidence = [], []
        for n in range(1, policy.baseline_days+1):
            prior = applicable_observations(observations, binding.point_direction, day-timedelta(days=n), "Physical Flow")
            if prior:
                baseline.append(prior[0].value)
                baseline_evidence.extend(r.source_id for r in prior)
        if flow is not None and len(baseline) >= policy.baseline_min_days and median(baseline) > 0:
            delta = 100*abs(flow-median(baseline))/median(baseline)
            if delta > policy.deviation_pct:
                meta["evidence"] = (*meta["evidence"], *baseline_evidence)
                finding("deviation", binding.expected_label+f" · scarto dalla mediana di {len(baseline)} giorni", "historical_median_deviation",
                    "ENTSOG:"+binding.point_direction, value=delta, threshold=Decimal(str(policy.deviation_pct)), unit="%",
                    baseline=median(baseline), baseline_n=len(baseline), **meta)
    for event in events:
        binding = next((b for b in network.bindings if b.point_direction == event.get("point_direction")), None)
        finding("event", event["source"]+" · evento associato a un’infrastruttura verificata", "verified_published_event",
            event["source"], value=event.get("value"), unit=event.get("unit") or "",
            observed=_stamp(event.get("observed_at")), retrieved=event["retrieved_at"], infrastructure=event["infrastructure_id"],
            direction=binding.direction if binding else None, evidence=(event["source_id"],), identity=event["source_id"])
    if event_coverage.valid < event_coverage.expected:
        flags.append("events:partial")
    if unresolved:
        flags.append("events:unresolved")
    iip_result = state.get("gie_iip", {}).get("result")
    if iip_result:
        acquired = _stamp(iip_result.get("acquired"))
        if acquired and acquired <= now and (iip_result.get("failed") or state.get("gie_iip", {}).get("error")
                or now-acquired > timedelta(hours=policy.event_ttl_hours)):
            flags.append("events:stale")
            finding("quality", "GIE IIP · copia degli avvisi non recente", "stale_critical_source", "GIE:IIP",
                value=Decimal(str((now-acquired).total_seconds()/3600)), threshold=Decimal(str(policy.event_ttl_hours)), unit="ore", retrieved=acquired)
    used = [m for m in (*measures.values(), storage, forecast) if m.value is not None]
    retrieved = [m.retrieved_at for m in used if m.retrieved_at]
    observed = [m.observed_at for m in used]
    start, stop = gas_day_bounds(day)
    return OverviewStatus(day, "active" if day == active else "last_completed" if day == closed else "historical",
        active, closed, latest_day, min(observed) if observed and all(observed) else None, min(retrieved) if retrieved else None,
        tuple(sorted({m.source_id for m in used})), "unavailable" if not used else "stale" if any(m.freshness == "stale" for m in used) else
        "partial" if coverage.valid < coverage.expected else "observed", coverage, imports, storage, lng, demand, forecast,
        events, tuple(sorted(set(flags))), components, tuple(sorted(findings, key=lambda f: (f.category == "quality", f.id))),
        tuple(session_health(state, now, inspections=inspections)), event_coverage, int((stop-start).total_seconds()/3600))
