"""Public/default, explicit Demo, offline filters and reuse of both existing routes."""
from datetime import date,datetime,timezone
from decimal import Decimal as D
from pathlib import Path
import json

import pytest
import requests
from streamlit.testing.v1 import AppTest

from gasops_app import security_scenario_page as page,session,workbench
from gasops_app.data import synthetic
from gasops_app.italian_network_page import SELECTED,assets
from gasops_app.italian_network import security_entries
from gasops_app.italian_network_map import deck

NOW=datetime(2026,11,23,12,tzinfo=timezone.utc)
ROOT=Path(__file__).resolve().parents[1]
SCRIPT="from gasops_app.workbench import _scenario_panel\n_scenario_panel()"


@pytest.fixture
def offline(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setattr(page,"utc_now",lambda:NOW)
    monkeypatch.setattr(session,"_configuration",lambda:None)
    def forbidden(*args,**kwargs):raise AssertionError("Stress Test must not fetch providers")
    monkeypatch.setattr(requests,"get",forbidden)
    monkeypatch.setattr(requests.Session,"request",forbidden)
    configs=[]
    original=page.stress_configuration
    def capture(*a,**kw):
        config=original(*a,**kw);configs.append(config);return config
    monkeypatch.setattr(page,"stress_configuration",capture)
    return configs


def submit(app):
    next(b for b in app.button if b.label=="Calcola Stress Test").click().run()
    assert not app.exception


def test_public_is_partial_and_never_borrows_demo_or_private_data(offline):
    app=AppTest.from_string(SCRIPT,default_timeout=30)
    app.session_state["active_bundle"]=synthetic()
    app.session_state["settlement_desk_csv_v1"]={"rows":["PRIVATE"],"authorized":True}
    app.session_state["gie_api_key"]="SECRET-CREDENTIAL"
    app.run()
    assert not app.exception and offline[-1]["inputs"]["mode"]=="PUBLIC"
    assert app.radio(key="sos_mode").value=="Dati pubblici"
    assert offline[-1]["model_output"]["baseline"]["balance"] is None
    assert "demand" in offline[-1]["model_output"]["missing"]
    assert offline[-1]["model_output"]["baseline"]["entry_flow"] is not None
    assert offline[-1]["model_output"]["baseline"]["known_supply"]>0
    assert not any(i["quality"]=="demo" for i in offline[-1]["inputs"]["inputs"])
    raw=json.dumps(offline[-1],default=str)
    assert "PRIVATE" not in raw and "SECRET-CREDENTIAL" not in raw
    assert any(m.value=="Non calcolabile" for m in app.metric)
    assert any("Impatto topologico non determinabile" in c.value for c in app.caption)
    assert not app.get("file_uploader") and len(app.get("deck_gl_json_chart"))==1


@pytest.mark.parametrize("preset,percent",[("+5%",5),("+10%",10),("+20%",20)])
def test_explicit_demo_shocks_and_public_mode_isolation(offline,preset,percent):
    app=AppTest.from_string(SCRIPT,default_timeout=30).run()
    app.radio(key="sos_mode").set_value("Demo esplicita").run()
    scope="sos_demo_2026-11-20_OBSERVED"
    app.radio(key=scope+"_preset").set_value(preset).run()
    assert not app.exception
    config=offline[-1];result=config["model_output"]
    assert config["inputs"]["mode"]=="DEMO"
    assert all(i["classification"]=="ASSUMPTION" for i in config["inputs"]["inputs"])
    assert result["baseline"]["supply"]==900 and result["baseline"]["demand"]==880
    assert result["stress"]["demand"]==D(850)*(1+D(percent)/100)+30
    app.radio(key="sos_mode").set_value("Dati pubblici").run()
    assert not app.exception and offline[-1]["inputs"]["mode"]=="PUBLIC"
    assert offline[-1]["model_output"]["baseline"]["balance"] is None
    assert not offline[-1]["assumptions"]["input_assumptions"]


def test_combined_controls_export_and_day_specific_assumptions(offline):
    app=AppTest.from_string(SCRIPT,default_timeout=30).run()
    public="sos_public_2026-11-20_OBSERVED"
    app.number_input(key=public+"_input_production").set_value(0.)
    submit(app)
    assert offline[-1]["model_output"]["input_classes"]["production"]=="ASSUMPTION"
    app.date_input(key="sos_public_day").set_value(date(2026,11,19)).run()
    assert not app.exception and not offline[-1]["assumptions"]["input_assumptions"]
    app.radio(key="sos_mode").set_value("Demo esplicita").run()
    scope="sos_demo_2026-11-20_OBSERVED"
    app.checkbox(key=scope+"_outage").set_value(True)
    app.slider(key=scope+"_capacity").set_value(80)
    app.slider(key=scope+"_lng").set_value(50)
    app.number_input(key=scope+"_storage").set_value(25.)
    app.number_input(key=scope+"_cold").set_value(5.)
    submit(app)
    config=offline[-1]
    assert config["model_output"]["point_flow_loss"]==120
    assert config["model_output"]["stress"]["supply"]==595
    assert config["model_output"]["stress"]["balance"]==D("-463.50")
    assert config["calculation_parameters"]["outage"].startswith("dominates")
    assert any(b.label=="Scarica configurazione JSON" for b in app.get("download_button"))


def test_forecast_unavailable_is_not_replaced_with_an_observation(offline):
    app=AppTest.from_string(SCRIPT,default_timeout=30).run()
    app.radio(key="sos_demand_basis").set_value("FORECAST").run()
    assert not app.exception
    assert "demand" in offline[-1]["model_output"]["missing"]
    assert all(i["key"]!="demand" for i in offline[-1]["inputs"]["inputs"])


def test_map_overlay_is_an_assumption_not_a_documented_event(offline):
    network,boundary,_=assets();entries=security_entries(network)
    ids={b.infrastructure_id for b in entries};identifier=entries[0].infrastructure_id
    scene=deck(network,boundary,tuple(i for i in network.infrastructure if i.id in ids),identifier,
        mode="scenario",scenario_ids=(identifier,),day=date(2026,11,20),stable_picking=True)
    layers={layer.id:layer for layer in scene.layers}
    assert "scenario-assumptions" in layers and "event-rings" not in layers
    assert len(layers["scenario-assumptions"].data["features"])==1
    assert "ASSUMPTION" in layers["scenario-assumptions"].data["features"][0]["properties"]["safe_status"]
    assert not layers["scenario-assumptions"].pickable


def test_legacy_aggregate_requires_explicit_demo_and_keeps_its_calculation(offline,monkeypatch):
    app=AppTest.from_string(SCRIPT,default_timeout=30)
    app.session_state["scenario_model"]="Scenario aggregato esistente"
    original=workbench.fixture
    monkeypatch.setattr(workbench,"fixture",lambda:(_ for _ in ()).throw(AssertionError("No automatic fixture")))
    app.run()
    assert not app.exception and not app.get("plotly_chart")
    assert any("esplicitamente" in i.value for i in app.info)
    monkeypatch.setattr(workbench,"fixture",original)
    app.radio(key="scenario_aggregate_source").set_value("Demo · dati fittizi").run()
    assert not app.exception and len(app.get("plotly_chart"))==1


@pytest.mark.parametrize("mode",["demo","workbench"])
def test_real_navigation_preserves_selected_entry_and_returns_from_map(offline,monkeypatch,mode):
    monkeypatch.setenv("GASOPS_APP_MODE",mode)
    app=AppTest.from_file(ROOT/"app.py",default_timeout=30)
    app.session_state["balancing_view"]="Scenario di mercato"
    app.run()
    links={e.proto.page:e.proto.page_script_hash for e in app.get("page_link")}
    app._page_hash=links["balancing"];app.run()
    assert not app.exception
    point=security_entries(assets()[0])[-1].point_direction
    app.selectbox(key="sos_entry").set_value(point).run()
    identifier=app.session_state[SELECTED]
    app.button(key="sos_open_map").click().run()
    assert not app.exception and app.radio(key="operational_platform").value=="MAP"
    assert app.session_state[SELECTED]==identifier and app.session_state["net_direction"]=="entry"
    app.button(key="net_stress_full").click().run()
    assert not app.exception and app.radio(key="scenario_model").value=="Stress Test Italia"
    assert app.radio(key="sos_mode").value=="Dati pubblici" and app.session_state[SELECTED]==identifier
