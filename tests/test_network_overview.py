"""Offline overview/navigation tests; synthetic payloads only for click fixtures."""
from pathlib import Path
from datetime import date,datetime,timezone
import json
import pandas as pd

import pytest
import requests
from streamlit.testing.v1 import AppTest

from gasops_app.system_status_page import ARCHIVE_KEY
from gasops_app import italian_network_page as view, session
from gasops_app.italian_network_map import deck, label_layout

ROOT=Path(__file__).resolve().parents[1]


def offline(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setattr(session,"_configuration",lambda:None)
    def forbidden(*a,**kw):raise AssertionError("No automatic source requests from the overview")
    monkeypatch.setattr(requests.Session,"request",forbidden)
    monkeypatch.setattr(requests,"get",forbidden)


@pytest.mark.parametrize("mode",["demo","workbench"])
def test_both_home_modes_open_map_and_side_panel_without_api_calls(monkeypatch,tmp_path,mode):
    offline(monkeypatch,tmp_path)
    monkeypatch.setenv("GASOPS_APP_MODE",mode)
    calls=[]
    original=view.st.pydeck_chart
    def capture(*a,**kw):
        calls.append(kw)
        return original(*a,**kw)
    monkeypatch.setattr(view.st,"pydeck_chart",capture)
    app=AppTest.from_file(ROOT/"app.py",default_timeout=30)
    app.session_state[ARCHIVE_KEY] = True
    app.run()
    assert not app.exception and app.title[0].value == "I.G.O.R. — Sistema Gas Italiano"
    assert len(app.get("deck_gl_json_chart")) == 1 and calls[0]["height"] == 500
    assert "overview" in calls[0]["key"] and callable(calls[0]["on_select"])
    assert app.button(key="net_overview_open").label == "Esplora la rete"
    assert not any(w.key == "net_layers" for w in app.multiselect)
    assert not any(b.key == "net_refresh" for b in app.button)
    assert any("componenti" in c.value and "/9" in c.value for c in app.caption)
    assert any("Giorno gas storico" in h.proto.body for h in app.get("html"))
    assert any("SciGRID 2021" in c.value for c in app.caption)
    if mode == "demo":
        assert any("simulati" in s.value for s in app.caption)
        assert len(app.get("plotly_chart")) == 1
    else:
        assert app.button(key="workspace_open_balancing")


@pytest.mark.parametrize("mode",["demo","workbench"])
def test_explore_opens_the_same_pipeline_and_clears_only_conflicting_filters(monkeypatch,tmp_path,mode):
    offline(monkeypatch,tmp_path)
    monkeypatch.setenv("GASOPS_APP_MODE",mode)
    app=AppTest.from_file(ROOT/"app.py",default_timeout=30)
    app.session_state[view.SELECTED]="INET_PL_5"
    app.session_state["net_layers"]=["lng"]
    app.session_state["net_regions"]=["Veneto"]
    app.session_state["unrelated_evidence"]={"sha":"keep"}
    app.run()
    app.button(key="net_overview_open").click().run()
    assert not app.exception
    assert app.radio(key="operational_platform").value == "MAP"
    assert app.selectbox(key="net_infrastructure").value == "INET_PL_5"
    assert "pipeline" in app.multiselect(key="net_layers").value
    assert app.multiselect(key="net_regions").value == []
    assert app.session_state["unrelated_evidence"] == {"sha":"keep"}
    links={l.proto.page:l.proto.page_script_hash for l in app.get("page_link")}
    app._page_hash=links[""]
    app.run()
    assert not app.exception and app.session_state[view.SELECTED] == "INET_PL_5"


def test_native_pipeline_callback_reads_geometry_identity_and_rejects_stale_picks(monkeypatch):
    event={"selection":{"objects":{"pipeline-hit-targets":[{"properties":{"infra_id":"INET_PL_5"}}]}}}
    state={"chart":event}
    monkeypatch.setattr(view.st,"session_state",state)
    view._accept_pick("chart",("INET_PL_5",),"overview")
    assert state[view.SELECTED] == "INET_PL_5" and "net_pending_selection" not in state
    view._accept_pick("chart",("INET_PL_5",),"full")
    assert state["net_pending_selection"] == "INET_PL_5"
    state["chart"]={"selection":{"objects":{"pipeline-hit-targets":[{"properties":{"infra_id":"foreign"}}]}}}
    view._accept_pick("chart",("INET_PL_5",),"overview")
    assert state[view.SELECTED] == "INET_PL_5"


def test_pipeline_mouse_targets_are_wider_without_changing_source_geometry():
    network,boundary,_=view.assets()
    visible=tuple(i for i in network.infrastructure if i.category == "pipeline")
    spec=json.loads(deck(network,boundary,visible,"INET_PL_5").to_json())
    layers={l["id"]:l for l in spec["layers"]}
    target=layers["pipeline-hit-targets"]
    assert target["pickable"] and target["lineWidthUnits"] == "pixels"
    assert target["lineWidthMinPixels"] == target["lineWidthMaxPixels"] == 18
    assert target["getLineColor"][3] == 1
    assert target["data"] == layers["historical-links"]["data"]
    assert not layers["historical-links"]["pickable"]
    assert layers["selected-link"]["data"]["features"][0]["properties"]["infra_id"] == "INET_PL_5"


def test_overview_and_full_have_independent_keys_and_read_assets_once(monkeypatch,tmp_path):
    offline(monkeypatch,tmp_path)
    view.assets.clear()
    calls=[]
    original=view.load_network_assets
    def load():
        calls.append(True)
        return original()
    monkeypatch.setattr(view,"load_network_assets",load)
    app=AppTest.from_string("from gasops_app.italian_network_page import panel\npanel(mode='overview')\npanel()",default_timeout=30).run()
    assert not app.exception and len(app.get("deck_gl_json_chart")) == 2
    ids=[c.proto.id for c in app.get("deck_gl_json_chart")]
    assert len(set(ids)) == 2 and len(calls) == 1


def test_history_reserves_date_axis_space_and_uses_dark_theme(monkeypatch,tmp_path):
    offline(monkeypatch,tmp_path)
    figures=[]
    original=view.plot
    def plot(fig,**kw):
        figures.append(fig)
        original(fig,**kw)
    monkeypatch.setattr(view,"plot",plot)
    app=AppTest.from_string("from gasops_app.italian_network_page import panel\npanel()",default_timeout=30)
    app.session_state[ARCHIVE_KEY] = True
    app.run()
    assert not app.exception
    fig=figures[0]
    assert fig.layout.margin.b >= 50 and fig.layout.xaxis.automargin
    assert fig.layout.xaxis.tickformat == "%d/%m" and fig.layout.xaxis.nticks <= 4
    assert fig.layout.template.layout.paper_bgcolor != "white"


def test_overview_missing_assets_is_a_readable_state_not_fabricated_data(monkeypatch,tmp_path):
    offline(monkeypatch,tmp_path)
    def unavailable():raise OSError("Synthetic fixture: missing offline file")
    monkeypatch.setattr(view,"assets",unavailable)
    app=AppTest.from_string("from gasops_app.italian_network_page import panel\npanel(mode='overview')",default_timeout=30).run()
    assert not app.exception and app.info and not app.get("deck_gl_json_chart")


def test_overview_limits_kpis_and_retains_gie_date_and_failed_refresh_state(monkeypatch,tmp_path):
    offline(monkeypatch,tmp_path)
    app=AppTest.from_string("from gasops_app.italian_network_page import panel\npanel(mode='overview')",default_timeout=30)
    # Synthetic GIE state, deliberately one day older than the ENTSOG extract.
    app.session_state["AGSI+_IT"]={"result":{"frame":pd.DataFrame([{"gas_day":date(2026,11,19),"stock_twh":123.4}]),
        "acquired":datetime(2026,11,21,tzinfo=timezone.utc),"failed":True,"scope":"IT"}}
    app.run()
    assert not app.exception
    grid=next(h.proto.body for h in app.get("html") if 'class="gas-kpi-grid"' in h.proto.body)
    assert grid.count('class="gas-kpi"') + grid.count('class="gas-kpi gas-kpi-missing"') == 4
    assert "19 nov 2026" in grid and "ultima copia valida" in grid
    assert "GIE AGSI+" in grid


def test_crowded_labels_are_decluttered_without_moving_the_markers():
    rows=[{"infra_id":str(i),"label":"Synthetic label "+str(i),"position":[10,44]} for i in range(10)]
    result=label_layout(rows)
    assert 1 <= len(result) <= 4
    assert result[0]["infra_id"] == "0"  # selected label has priority
    assert all(r["position"] == [10,44] for r in result)


def test_overview_exposes_same_operational_history_and_keeps_missing_values_missing(monkeypatch,tmp_path):
    offline(monkeypatch,tmp_path)
    app=AppTest.from_string("from gasops_app.italian_network_page import panel\npanel(mode='overview')",default_timeout=30)
    app.session_state[ARCHIVE_KEY] = True
    app.run()
    assert not app.exception
    assert [t.label for t in app.tabs] == ["Dati","Storico","Eventi","Fonti"]
    assert app.selectbox(key="net_overview_indicator").value == "Physical Flow"
    assert "Nomination" in app.selectbox(key="net_overview_indicator").options or "Nomina" in app.selectbox(key="net_overview_indicator").options
    app.selectbox(key="net_overview_indicator").set_value("Nomination").run()
    assert not app.exception and len(app.get("plotly_chart")) == 1
    commercial=next(d.value for d in app.dataframe if "Periodo e validità" in d.value.columns)
    assert "Capacità tecnica firm" in set(commercial.Indicatore) and "Rinomina" in set(commercial.Indicatore)
    app.session_state[view.SELECTED]="INET_PL_5"
    app.run()
    assert not app.exception and not app.get("plotly_chart")
    assert [t.label for t in app.tabs] == ["Dati","Storico","Eventi","Fonti"]
    assert any("nessuna misura di flusso sul segmento" in c.value for c in app.caption)


def test_view_reset_preserves_selection_and_separates_overview_from_full(monkeypatch):
    state={view.SELECTED:"INET_BP_89","net_view_epoch_full":2,"unrelated_evidence":{"keep":True}}
    monkeypatch.setattr(view.st,"session_state",state)
    view._reset_view("overview")
    assert state[view.SELECTED] == "INET_BP_89" and state["net_view_epoch_overview"] == 1
    assert state["net_view_epoch_full"] == 2 and state["unrelated_evidence"] == {"keep":True}


def test_overview_direction_is_consistent_in_tooltip_detail_and_navigation(monkeypatch,tmp_path):
    offline(monkeypatch,tmp_path)
    monkeypatch.delenv("GASOPS_APP_MODE",raising=False)
    tooltips=[]
    original=view.deck
    def capture(*a,**kw):
        scene=original(*a,**kw)
        spec=json.loads(scene.to_json())
        layer=next(r for r in spec["layers"] if r["id"] == "infrastructure-points")
        tooltips.append(next(r["safe_value"] for r in layer["data"] if r["infra_id"] == "INET_BP_89"))
        return scene
    monkeypatch.setattr(view,"deck",capture)
    app=AppTest.from_file(ROOT/"app.py",default_timeout=30)
    app.session_state[view.SELECTED]="INET_BP_89"
    app.run()
    assert not app.exception and "ingresso" in tooltips[-1]
    app.radio(key="net_overview_direction").set_value("exit").run()
    assert not app.exception and "ingresso" not in tooltips[-1]
    app.button(key="net_overview_open").click().run()
    assert not app.exception and app.selectbox(key="net_direction").value == "exit"


@pytest.mark.parametrize("mode", ["overview", "full"])
def test_attention_pick_opens_events_and_other_modes_open_data(monkeypatch, mode):
    event = {"selection":{"objects":{"infrastructure-points":[{"infra_id":"INET_BP_65"}]}}}
    key = view._detail_tab_key(mode)
    state = {view.READING:"ATTENTION", key:"Storico"}
    monkeypatch.setattr(view.st, "session_state", state)
    view._accept_pick("chart", ("INET_BP_65",), mode, event)
    assert state[view.SELECTED] == "INET_BP_65"
    assert state[key] == "Eventi"
    state[key] = "Fonti"
    view._accept_pick("chart", ("foreign",), mode, event)
    assert state[key] == "Fonti"
    state[view.READING] = "FLOW"
    view._accept_pick("chart", ("INET_BP_65",), mode, event)
    assert state[key] == "Dati"


def test_overview_attention_tab_and_compact_event_evidence(monkeypatch, tmp_path):
    offline(monkeypatch,tmp_path)
    app = AppTest.from_string("""
import streamlit as st
from types import SimpleNamespace
from decimal import Decimal
from gasops_app.italian_network_page import _accept_pick, _point_events, _detail_tab_key, DETAIL_TABS, READING
from gasops_app.system_status import Attention
st.session_state.setdefault(READING, "ATTENTION")
_accept_pick("chart", ("point",), "overview", {"selection":{"objects":{"infrastructure-points":[{"infra_id":"point"}]}}})
tabs = st.tabs(list(DETAIL_TABS), key=_detail_tab_key("overview"), on_change="rerun")
with tabs[2]:
    _point_events(SimpleNamespace(id="point"), {}, (), (
        Attention(id="id", category="deviation", severity="info",
                  description="Passo Gries · scarto dalla mediana di 28 giorni",
                  rule="historical_median_deviation", threshold=Decimal("30"),
                  observed_value=Decimal("53"), unit="%", source_id="ENTSOG:point",
                  observed_at=None, retrieved_at=None,
                  infrastructure_id="point", direction="entry",
                  evidence_ids=("raw-observation-1","raw-observation-2"),
                  baseline=Decimal("100"), baseline_n=28),
    ))
""", default_timeout=30).run()
    assert not app.exception
    assert app.session_state[view._detail_tab_key("overview")] == "Eventi"
    assert [t.label for t in app.tabs] == list(view.DETAIL_TABS)
    assert any("28 giorni validi" in c.value for c in app.caption)
    assert any("2 riferimenti" in c.value for c in app.caption)
    assert not any("raw-observation" in c.value for c in app.caption)
    assert any(e.label == "Evidenze tecniche e metodologia" for e in app.expander)
    assert list(app.dataframe[0].value["ID osservazione"]) == ["raw-observation-1", "raw-observation-2"]


def test_map_focus_and_reset_preserve_selection_and_other_layout(monkeypatch):
    state={view.SELECTED:"INET_BP_65","net_view_epoch_full":3,"net_period":("keep","keep")}
    monkeypatch.setattr(view.st,"session_state",state)
    view._focus_view("overview","INET_BP_65")
    assert state["net_camera_focus_overview"] == "INET_BP_65"
    assert state["net_view_epoch_overview"] == 1
    view._reset_view("overview")
    assert "net_camera_focus_overview" not in state
    assert state["net_view_epoch_overview"] == 2
    assert state[view.SELECTED] == "INET_BP_65" and state["net_view_epoch_full"] == 3
    assert state["net_period"] == ("keep","keep")


def test_map_focus_camera_uses_selected_geometry_and_allows_national_zoom():
    from gasops_app.italian_network_map import label_anchor
    network,boundary,_=view.assets()
    identifier="INET_BP_65"
    geometry=next(g.geometry for g in network.geography if g.infrastructure_id == identifier)
    national=json.loads(deck(network,boundary,network.infrastructure).to_json())["initialViewState"]
    spec=json.loads(deck(network,boundary,network.infrastructure,identifier,focus_id=identifier).to_json())
    camera=spec["initialViewState"]
    assert [camera["longitude"],camera["latitude"]] == label_anchor(geometry)
    assert camera["zoom"] > national["zoom"]
    assert camera["minZoom"] == national["minZoom"]
    assert camera["maxZoom"] == national["maxZoom"]


def test_flow_sizes_are_fixed_and_tooltips_are_compact():
    from gasops_app.italian_network_map import flow_icon_size
    from decimal import Decimal
    assert [flow_icon_size(Decimal(str(v))) for v in (0,1,100,101,500,501)] == [9,12,12,15,15,18]
    network,boundary,_=view.assets()
    scene=deck(network,boundary,network.infrastructure)
    tooltip=scene._tooltip  # PyDeck passes tooltip separately from the deck JSON.
    assert "{safe_summary}" in tooltip["html"]
    assert "{safe_value}" not in tooltip["html"]
    assert tooltip["style"]["maxWidth"] == "240px"
    assert tooltip["style"]["whiteSpace"] == "pre-line"


def test_gries_nearby_facilities_have_separate_selectable_identities():
    from gasops_app.italian_network_map import nearby_points
    network,_,_=view.assets()
    items=tuple(i for i in network.infrastructure if i.category in ("entry","compressor"))
    groups=nearby_points(network,items)
    assert "INET_CO_77" in groups["INET_BP_78"]
    assert "INET_BP_78" in groups["INET_CO_77"]
    assert "INET_CO_77" not in nearby_points(network,tuple(i for i in items if i.category=="entry")).get("INET_BP_78",())


@pytest.mark.parametrize("mode",["overview","full"])
def test_nearby_selection_updates_detail_identity(monkeypatch,mode):
    state={view.READING:"SYSTEM",view.SELECTED:"INET_BP_78"}
    monkeypatch.setattr(view.st,"session_state",state)
    view._select_related(mode,"INET_CO_77")
    assert state[view.SELECTED]=="INET_CO_77"
    assert state[view._detail_tab_key(mode)]=="Dati"
    if mode=="full":
        assert state["net_pending_selection"]=="INET_CO_77"


def test_attention_does_not_render_previous_normal_selection():
    network,boundary,_=view.assets()
    mazara="INET_BP_65"
    gries="INET_BP_78"
    info={mazara:{"binding":object(),"flow_available":True,"stale":False}}
    visible=view._reading_items(network.infrastructure,"ATTENTION",info,mazara,(),{gries})
    assert mazara not in {i.id for i in visible}
    assert gries in {i.id for i in visible}
    assert any(i.category=="pipeline" for i in visible)
    spec=json.loads(deck(network,boundary,visible,mazara,reading_mode="ATTENTION",finding_ids={gries},stable_picking=True).to_json())
    layers={l["id"]:l for l in spec["layers"]}
    assert "selected-point" not in layers
    assert not next(r for r in layers["infrastructure-points"]["data"] if r["infra_id"]==mazara)["active"]
    assert next(r for r in layers["infrastructure-points"]["data"] if r["infra_id"]==gries)["active"]
    assert mazara in {i.id for i in view._reading_items(network.infrastructure,"SYSTEM",info,mazara,(),{gries})}


def test_overview_nearby_button_can_open_compressor(monkeypatch,tmp_path):
    offline(monkeypatch,tmp_path)
    app=AppTest.from_string("from gasops_app.italian_network_page import panel\npanel(mode='overview')",default_timeout=30)
    app.session_state[ARCHIVE_KEY]=True
    app.session_state[view.SELECTED]="INET_BP_78"
    app.run()
    assert not app.exception
    button=app.button(key="net_nearby_overview_INET_CO_77")
    assert "Compressione" in button.label
    button.click().run()
    assert not app.exception
    assert app.session_state[view.SELECTED]=="INET_CO_77"


@pytest.mark.parametrize("layout",["overview","full"])
def test_mode_switch_removes_previous_storage_and_resets_details(monkeypatch,tmp_path,layout):
    offline(monkeypatch,tmp_path)
    app=AppTest.from_string(f"from gasops_app.italian_network_page import panel\npanel(mode='{layout}')",default_timeout=30)
    app.session_state[ARCHIVE_KEY]=True
    app.session_state[view.SELECTED]="INET_SR_37"
    app.run()
    assert not app.exception
    assert app.session_state[view.SELECTED]=="INET_SR_37"
    widget="net_overview_infrastructure" if layout=="overview" else "net_infrastructure"
    for reading in ("FLOW","ATTENTION"):
        app.radio(key="net_reading_"+layout).set_value(reading).run()
        assert not app.exception
        assert app.session_state[view.SELECTED]!="INET_SR_37"
        assert app.selectbox(key=widget).value==app.session_state[view.SELECTED]
        assert app.session_state[view._detail_tab_key(layout)]==("Eventi" if reading=="ATTENTION" else "Dati")
        spec=json.loads(app.get("deck_gl_json_chart")[0].proto.json)
        points=next(l["data"] for l in spec["layers"] if l["id"]=="infrastructure-points")
        assert not next(r for r in points if r["infra_id"]=="INET_SR_37")["active"]
