"""Offline overview/navigation tests; synthetic payloads only for click fixtures."""
from pathlib import Path
from datetime import date,datetime,timezone
import json
import pandas as pd

import pytest
import requests
from streamlit.testing.v1 import AppTest

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
    app=AppTest.from_file(ROOT/"app.py",default_timeout=30).run()
    assert not app.exception and app.title[0].value == "Sistema gas italiano"
    assert len(app.get("deck_gl_json_chart")) == 1 and calls[0]["height"] == 500
    assert "overview" in calls[0]["key"] and callable(calls[0]["on_select"])
    assert app.button(key="net_overview_open").label == "Esplora la rete"
    assert not any(w.key == "net_layers" for w in app.multiselect)
    assert not any(b.key == "net_refresh" for b in app.button)
    assert any("Copertura parziale" in c.value for c in app.caption)
    assert any("Storico" in h.proto.body and "giorno gas" in h.proto.body for h in app.get("html"))
    assert any("SciGRID 2021" in c.value for c in app.caption)
    if mode == "demo":
        assert any("simulazioni" in s.value for s in app.subheader)
        assert len(app.get("plotly_chart")) == 2  # point history plus the preserved BSO case
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
    assert target["lineWidthMinPixels"] == target["lineWidthMaxPixels"] == 12
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
    app=AppTest.from_string("from gasops_app.italian_network_page import panel\npanel()",default_timeout=30).run()
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
        "acquired":datetime(2026,11,21,tzinfo=timezone.utc),"failed":True}}
    app.run()
    assert not app.exception
    grid=next(h.proto.body for h in app.get("html") if 'class="gas-kpi-grid"' in h.proto.body)
    assert grid.count('class="gas-kpi"') == 4
    assert "19 nov 2026" in grid and "ultima copia valida" in grid
    assert any("GIE AGSI+" in c.value and "aggregato nazionale distinto" in c.value for c in app.caption)


def test_crowded_labels_are_decluttered_without_moving_the_markers():
    rows=[{"infra_id":str(i),"label":"Synthetic label "+str(i),"position":[10,44]} for i in range(10)]
    result=label_layout(rows)
    assert 1 <= len(result) <= 4
    assert result[0]["infra_id"] == "0"  # selected label has priority
    assert all(r["position"] == [10,44] for r in result)


def test_overview_exposes_same_operational_history_and_keeps_missing_values_missing(monkeypatch,tmp_path):
    offline(monkeypatch,tmp_path)
    app=AppTest.from_string("from gasops_app.italian_network_page import panel\npanel(mode='overview')",default_timeout=30).run()
    assert not app.exception
    assert [t.label for t in app.tabs] == ["Dati","Storico"]
    assert app.selectbox(key="net_overview_indicator").value == "Physical Flow"
    assert "Nomination" in app.selectbox(key="net_overview_indicator").options or "Nomina" in app.selectbox(key="net_overview_indicator").options
    app.selectbox(key="net_overview_indicator").set_value("Nomination").run()
    assert not app.exception and len(app.get("plotly_chart")) == 1
    assert any("Capacità tecnica" in h.proto.body and "Rinomina" in h.proto.body for h in app.get("html"))
    app.session_state[view.SELECTED]="INET_PL_5"
    app.run()
    assert not app.exception and not app.tabs and not app.get("plotly_chart")
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
