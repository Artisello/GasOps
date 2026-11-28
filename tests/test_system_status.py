"""Synthetic measurements against the existing, verified infrastructure catalog."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace

import pandas as pd
import pytest

from gasops_app.data import frame_bundle, utc_starts
from gasops_app.gas_calendar import gas_day_bounds
from gasops_app.italian_network import Observation, load_network_assets
from gasops_app.models import Agent, Kind, Origin, Result, Run
from gasops_app.system_status import build_status, StatusPolicy, ENTSOG

NOW = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
DAY = date(2026, 11, 21)


@pytest.fixture(scope="module")
def network():
    return load_network_assets()


def binding(network, category="entry", direction="entry"):
    ids = {i.id for i in network.infrastructure if i.category == category}
    return next(b for b in network.bindings if b.provider == "ENTSOG" and b.infrastructure_id in ids and b.direction == direction)


def observation(b, value=10, *, day=DAY, indicator="Physical Flow", acquired=None, **kw):
    start, end = gas_day_bounds(day)
    return Observation(infrastructure_id=b.infrastructure_id, point_direction=b.point_direction,
        indicator=indicator, value=None if value is None else D(str(value)), unit="GWh/d",
        period_from=start, period_to=end, gas_day=day if indicator == "Physical Flow" else None,
        retrieved_at=acquired or NOW-timedelta(hours=1), observed_at=(NOW-timedelta(hours=2)).isoformat(),
        source="ENTSOG", source_url=ENTSOG, source_id=f"fixture-{indicator}-{day}",
        quality_status="valid" if value is not None else "N/A", publication_status="Confirmed", **kw)


def snapshot(b, records, *, acquired=None, partial=False, failed=False, day=DAY):
    return SimpleNamespace(point_direction=b.point_direction, records=tuple(records), acquired=acquired or NOW-timedelta(hours=1),
        first=min((r.gas_day for r in records if r.gas_day), default=day), last=day, partial=partial, failed=failed)


def gie(platform, rows, *, acquired=None, scope="IT", failed=False):
    return {"scope":scope, "platform":platform, "frame":pd.DataFrame(rows),
        "acquired":acquired or NOW-timedelta(hours=1), "failed":failed, "cached":True}


def component(status, code):
    return next(c.measure for c in status.components if c.id == code)


def test_missing_stays_missing_but_a_published_zero_is_an_observation(network):
    empty = build_status(network, (), {}, NOW)
    assert empty.entry_flow_observed.value is None
    assert empty.demand_actual.value is None and empty.demand_forecast.value is None
    assert empty.source_coverage.valid == 0 and empty.source_coverage.expected == 9
    assert all(c.measure.value is None for c in empty.components)
    b = binding(network)
    zero = build_status(network, (snapshot(b, [observation(b, 0)]),), {}, NOW)
    assert zero.entry_flow_observed.value == 0
    assert zero.source_coverage.valid == 1 and zero.entry_flow_observed.coverage.valid == 1
    assert not zero.reconcilable and "non riconciliabile" in zero.balance_message


@pytest.mark.parametrize("day,hours", [(date(2026,3,28),23), (date(2026,10,24),25), (DAY,24)])
def test_status_reuses_italian_gas_day_bounds_across_dst(network, day, hours):
    now = gas_day_bounds(day)[1]+timedelta(hours=4)
    s = build_status(network, (), {}, now, gas_day=day)
    assert s.hours == hours and s.gas_day_status == "last_completed"
    active = build_status(network, (), {}, now, gas_day=day+timedelta(days=1))
    assert active.gas_day_status == "active"
    historical = build_status(network, (), {}, now, gas_day=day-timedelta(days=1))
    assert historical.gas_day_status == "historical"
    with pytest.raises(ValueError):
        build_status(network, (), {}, now.replace(tzinfo=None))
    with pytest.raises(ValueError):
        build_status(network, (), {}, now, gas_day=day+timedelta(days=2))


def test_partial_coverage_and_newer_unrelated_indicator_do_not_freshen_flow(network):
    b = binding(network)
    old = NOW-timedelta(hours=20)
    flow = snapshot(b, [observation(b, acquired=old)], acquired=old)
    other = replace(observation(b, indicator="Nomination"), gas_day=DAY)
    # A single response containing old flow plus new nomination preserves each timestamp.
    s = build_status(network, (snapshot(b, [*flow.records, other], partial=True),), {}, NOW)
    assert s.retrieved_at == old and s.source_status == "stale"
    assert s.entry_flow_observed.coverage.valid < s.entry_flow_observed.coverage.expected
    f = next(f for f in s.attention if f.rule == "stale_critical_source")
    assert f.observed_value == 20 and f.retrieved_at == old
    assert "balance:partial" in s.quality_flags


def test_failed_refresh_and_ttl_are_separate_from_measurement_day(network):
    b = binding(network)
    snaps = (snapshot(b, [observation(b)]),)
    state = {"italian_network_data_v1":{"failures":{b.point_direction:NOW}}}
    failed = build_status(network, snaps, state, NOW)
    assert failed.entry_flow_observed.value == 10 and failed.entry_flow_observed.freshness == "stale"
    recent = build_status(network, snaps, {}, NOW, policy=StatusPolicy(network_ttl_hours=2))
    assert recent.entry_flow_observed.freshness != "stale"
    short = build_status(network, snaps, {}, NOW, policy=StatusPolicy(network_ttl_hours=.5))
    assert short.entry_flow_observed.freshness == "stale"


def test_lng_sources_are_alternatives_and_storage_level_is_not_a_balance_flow(network):
    entry, lng = binding(network), binding(network, "lng")
    snaps = (snapshot(entry, [observation(entry, 13)]), snapshot(lng, [observation(lng, 40)]))
    state = {"ALSI_IT":{"result":gie("ALSI", [{"gas_day":DAY, "sendout_gwh_d":80, "status":"C"}])},
        "AGSI+_IT":{"result":gie("AGSI+", [{"gas_day":DAY, "stock_twh":100, "withdrawal_gwh_d":20,
            "injection_gwh_d":0, "status":"C"}])}}
    s = build_status(network, snaps, state, NOW)
    assert s.entry_flow_observed.value == 13 and s.lng_sendout.value == 80
    assert s.lng_sendout.source_id == "GIE:ALSI:IT"  # never 40 + 80
    assert s.storage_level.value == 100 and s.storage_level.unit == "TWh"
    assert component(s, "withdrawal").value == 20 and component(s, "injection").value == 0
    assert s.source_coverage.valid == 4
    state["ALSI_IT"]["result"]["scope"] = "EU"
    assert build_status(network, snaps, state, NOW).lng_sendout.value == 40


def test_inventory_only_day_selection_conflicts_and_no_forward_fill(network):
    rows = [{"gas_day":DAY-timedelta(days=1), "stock_twh":99, "withdrawal_gwh_d":4, "status":"C"}]
    state = {"AGSI+_IT":{"result":gie("AGSI+", rows)}}
    latest = build_status(network, (), state, NOW)
    assert latest.gas_day == DAY-timedelta(days=1)
    chosen = build_status(network, (), state, NOW, gas_day=DAY)
    assert chosen.storage_level.gas_day == DAY-timedelta(days=1)
    assert chosen.storage_level.value == 99 and component(chosen, "withdrawal").value is None
    assert chosen.source_coverage.valid == 0
    state["AGSI+_IT"]["result"] = gie("AGSI+", [*rows, {**rows[0], "stock_twh":98}])
    assert build_status(network, (), state, NOW, gas_day=DAY).storage_level.value is None


def test_sectoral_demand_is_not_imports_or_an_extra_overlapping_balance_component(network):
    from gasops_app.live_sources import BUNDLES
    dates = pd.DatetimeIndex([DAY])
    rows = pd.DataFrame({"period":[DAY.isoformat()], "timestamp_utc":[utc_starts(dates,"daily")[0].isoformat()],
        "energy_unit":["GWh"], "source_flag":["Confirmed"], "demand_gwh":[90],
        "distribution_gwh":[20], "industry_gwh":[30], "power_gwh":[40]})
    origin = Origin(name="Synthetic test of public schema", url=ENTSOG, grain="daily", kind=Kind.HISTORICAL,
        fields=("demand_gwh","distribution_gwh","industry_gwh","power_gwh"), description="fixture", retrieved_at=NOW-timedelta(hours=1))
    bundle = frame_bundle(rows, origin)
    s = build_status(network, (), {BUNDLES:{"daily":bundle}}, NOW)
    assert s.entry_flow_observed.value is None and s.demand_actual.value == 90
    assert component(s, "conventional").value == 50 and component(s, "power").value == 40
    assert s.source_coverage.valid == 2 and len(s.components) == 9
    assert "non domanda nazionale" in s.demand_actual.warnings[0]
    fake = replace(bundle, origin=origin.model_copy(update={"kind":Kind.SYNTHETIC}))
    assert build_status(network, (), {BUNDLES:{"daily":fake}}, NOW).demand_actual.value is None


def test_physical_linepack_and_daily_production_are_not_inferred_from_other_quantities(network):
    state = {"jarvis_public_snapshot_v1":{"versions":pd.DataFrame([
        {"gas_day":DAY, "expected_linepack_gwh":1000}, {"gas_day":DAY, "expected_linepack_gwh":1100}])}}
    s = build_status(network, (), state, NOW)
    assert component(s, "linepack").value is None and component(s, "production").value is None
    assert not s.reconcilable


def test_capacity_rule_is_configurable_and_requires_same_direction_and_full_day(network):
    b = binding(network)
    flow, capacity = observation(b, 95), observation(b, 100, indicator="Firm Technical")
    snaps = (snapshot(b, [flow, capacity]),)
    s = build_status(network, snaps, {}, NOW)
    f = next(f for f in s.attention if f.rule == "capacity_utilization")
    assert f.observed_value == 95 and f.threshold == 90 and f.infrastructure_id == b.infrastructure_id
    assert f.severity == "info" and f.evidence_ids
    assert not any(f.rule == "capacity_utilization" for f in build_status(network, snaps, {}, NOW, policy=StatusPolicy(capacity_pct=99)).attention)
    short = replace(capacity, period_from=capacity.period_from+timedelta(hours=1))
    assert not any(f.rule == "capacity_utilization" for f in build_status(network, (snapshot(b,[flow,short]),), {}, NOW).attention)
    with pytest.raises(ValueError):
        StatusPolicy(baseline_min_days=29)


def test_deviation_needs_sufficient_prior_history_and_preserves_baseline_evidence(network):
    b = binding(network)
    history = [observation(b, 10, day=DAY-timedelta(days=n)) for n in range(1,15)]
    snaps = (snapshot(b, [*history, observation(b, 30)]),)
    s = build_status(network, snaps, {}, NOW)
    f = next(f for f in s.attention if f.rule == "historical_median_deviation")
    assert f.baseline == 10 and f.baseline_n == 14 and f.observed_value == 200
    assert len(f.evidence_ids) >= 15
    assert not any(f.rule == "historical_median_deviation" for f in build_status(network, (snapshot(b,[*history[:13],observation(b,30)]),), {}, NOW).attention)
    assert not any(f.rule == "historical_median_deviation" for f in build_status(network, snaps, {}, NOW, policy=StatusPolicy(deviation_pct=250)).attention)


def test_new_missing_response_replaces_old_value_and_has_a_quality_finding(network):
    b = binding(network)
    old = snapshot(b, [observation(b)], acquired=NOW-timedelta(hours=2))
    new = snapshot(b, [observation(b, None)], acquired=NOW-timedelta(hours=1))
    s = build_status(network, (old, new), {}, NOW, gas_day=DAY)
    assert s.entry_flow_observed.value is None
    assert any(f.rule == "missing_expected_flow" and f.infrastructure_id == b.infrastructure_id for f in s.attention)
    assert not any(f.rule in ("capacity_utilization", "historical_median_deviation") for f in s.attention)


def test_future_unaligned_and_unverified_observations_do_not_count(network):
    b = binding(network)
    r = observation(b)
    for invalid in (replace(r,retrieved_at=NOW+timedelta(hours=1)), replace(r,mapping_confidence="unknown"),
            replace(r,period_to=r.period_to-timedelta(hours=1)), replace(r,infrastructure_id="unverified"),
            replace(r,observed_at=(NOW+timedelta(hours=1)).isoformat()), replace(r,unit="m³/d")):
        s = build_status(network, (snapshot(b,[invalid]),), {}, NOW, gas_day=DAY)
        assert s.entry_flow_observed.value is None


def test_active_day_cannot_supply_a_completed_daily_actual(network):
    b = binding(network)
    day = DAY+timedelta(days=1)
    s = build_status(network, (snapshot(b,[observation(b,day=day)],day=day),), {}, NOW, gas_day=day)
    assert s.gas_day_status == "active" and s.entry_flow_observed.value is None


@pytest.mark.parametrize("published,expected", [("C",None),("E",D(20))])
def test_active_gie_day_accepts_only_explicitly_estimated_daily_flows(network,published,expected):
    day = DAY+timedelta(days=1)
    state = {"AGSI+_IT":{"result":gie("AGSI+", [{"gas_day":day, "stock_twh":100,
        "withdrawal_gwh_d":20, "status":published}])}}
    s = build_status(network, (), state, NOW, gas_day=day)
    assert component(s,"withdrawal").value == expected
    assert s.storage_level.value == 100
    if expected is not None:
        assert component(s,"withdrawal").status == "estimated"


def test_response_quality_and_point_coverage_are_distinct(network):
    bindings = [b for b in network.bindings if b.provider == "ENTSOG" and b.direction == "entry" and b.external_id.startswith("ITP-")]
    copies = tuple(snapshot(b,[observation(b)],partial=True) for b in bindings)
    m = build_status(network, copies, {}, NOW).entry_flow_observed
    assert m.coverage.valid == m.coverage.expected and m.freshness == "partial"
    assert "Risposta della fonte parziale" in m.warnings
    assert "Copertura parziale dei punti mappati" not in m.warnings


def test_duplicate_events_count_once_with_stable_ids_and_zero_is_not_an_outage(network):
    b = binding(network)
    start, end = gas_day_bounds(DAY)
    event = dict(infrastructure_id=b.infrastructure_id, point_direction=b.point_direction, source="ENTSOG TP Interruptions",
        source_id="fixture-event", period_from=start, period_to=end, observed_at=NOW-timedelta(hours=2),
        retrieved_at=NOW-timedelta(hours=1), value=D(5), unit="GWh/d", status="Pubblicato", mapping_confidence="confirmed")
    result = dict(point_direction=b.point_direction, records=(event,dict(event)), acquired=NOW-timedelta(hours=1), first=DAY,last=DAY)
    first = build_status(network, (), {}, NOW, gas_day=DAY, interruptions=(result,))
    assert len(first.active_events) == 1
    f = next(f for f in first.attention if f.rule == "verified_published_event")
    second = build_status(network, (), {}, NOW+timedelta(minutes=1), gas_day=DAY, interruptions=(result,))
    assert f.id == next(f for f in second.attention if f.rule == "verified_published_event").id
    assert f.infrastructure_id == b.infrastructure_id
    result["records"] = ({**event,"value":D(0)}, {**event,"mapping_confidence":"unknown"})
    assert not build_status(network, (), {}, NOW, gas_day=DAY, interruptions=(result,)).active_events


def test_iip_exact_codes_deduplicate_identical_messages_without_matching_names(network):
    b = next(b for b in network.bindings if b.provider == "ALSI")
    message = {"messageId":"fixture-iip", "publicationDateTime":(NOW-timedelta(days=1)).isoformat(),
        "assetCode":b.external_id, "eventStatus":"Active", "countryCode":"IT",
        "eventStart":gas_day_bounds(DAY)[0].isoformat(), "eventStop":gas_day_bounds(DAY)[1].isoformat()}
    result = {"messages":[message,dict(message),{**message,"messageId":"wrong","assetCode":"unknown","assetName":"Panigaglia"}],
        "source_url":"https://iip.gie.eu/", "acquired":NOW-timedelta(hours=1)}
    s = build_status(network, (), {"gie_iip":{"result":result}}, NOW, gas_day=DAY)
    assert len(s.active_events) == 1 and s.active_events[0]["infrastructure_id"] == b.infrastructure_id
    assert "events:unresolved" in s.quality_flags


def test_cached_public_forecast_is_estimated_and_synthetic_or_archival_runs_are_excluded(network):
    origin = Origin(name="ENTSOG", url=ENTSOG, grain="daily", fields=("demand_gwh",), kind=Kind.HISTORICAL,
        retrieved_at=NOW-timedelta(hours=1), latest_period=(DAY-timedelta(days=1)).isoformat(), description="fixture")
    run = Run(question="fixture", source=origin, input_sha256="fixture", assumptions={}, started_at=NOW-timedelta(minutes=30),
        results={Agent.FORECAST:Result(agent=Agent.FORECAST, summary="fixture", values={"forecast":{"points":[{"period":DAY.isoformat(),"estimate":120}]}})})
    s = build_status(network, (), {"last_run":run}, NOW, gas_day=DAY)
    assert s.demand_forecast.value == 120 and s.demand_forecast.status == "estimated"
    assert s.demand_actual.value is None and s.source_coverage.valid == 0
    for source in (origin.model_copy(update={"kind":Kind.SYNTHETIC}), origin.model_copy(update={"archive":True}),
                   origin.model_copy(update={"grain":"monthly"})):
        assert build_status(network, (), {"last_run":run.model_copy(update={"source":source})}, NOW, gas_day=DAY).demand_forecast.value is None


def test_event_monitoring_without_copies_is_unavailable_not_zero_active(network):
    from gasops_app.system_status import event_monitoring_label
    status=build_status(network,(),{},NOW,gas_day=DAY)
    assert status.event_monitoring["status"]=="unavailable"
    assert status.event_monitoring["active_event_count"] is None
    assert status.event_coverage.valid==0
    assert event_monitoring_label(status)=="Monitoraggio eventi non disponibile"


def test_event_coverage_excludes_partial_stale_and_outside_day_copies(network):
    from gasops_app.italian_network import verified_bindings
    bindings=tuple(verified_bindings(network))[:4]
    copies=tuple(dict(point_direction=b.point_direction,records=(),first=DAY,last=DAY,
                      acquired=NOW-timedelta(hours=1),partial=False,failed=False) for b in bindings)
    partial={**copies[1],"partial":True}
    stale={**copies[2],"acquired":NOW-timedelta(hours=13)}
    outside={**copies[3],"first":DAY-timedelta(days=1),"last":DAY-timedelta(days=1)}
    status=build_status(network,(),{},NOW,gas_day=DAY,interruptions=(copies[0],partial,stale,outside))
    assert status.event_coverage.valid==1
    assert status.event_monitoring["entsog_queried"]==3
    assert status.event_monitoring["entsog_stale"]==1
    assert status.event_monitoring["status"]=="partial"
    assert status.event_monitoring["active_event_count"] is None


def test_event_monitoring_keeps_iip_coverage_separate(network):
    from gasops_app.data import ROME
    start,stop=gas_day_bounds(DAY)
    result={"messages":[],"source_url":"https://iip.gie.eu/","acquired":NOW,
            "request_from":start.astimezone(ROME).date().isoformat(),
            "request_to":stop.astimezone(ROME).date().isoformat(),
            "pagination_verified":True,"partial":False,"reported_total":0}
    status=build_status(network,(),{"gie_iip":{"result":result}},NOW,gas_day=DAY)
    assert status.event_monitoring["iip_status"]=="complete"
    assert status.event_monitoring["iip_received_records"]==0
    assert status.event_monitoring["active_event_count"] is None
    assert status.event_coverage.valid==0
    result["request_from"]=(DAY+timedelta(days=2)).isoformat()
    status=build_status(network,(),{"gie_iip":{"result":result}},NOW,gas_day=DAY)
    assert status.event_monitoring["iip_status"]=="window_unverified"
    assert status.event_monitoring["iip_received_records"] is None


def test_unknown_interruption_quantity_cannot_certify_coverage(network):
    b=binding(network)
    start,stop=gas_day_bounds(DAY)
    event=dict(source="ENTSOG TP Interruptions",value=None,period_from=start,period_to=stop)
    result=dict(point_direction=b.point_direction,records=(event,),acquired=NOW,first=DAY,last=DAY,partial=False)
    status=build_status(network,(),{},NOW,gas_day=DAY,interruptions=(result,))
    assert status.event_coverage.valid==0
    assert status.event_monitoring["unresolved"]==1
