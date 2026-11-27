"""P1 regressions. All generated readings/events below are synthetic fixtures."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import json

import pytest
import requests
from streamlit.testing.v1 import AppTest

from gasops_app.system_status_page import ARCHIVE_KEY
from gasops_app import italian_network_page as view
from gasops_app.gas_calendar import gas_day_bounds
from gasops_app.italian_network import (Observation, READING_MODES, filter_infrastructure,
    point_intelligence, reading_infrastructure, merge_observations)
from gasops_app.italian_network_events import verified_events
from gasops_app.italian_network_map import deck
from gasops_app.italian_network_sources import Snapshot, decode_snapshot, encode_snapshot

DAY = date(2026,11,20)
NOW = datetime(2026,11,22,12,tzinfo=timezone.utc)


@pytest.fixture
def assets():
    return view.assets()


def reading(binding, indicator="Physical Flow", value="2", day=DAY, **changes):
    start, stop = gas_day_bounds(day)
    return replace(Observation(binding.infrastructure_id,binding.point_direction,indicator,D(value),"GWh/d",
        start,stop,day,NOW-timedelta(hours=1),(NOW-timedelta(hours=2)).isoformat(),
        "Synthetic test source","https://example.invalid/fixture","synthetic-"+indicator,
        "valid","Confirmed"),**changes)


def point(network):
    return next(b for b in network.bindings_for("INET_BP_65","ENTSOG") if b.direction == "entry")


def test_all_seven_measures_keep_direction_units_period_and_published_headroom(assets):
    network,_,_ = assets
    b = point(network)
    amounts = {"Physical Flow":"2","Nomination":"2.1","Renomination":"2.2","Allocation":"1.9",
               "Firm Technical":"4","Firm Booked":"3","Firm Available":"0.5"}
    rows = tuple(reading(b,k,v) for k,v in amounts.items())+(reading(b,day=DAY-timedelta(days=1)),
        reading(b,"Firm Technical","5",day=DAY-timedelta(days=1)))
    snapshot = Snapshot(b.point_direction,rows,DAY-timedelta(days=1),DAY,NOW-timedelta(hours=1))
    # Existing on-disk schema remains readable without a migration or new cache.
    restored = decode_snapshot(encode_snapshot(snapshot))
    info = point_intelligence(network,b.infrastructure_id,merge_observations((restored,)),DAY,NOW,snapshots=(restored,))
    assert info["values"] == {k:D(v) for k,v in amounts.items()}
    assert info["utilization_pct"] == 50
    assert info["headroom_gwh_d"] == D("0.5") != D(4)-D(2)
    assert info["headroom_kind"] == "published"
    assert info["change_gwh_d"] == 0 and info["capacity_change_gwh_d"] == -1
    assert info["binding"].direction == "entry"
    assert all(o.unit == "GWh/d" and (o.period_from,o.period_to) == gas_day_bounds(DAY)
               for rows in info["publications"].values() for o in rows)


@pytest.mark.parametrize("case",["clock","unit","other_direction","zero_capacity","missing","conflict"])
def test_utilization_withholds_non_comparable_capacity_and_never_derives_headroom(assets,case):
    n,_,_ = assets
    b = point(n)
    flow, capacity = reading(b), reading(b,"Firm Technical","4")
    if case == "clock":
        capacity = replace(capacity,gas_day=None,period_from=capacity.period_from+timedelta(hours=1),period_to=capacity.period_to+timedelta(hours=1))
    if case == "unit":capacity = replace(capacity,unit="m³/d")
    if case == "other_direction":capacity = replace(capacity,point_direction=b.operator_id+b.external_id+"exit")
    if case == "zero_capacity":capacity = replace(capacity,value=D(0))
    if case == "missing":capacity = replace(capacity,value=None,quality_status="N/A")
    if case == "conflict":capacity = replace(capacity,quality_status="conflict")
    info = point_intelligence(n,b.infrastructure_id,(flow,capacity),DAY,NOW)
    assert info["utilization_pct"] is None and info["headroom_gwh_d"] is None
    assert info["values"]["Physical Flow"] == 2
    if case == "clock":
        assert info["publications"]["Firm Technical"] == (capacity,)
        assert "Firm Technical" not in info["values"]


def test_zero_is_a_measure_missing_does_not_fall_back_to_another_day(assets):
    n,_,_ = assets
    b = point(n)
    previous = reading(b,"Physical Flow","3",day=DAY-timedelta(days=1))
    missing = point_intelligence(n,b.infrastructure_id,(previous,),DAY,NOW)
    assert missing["values"] == {} and missing["change_gwh_d"] is None
    zero = point_intelligence(n,b.infrastructure_id,(previous,reading(b,value="0"),reading(b,"Firm Technical","4")),DAY,NOW)
    assert zero["flow_available"] and zero["utilization_pct"] == 0 and zero["change_gwh_d"] == -3


def test_a_capacity_change_inside_the_day_invalidates_the_daily_ratio(assets):
    n,_,_ = assets
    b = point(n)
    capacity = reading(b,"Firm Technical","4")
    partial = replace(capacity,value=D(3),gas_day=None,period_from=capacity.period_from+timedelta(hours=12))
    info = point_intelligence(n,b.infrastructure_id,(reading(b),capacity,partial),DAY,NOW)
    assert info["utilization_pct"] is None and "Firm Technical" not in info["values"]


@pytest.mark.parametrize("day,hours",[(date(2026,3,28),23),(date(2026,10,24),25)])
def test_comparable_capacity_uses_real_gas_day_bounds_across_dst(assets,day,hours):
    n,_,_ = assets
    b = point(n)
    rows = (reading(b,day=day),reading(b,"Firm Technical","4",day=day))
    info = point_intelligence(n,b.infrastructure_id,rows,day,NOW)
    assert (rows[0].period_to-rows[0].period_from).total_seconds()/3600 == hours
    assert info["utilization_pct"] == 50


@pytest.mark.parametrize("case",["binding","duplicate_binding","observation","future_retrieval","future_publication","wrong_day","incomplete_day"])
def test_flow_mode_rejects_unverified_or_future_physical_evidence(assets,case):
    n,_,_ = assets
    b = point(n)
    row = reading(b)
    if case == "binding":n = replace(n,bindings=tuple(replace(x,mapping_confidence="candidate") if x == b else x for x in n.bindings))
    if case == "duplicate_binding":n = replace(n,bindings=(*n.bindings,b))
    if case == "observation":row = replace(row,mapping_confidence="candidate")
    if case == "future_retrieval":row = replace(row,retrieved_at=NOW+timedelta(hours=1))
    if case == "future_publication":row = replace(row,observed_at=(NOW+timedelta(hours=1)).isoformat())
    if case == "wrong_day":row = replace(row,gas_day=DAY-timedelta(days=1))
    if case == "incomplete_day":row = replace(row,period_to=NOW+timedelta(hours=1),gas_day=None)
    info = point_intelligence(n,b.infrastructure_id,(row,),DAY,NOW)
    assert not info["flow_available"]
    items = tuple(i for i in n.infrastructure if i.id == b.infrastructure_id)
    assert not reading_infrastructure(items,"FLOW",{b.infrastructure_id:info})


def test_stale_data_stays_visible_with_original_acquisition_and_attention_marker(assets):
    n,boundary,_ = assets
    b = point(n)
    row = reading(b,retrieved_at=NOW-timedelta(hours=13))
    info = point_intelligence(n,b.infrastructure_id,(row,),DAY,NOW)
    assert info["stale"] and info["status"]["oldest"] == row.retrieved_at
    item = next(i for i in n.infrastructure if i.id == b.infrastructure_id)
    assert reading_infrastructure((item,),"ATTENTION",{item.id:info}) == (item,)
    spec = json.loads(deck(n,boundary,(item,),reading_mode="ATTENTION",day=DAY,intelligence={item.id:info}).to_json())
    quality = next(l for l in spec["layers"] if l["id"] == "quality-marks")
    assert not quality["pickable"] and quality["getIcon"] == "quality"
    failed = point_intelligence(n,b.infrastructure_id,(reading(b),),DAY,NOW,failures={b.point_direction:NOW})
    assert failed["stale"]  # A failed explicit refresh does not silently freshen the copy.


def test_events_need_exact_binding_and_conflicting_releases_are_not_located(assets):
    n,_,_ = assets
    b = point(n)
    start,stop = gas_day_bounds(DAY)
    event = dict(infrastructure_id=b.infrastructure_id,point_direction=b.point_direction,source="ENTSOG TP Interruptions",
        source_id="synthetic-event",source_url="https://example.invalid/fixture",period_from=start,period_to=stop,
        observed_at=NOW-timedelta(hours=2),retrieved_at=NOW-timedelta(hours=1),value=D(1),unit="GWh/d",status="Pubblicato",mapping_confidence="confirmed")
    events,unresolved = verified_events(n,(event,event),DAY,DAY,NOW)
    assert events == (event,) and unresolved == 0
    for invalid in ({**event,"mapping_confidence":"unknown"}, {**event,"point_direction":"unverified"},
                    {**event,"infrastructure_id":"INET_PL_5"},{**event,"retrieved_at":NOW+timedelta(hours=1)}):
        assert verified_events(n,(invalid,),DAY,DAY,NOW) == ((),1)
    assert verified_events(n,(event,{**event,"value":D(2)}),DAY,DAY,NOW) == ((),1)
    assert verified_events(n,({**event,"value":D(0)},),DAY,DAY,NOW) == ((),0)


def test_modes_do_not_duplicate_points_or_animate_pipeline_flows(assets):
    n,boundary,snapshots = assets
    rows = merge_observations(snapshots)
    info = {b.infrastructure_id:point_intelligence(n,b.infrastructure_id,rows,DAY,NOW) for b in n.bindings if b.provider == "ENTSOG"}
    selected = "INET_PL_5"
    for mode in READING_MODES:
        items = reading_infrastructure(n.infrastructure,mode,info,selected=selected,event_ids={"INET_BP_65"},finding_ids={"INET_BP_65"})
        assert selected in {i.id for i in items}
        spec = json.loads(deck(n,boundary,items,selected,{"INET_BP_65"} if mode == "ATTENTION" else (),
            reading_mode=mode,intelligence=info,finding_ids={"INET_BP_65"},day=DAY).to_json())
        layers = {l["id"]:l for l in spec["layers"]}
        points = layers["infrastructure-points"]["data"]
        assert len({r["infra_id"] for r in points}) == len(points)
        assert layers["historical-links"]["data"] == layers["pipeline-hit-targets"]["data"]
        assert not any(l["@@type"] in ("TripsLayer","ArcLayer","FlowLayer") for l in spec["layers"])
        assert not spec.get("mapProvider") and all(not isinstance(l.get("data"),str) for l in spec["layers"])
        if mode == "ATTENTION":
            assert layers["event-rings"]["getIcon"] != layers["finding-marks"]["getIcon"]
            assert not layers["event-rings"]["pickable"] and not layers["finding-marks"]["pickable"]
        if mode == "SYSTEM":
            assert sum(r["category"] == "power" for r in points) == 69
            assert sum(r["category"] == "node" for r in points) == 177


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(view,"utc_now",lambda:NOW)
    def forbidden(*a,**kw):raise AssertionError("A reading-mode switch must not refresh providers")
    monkeypatch.setattr(requests.Session,"request",forbidden)
    monkeypatch.setattr(requests,"get",forbidden)


@pytest.mark.parametrize("layout",["overview","full"])
def test_power_plants_are_visible_before_selection_in_both_default_maps(assets,offline,layout):
    n,_,_ = assets
    app = AppTest.from_string(f"from gasops_app.italian_network_page import panel\npanel(mode='{layout}')",default_timeout=30).run()
    assert not app.exception and app.session_state[view.SELECTED] == "INET_BP_65"
    spec = json.loads(app.get("deck_gl_json_chart")[0].proto.json)
    points = next(l["data"] for l in spec["layers"] if l["id"] == "infrastructure-points")
    assert {r["infra_id"] for r in points if r["category"] == "power"} == {i.id for i in n.infrastructure if i.category == "power"}
    assert any("Centrali elettriche" in h.proto.body for h in app.get("html"))


def test_modes_preserve_filters_period_and_selected_pipeline_without_fetches(assets,offline):
    n,_,_ = assets
    app = AppTest.from_string("from gasops_app.italian_network_page import panel\npanel()",default_timeout=30).run()
    app.multiselect(key="net_layers").set_value(["pipeline","power"]).run()
    app.multiselect(key="net_regions").set_value(["Piemonte"]).run()
    app.selectbox(key="net_infrastructure").set_value("INET_PL_5").run()
    period = (date(2026,11,18),DAY)
    app.date_input(key="net_period").set_value(period).run()
    for mode in READING_MODES:
        app.radio(key="net_reading_full").set_value(mode).run()
        assert not app.exception
        assert app.session_state[view.READING] == mode
        if mode in ("FLOW","ATTENTION"):
            assert app.selectbox(key="net_infrastructure").value is None
            assert app.session_state[view.SELECTED] is None
        else:
            assert app.selectbox(key="net_infrastructure").value is not None
        assert app.multiselect(key="net_layers").value == ["pipeline","power"]
        assert app.multiselect(key="net_regions").value == ["Piemonte"]
        assert app.date_input(key="net_period").value == period
        assert len(app.get("deck_gl_json_chart")) == 1
        assert not app.get("plotly_chart")  # No fabricated segment telemetry.
    # Explicit category/region filters still constrain every reading mode.
    expected = {i.id for i in filter_infrastructure(n,["pipeline","power"],regions=["Piemonte"])}
    spec = json.loads(app.get("deck_gl_json_chart")[0].proto.json)
    points = next(l["data"] for l in spec["layers"] if l["id"] == "infrastructure-points")
    assert {r["infra_id"] for r in points if r.get("active")} <= expected


def test_native_pick_indices_keep_their_identity_when_modes_filter_markers(assets):
    n,boundary,snapshots = assets
    rows = merge_observations(snapshots)
    info = {b.infrastructure_id:point_intelligence(n,b.infrastructure_id,rows,DAY,NOW) for b in n.bindings if b.provider == "ENTSOG"}
    indexes = []
    for mode in READING_MODES:
        visible = reading_infrastructure(n.infrastructure,mode,info,selected="INET_BP_89")
        spec = json.loads(deck(n,boundary,visible,"INET_BP_89",reading_mode=mode,intelligence=info,
            day=DAY,stable_picking=True).to_json())
        layers = {l["id"]:l for l in spec["layers"]}
        points = layers["infrastructure-points"]["data"]
        labels = layers["point-labels"]["data"]["features"]
        indexes.append(([p["infra_id"] for p in points],[r["properties"]["infra_id"] for r in labels]))
        assert all(p["radius"] == 0 for p in points if not p["active"])
        assert all(p["hit_radius"] == 0 for p in points if not p["active"])
        assert layers["infrastructure-points"]["radiusMinPixels"] == 0
        assert all(r["properties"]["label_size"] == 0 for r in labels if not r["properties"]["label"])
    assert all(index == indexes[0] for index in indexes)


def test_overview_has_real_d30_gaps_and_same_sections_as_full_card(offline):
    app = AppTest.from_string("from gasops_app.italian_network_page import panel\npanel(mode='overview')",default_timeout=30)
    app.session_state[ARCHIVE_KEY] = True
    app.run()
    assert not app.exception
    assert [t.label for t in app.tabs] == ["Dati","Storico","Eventi","Fonti"]
    captions = {c.value for c in app.caption}
    assert {"TREND · D-30","EVENTI","DATI E PROVENIENZA"} <= captions
    assert any(e.label=="Capacità e dati commerciali" for e in app.expander)
    commercial=next(d.value for d in app.dataframe if "Periodo e validità" in d.value.columns)
    assert "Nomina" in set(commercial.Indicatore) and "Capacità tecnica firm" in set(commercial.Indicatore)
    figure = json.loads(app.get("plotly_chart")[0].proto.spec)
    assert len(figure["data"][0]["x"]) == 30
    assert sum(y is not None for y in figure["data"][0]["y"]) == 7
    assert not figure["data"][0]["connectgaps"]
    assert any("7/30 giorni gas" in c.value for c in app.caption)


def test_flow_pick_retains_the_actual_rendered_direction(monkeypatch):
    state = {}
    monkeypatch.setattr(view.st,"session_state",state)
    event = {"selection":{"objects":{"infrastructure-points":[{"infra_id":"INET_BP_89","direction":"malicious"}]}}}
    view._accept_pick("chart",("INET_BP_89",),"full",event,point_directions=(("INET_BP_89","exit"),))
    assert state[view.SELECTED] == "INET_BP_89" and state["net_direction"] == "exit"


def test_previous_default_upgrades_power_layer_once_but_custom_filters_survive(monkeypatch):
    state = {"net_layers":["pipeline","entry","lng","storage","compressor"]}
    monkeypatch.setattr(view.st,"session_state",state)
    view._initialize_layers()
    assert "power" in state["net_layers"] and "node" in state["net_layers"]
    state["net_layers"] = ["lng"]
    view._initialize_layers()
    assert state["net_layers"] == ["lng"]
    custom = {"net_layers":["storage","lng"]}
    monkeypatch.setattr(view.st,"session_state",custom)
    view._initialize_layers()
    assert custom["net_layers"] == ["storage","lng"]


def test_full_map_handles_only_future_cache_without_displaying_readings(offline,monkeypatch):
    monkeypatch.setattr(view,"utc_now",lambda:datetime(2026,11,22,2,tzinfo=timezone.utc))
    app = AppTest.from_string("from gasops_app.italian_network_page import panel\npanel()",default_timeout=30).run()
    assert not app.exception and len(app.get("deck_gl_json_chart")) == 1
    assert not app.metric and any("Nessun dato operativo" in c.value for c in app.caption)


def test_map_hover_targets_always_have_resolved_tooltip_fields(assets):
    n,boundary,_=assets
    visible=tuple(i for i in n.infrastructure if i.id=="INET_BP_65" or i.category=="pipeline")
    spec=json.loads(deck(n,boundary,visible,"INET_BP_65",stable_picking=True).to_json())
    layers={l["id"]:l for l in spec["layers"]}
    assert not layers["point-labels"]["pickable"]
    assert layers["infrastructure-points"]["pickable"]
    assert layers["pipeline-hit-targets"]["pickable"]
    fields={"safe_name","safe_status","safe_summary"}
    for row in layers["infrastructure-points"]["data"]:
        assert fields <= row.keys()
        if not row["active"]:
            assert all(row[field]=="" for field in fields)
            assert row["hit_radius"]==0
        else:
            assert row["safe_name"] and row["safe_summary"]
    assert all(fields <= f["properties"].keys() for f in layers["pipeline-hit-targets"]["data"]["features"])


@pytest.mark.parametrize("record", [
    {"infra_id":"point","active":False},
    {"properties":{"infra_id":"point","active":False}},
])
def test_inactive_map_pick_cannot_change_selection(record):
    from gasops_app.italian_network import selected_id
    event={"selection":{"objects":{"infrastructure-points":[record]}}}
    assert selected_id(event,{"point"}) is None


def test_gries_preview_shows_both_confirmed_directions_and_distinguishes_zero_from_missing(assets):
    from gasops_app.italian_network_map import bidirectional_preview
    from gasops_app.italian_network import verified_bindings
    n,boundary,_=assets
    identifier="INET_BP_78"
    bindings=verified_bindings(n,identifier)
    assert {b.direction for b in bindings}=={"entry","exit"}
    entry=next(b for b in bindings if b.direction=="entry")
    exit=next(b for b in bindings if b.direction=="exit")
    rows=(reading(entry,value="213.8"),reading(exit,value="0"))
    for direction in ("entry","exit"):
        info=point_intelligence(n,identifier,rows,DAY,NOW,direction=direction)
        preview=bidirectional_preview(bindings,rows,DAY,info)
        assert "Ingresso: 213,8 GWh/d" in preview
        assert "Uscita: 0,0 GWh/d" in preview
        spec=json.loads(deck(n,boundary,tuple(i for i in n.infrastructure if i.id==identifier),
            identifier,day=DAY,observations=rows,intelligence={identifier:info},reading_mode="SYSTEM").to_json())
        target=next(l["data"][0] for l in spec["layers"] if l["id"]=="infrastructure-points")
        assert target["safe_status"]=="Bidirezionale · ENTSOG"
        assert "Ingresso: 213,8 GWh/d" in target["safe_summary"]
        assert "Uscita: 0,0 GWh/d" in target["safe_summary"]
        assert target["direction"]==direction
    missing=bidirectional_preview(bindings,rows[:1],DAY,{})
    assert "Uscita: N/D" in missing
    assert "Uscita: 0,0" not in missing
    assert bidirectional_preview((entry,),rows,DAY,{}) is None
    assert "Ingresso: N/D" in bidirectional_preview(bindings,rows,DAY-timedelta(days=1),{})


def test_reading_selection_never_overrides_mode_membership(assets):
    n,_,_=assets
    storage="INET_SR_37"
    entry="INET_BP_65"
    node="INET_N_1034"
    items=tuple(i for i in n.infrastructure if i.id in (storage,entry,node))
    assert {i.id for i in items}=={storage,entry,node}
    info={entry:{"binding":object(),"flow_available":True,"stale":False}}
    for mode,previous,expected in (
        ("FLOW",storage,entry),("ATTENTION",storage,entry),
        ("SYSTEM",node,node),
        ("SYSTEM",storage,storage),("FLOW",entry,entry)):
        findings={entry} if mode=="ATTENTION" else set()
        displayed=reading_infrastructure(items,mode,info,selected=previous,finding_ids=findings)
        assert view._resolve_selection(displayed,mode,previous,findings=findings)==expected
        if mode in ("FLOW","ATTENTION"):
            assert storage not in {i.id for i in displayed}
    assert view._resolve_selection(reading_infrastructure(items,"ATTENTION",info),"ATTENTION",storage) is None
    assert node in {i.id for i in reading_infrastructure(items,"SYSTEM",info)}
    assert node not in {i.id for i in reading_infrastructure(items,"SYSTEM",info,include_nodes=False)}
    assert reading_infrastructure(items,"INFRASTRUCTURE",info)==reading_infrastructure(items,"SYSTEM",info)
