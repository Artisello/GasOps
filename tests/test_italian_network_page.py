"""Offline interactions and independently failing providers, with synthetic fixtures."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json

import pandas as pd
import pytest
import requests
from streamlit.testing.v1 import AppTest

from gasops_app import italian_network_page as page, italian_network_refresh as refresh
from gasops_app.italian_network import load_network_assets
from gasops_app.italian_network_events import iip_events
from gasops_app.italian_network_map import deck
from gasops_app.public_data import SourceUnavailable

NOW=datetime(2026,11,22,2,tzinfo=timezone.utc)
DAY=date(2026,11,20)
SCRIPT="from gasops_app.italian_network_page import panel\npanel()"


def offline(monkeypatch):
    def forbidden(*a,**kw):raise AssertionError("Navigation must not call an upstream API")
    monkeypatch.setattr(requests.Session,"request",forbidden)
    monkeypatch.setattr(requests,"get",forbidden)
    monkeypatch.setattr(page,"utc_now",lambda:NOW)


def test_deck_is_self_contained_italy_only_and_pickable_layers_have_stable_ids():
    network,boundary,_=page.assets()
    observations=page.merge_observations(page.assets()[2])
    spec=json.loads(deck(network,boundary,network.infrastructure,"INET_BP_65",{"INET_BP_65"},observations=observations,day=DAY).to_json())
    assert not spec.get("mapProvider") and not spec.get("mapStyle")
    assert spec["initialViewState"]["longitude"] == 12.5
    assert {r["id"] for r in spec["layers"]} >= {"italy-outline","historical-links","infrastructure-points","event-rings"}
    assert all(r.get("id") for r in spec["layers"] if r.get("pickable"))
    assert all(not isinstance(layer.get("data"),str) for layer in spec["layers"])
    assert len(spec["layers"][0]["data"]["features"]) == 1
    assert "Natural Earth" in json.dumps(spec)
    points=next(r["data"] for r in spec["layers"] if r["id"] == "infrastructure-points")
    assert "GWh/d" in next(r["safe_value"] for r in points if r["infra_id"] == "INET_BP_65")


@pytest.mark.parametrize("category", ["entry","lng","storage","compressor","power","node"])
def test_each_point_layer_uses_literal_pixels_and_hard_size_limits(category):
    # Regression: radius_units="pixels" becomes "@@=pixels" in PyDeck JSON.
    # The frontend requires the literal enum. Check the transmitted payload.
    network,boundary,_=page.assets()
    visible=tuple(i for i in network.infrastructure if i.category == category)
    selected=visible[0].id
    spec=json.loads(deck(network,boundary,visible,selected,{selected}).to_json())
    layers={r["id"]:r for r in spec["layers"]}
    markers=layers["infrastructure-points"]
    assert markers["radiusUnits"] == "pixels" and markers["radiusMaxPixels"] == 7
    assert all(2.5 <= r["radius"] <= 6 for r in markers["data"])
    assert layers["selected-point"]["radiusMaxPixels"] == 10
    assert layers["event-rings"]["radiusMaxPixels"] == 13
    for layer in layers.values():
        if layer["@@type"] == "ScatterplotLayer":
            assert layer["radiusUnits"] == "pixels" and layer["lineWidthUnits"] == "pixels"
            assert layer["lineWidthMaxPixels"] <= 2
    assert layers["point-labels"]["sizeUnits"] == "pixels"
    assert layers["point-labels"]["sizeMaxPixels"] == 11


def test_labels_can_be_hidden_without_losing_selected_infrastructure():
    network,boundary,_=page.assets()
    spec=json.loads(deck(network,boundary,network.infrastructure,"INET_BP_65",show_labels=False).to_json())
    labels=next(r for r in spec["layers"] if r["id"] == "point-labels")
    assert [r["infra_id"] for r in labels["data"]] == ["INET_BP_65"]
    assert len(next(r for r in spec["layers"] if r["id"] == "infrastructure-points")["data"]) == 293


def test_map_filters_detail_period_empty_selection_and_reset_are_offline(monkeypatch):
    offline(monkeypatch)
    app=AppTest.from_string(SCRIPT,default_timeout=30).run()
    assert not app.exception and len(app.get("deck_gl_json_chart")) == 1
    assert app.selectbox(key="net_infrastructure").value == "INET_BP_65"
    assert "GWh/d" in app.metric[0].value
    app.multiselect(key="net_layers").set_value(["lng"]).run()
    app.selectbox(key="net_infrastructure").set_value("it-lng-ravenna").run()
    assert not app.exception and app.subheader[0].value.startswith("Ravenna")
    app.multiselect(key="net_regions").set_value(["Toscana"]).run()
    assert app.selectbox(key="net_infrastructure").value == "INET_LG_33"
    app.toggle(key="net_events").set_value(True).run()
    assert not app.exception
    # Keep a real provider snapshot, unrelated imported evidence and GIE context.
    app.session_state[refresh.STATE]={"snapshots":{"preserved":page.assets()[2][0]}}
    app.session_state["unrelated_evidence"]={"sha":"preserve"}
    app.multiselect(key="net_layers").set_value(["production"]).run()
    assert not app.exception and app.selectbox(key="net_infrastructure").value is None
    assert any("Nessuna infrastruttura" in i.value for i in app.info)
    assert not any("0/0 ingressi" in h.proto.body for h in app.get("html"))
    app.button(key="net_reset").click().run()
    assert not app.exception and app.selectbox(key="net_infrastructure").value == "INET_BP_65"
    assert "preserved" in app.session_state[refresh.STATE]["snapshots"]
    assert app.session_state["unrelated_evidence"]["sha"] == "preserve"
    app.date_input(key="net_period").set_value((DAY-timedelta(days=2),DAY)).run()
    assert not app.exception and len(app.get("plotly_chart")) == 1


def test_native_pick_changes_detail_and_stale_foreign_pick_is_ignored(monkeypatch):
    offline(monkeypatch)
    original=page.st.pydeck_chart
    events=[]
    def native(*a,**kw):
        assert kw["on_select"] == "rerun" and kw["selection_mode"] == "single-object"
        default=original(*a,**kw)
        return events.pop(0) if events else default
    monkeypatch.setattr(page.st,"pydeck_chart",native)
    app=AppTest.from_string(SCRIPT,default_timeout=30).run()
    events.append({"selection":{"objects":{"infrastructure-points":[{"infra_id":"it-lng-piombino"}]}}})
    app.run()
    assert not app.exception and app.selectbox(key="net_infrastructure").value == "it-lng-piombino"
    events.append({"selection":{"objects":{"infrastructure-points":[{"infra_id":"foreign-id"}]}}})
    app.run()
    assert not app.exception and app.selectbox(key="net_infrastructure").value == "it-lng-piombino"


def test_gie_facility_and_national_context_remain_separate_and_units_explicit(monkeypatch):
    offline(monkeypatch)
    network,boundary,snapshots=page.assets()
    binding=next(b for b in network.bindings if b.provider == "ALSI")
    result={"frame":pd.DataFrame([{"gas_day":DAY,"status":"C","inventory_1000m3_lng":15.0,
        "inventory_gwh":None,"sendout_gwh_d":20.0,"dtrs_gwh_d":40.0}]),"acquired":NOW,
        "cached":False,"failed":False,"source":"GIE ALSI","source_url":"https://alsi.gie.eu/"}
    app=AppTest.from_string(SCRIPT,default_timeout=30)
    app.session_state[refresh.STATE]={"facilities":{("ALSI",binding.external_id):result}}
    app.session_state["net_infrastructure"]=binding.infrastructure_id
    app.session_state["AGSI+_IT"]={"result":{**result,"frame":pd.DataFrame([{
        "gas_day":DAY,"stock_twh":123.4,"fill_pct":80.0}])}}
    app.run()
    assert not app.exception
    assert any("singolo impianto" in m.value for m in app.markdown)
    assert any("indipendente dai filtri" in c.value for c in app.caption)
    app.selectbox(key="net_infrastructure").set_value("INET_BP_65").run()
    assert not app.exception and not any("singolo impianto" in m.value for m in app.markdown)
    assert any("123,40 TWh" in c.value for c in app.caption)


def test_refresh_provider_failures_are_independent_preserve_previous_and_throttle(monkeypatch):
    network,boundary,snapshots=page.assets()
    binding=next(b for b in network.bindings if b.provider == "ENTSOG" and b.external_id == "LNG-00015")
    snapshot=next(s for s in snapshots if s.point_direction == binding.point_direction)
    called=[]
    def catalog(*a,**kw):
        called.append("catalog")
        raise SourceUnavailable("Synthetic failure")
    def unavailable(*a,**kw):raise SourceUnavailable("Synthetic failure")
    monkeypatch.setattr(refresh,"load_catalog",catalog)
    monkeypatch.setattr(refresh,"load_point",lambda *a,**kw:replace(snapshot,acquired=NOW+timedelta(minutes=1)))
    monkeypatch.setattr(refresh,"load_interruptions",unavailable)
    monkeypatch.setattr(refresh,"load_facility",unavailable)
    monkeypatch.setattr(refresh,"load_agsi",unavailable)
    monkeypatch.setattr(refresh,"load_iip",lambda *a,**kw:{"failed":False,"messages":[],"acquired":NOW})
    previous={"source":"synthetic prior GIE fixture"}
    state={"AGSI+_IT":{"result":previous},"preserved":"evidence"}
    notices=refresh.refresh_network(state,None,network,binding.infrastructure_id,"entry",DAY,DAY,NOW,api_key="synthetic-key")
    saved=state[refresh.STATE]
    assert saved["snapshots"] and state["AGSI+_IT"]["result"] == previous and state["gie_iip"]["result"]["messages"] == []
    assert state["preserved"] == "evidence" and saved["failures"]
    assert "synthetic-key" not in repr(state) and any("non aggiornati" in n for n in notices)
    refresh.refresh_network(state,None,network,binding.infrastructure_id,"entry",DAY,DAY,NOW+timedelta(seconds=30))
    assert called == ["catalog"]


def test_refresh_refuses_changed_or_unknown_catalog_identity(monkeypatch):
    network,_,_=page.assets()
    rows=[dict(r,pointLabel="changed") for r in network.sources["opd"]["rows"]]
    monkeypatch.setattr(refresh,"load_catalog",lambda *a,**kw:{"rows":rows,"failed":False})
    def forbidden(*a,**kw):raise AssertionError("Unverified identity must not trigger operational requests")
    monkeypatch.setattr(refresh,"load_point",forbidden)
    state={}
    notices=refresh.refresh_network(state,None,network,"INET_BP_65","entry",DAY,DAY,NOW)
    assert any("da verificare" in n for n in notices)
    assert not state[refresh.STATE].get("snapshots")


def test_later_refresh_clears_only_failures_of_sources_that_recovered(monkeypatch):
    network,_,snapshots=page.assets()
    snapshot=next(s for s in snapshots if "ITP-00093" in s.point_direction)
    point=snapshot.point_direction
    state={refresh.STATE:{"attempted":NOW-timedelta(minutes=2),"failures":{
        "catalog":NOW,"interruptions:"+point:NOW,point:NOW,"unrelated-provider":NOW}}}
    monkeypatch.setattr(refresh,"load_catalog",lambda *a,**kw:{"rows":network.sources["opd"]["rows"],"failed":False})
    monkeypatch.setattr(refresh,"load_point",lambda *a,**kw:snapshot)
    monkeypatch.setattr(refresh,"load_interruptions",lambda *a,**kw:{"failed":False,"records":()})
    refresh.refresh_network(state,None,network,"INET_BP_65","entry",DAY,DAY,NOW)
    assert set(state[refresh.STATE]["failures"]) == {"unrelated-provider"}


def test_export_contains_only_selected_real_ids_with_dates_units_and_provenance():
    network,_,snapshots=page.assets()
    visible=tuple(i for i in network.infrastructure if i.id == "INET_BP_65")
    records=page.merge_observations(snapshots)
    payload=json.loads(page.export(network,visible,records,(),DAY,DAY))
    assert {i["id"] for i in payload["infrastructure"]} == {"INET_BP_65"}
    assert all(o["infrastructure_id"] == "INET_BP_65" and o["unit"] == "GWh/d" and o["license"]
               and o["retrieved_at"] and o["quality_status"] for o in payload["observations"])
    assert payload["first_gas_day"] == str(DAY)
