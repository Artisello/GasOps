"""Read-only public cockpit and strictly separate authorized portfolio routes."""
from datetime import date,datetime,timezone
from pathlib import Path

import pytest
import requests
from streamlit.testing.v1 import AppTest

from gasops_app import balancing_cockpit_page as page,session
from gasops_app.operations_ledger import sample_rows
from gasops_app.settlement_desk import merge_csv,archive_csv

ROOT=Path(__file__).resolve().parents[1]
NOW=datetime(2026,11,23,12,tzinfo=timezone.utc)
SCRIPT="from gasops_app.workbench import balancing\nbalancing()"


@pytest.fixture
def offline(monkeypatch,tmp_path):
    monkeypatch.setenv("GASOPS_STATE_DIR",str(tmp_path))
    monkeypatch.setattr(page,"utc_now",lambda:NOW)
    monkeypatch.setattr(session,"_configuration",lambda:None)
    def forbidden(*a,**kw):raise AssertionError("No fetch in the cockpit")
    monkeypatch.setattr(requests,"get",forbidden)
    monkeypatch.setattr(requests.Session,"request",forbidden)


def imported():
    return {**merge_csv(None,archive_csv(sample_rows()).encode(),acquired=NOW),
            "authorized":True,"origin":"user_upload","name":"synthetic-test-upload.csv"}


def test_default_public_view_is_gas_day_first_and_not_an_official_balance(offline):
    app=AppTest.from_string(SCRIPT,default_timeout=30).run()
    assert not app.exception
    assert app.radio(key="balancing_view").value=="Cockpit"
    assert app.radio(key="cockpit_context").value=="SYSTEM VIEW"
    assert app.date_input(key="cockpit_day_system").value==date(2026,11,20)
    assert any("Estimated System Position" in c.value and "Nessun saldo ufficiale" in c.value for c in app.caption)
    assert any("Settlement" in e.proto.body and "Non disponibile" in e.proto.body for e in app.get("html"))
    assert len(app.get("plotly_chart"))==1
    assert not app.get("file_uploader")
    table=app.dataframe[0].value
    assert "Flusso fisico" in table and table["Flusso fisico"].notna().sum()==11


def test_day_filter_updates_reconciliation_provenance_and_audit_together(offline,monkeypatch):
    frames=[]
    original=page.attributed_csv
    def record(result,**kw):
        frames.append(result["frame"].copy())
        return original(result,**kw)
    monkeypatch.setattr(page,"attributed_csv",record)
    app=AppTest.from_string(SCRIPT,default_timeout=30).run()
    frames.clear()
    app.date_input(key="cockpit_day_system").set_value(date(2026,11,18)).run()
    assert not app.exception and frames
    assert all(set(f.gas_day)=={date(2026,11,18)} for f in frames if "gas_day" in f)
    app.radio(key="cockpit_readout").set_value("Pubblicazioni").run()
    assert not app.exception and not app.get("plotly_chart")
    assert set(app.dataframe[0].value.gas_day)=={date(2026,11,18)}
    app.date_input(key="cockpit_day_system").set_value(date(2026,11,21)).run()
    assert any("Nessuna pubblicazione" in c.value for c in app.caption)
    app.radio(key="cockpit_readout").set_value("Riconciliazione").run()
    assert not app.exception
    assert app.dataframe[0].value["Flusso fisico"].isna().all()
    assert not app.get("plotly_chart")


def test_empty_shipper_context_never_uses_demo_or_public_inputs(offline,monkeypatch):
    app=AppTest.from_string(SCRIPT,default_timeout=30)
    app.session_state["daily_desk_demo"]=True
    app.session_state["daily_desk_data_mode"]="Esempio guidato"
    app.run()
    monkeypatch.setattr(page,"assets",lambda:(_ for _ in ()).throw(AssertionError("Portfolio must not read public sources")))
    app.radio(key="cockpit_context").set_value("PORTFOLIO / SHIPPER VIEW").run()
    assert not app.exception and app.metric[0].value=="Non calcolabile"
    assert not app.dataframe and not app.get("plotly_chart")
    app.button(key="cockpit_import").click().run()
    assert not app.exception
    assert app.radio(key="balancing_view").value=="Controllo giornaliero"
    assert app.radio(key="daily_desk_data_mode").value=="Dati importati"


def test_authorized_portfolio_and_drilldown_reuse_existing_settlement(offline):
    app=AppTest.from_string(SCRIPT,default_timeout=30)
    app.session_state["settlement_desk_csv_v1"]=imported()
    app.session_state["cockpit_context"]="PORTFOLIO / SHIPPER VIEW"
    app.run()
    assert not app.exception
    assert app.selectbox(key="cockpit_shipper").value=="DEMO-001"
    assert app.date_input(key="cockpit_day_portfolio").value==date(2026,9,30)
    audit=app.dataframe[0].value
    assert audit.publication_timestamp.isna().all() and audit.point_direction.isna().all()
    app.date_input(key="cockpit_day_portfolio").set_value(date(2026,9,5)).run()
    assert not app.exception
    assert set(app.dataframe[0].value.gas_day)=={date(2026,9,5)}
    app.button(key="cockpit_settlement").click().run()
    assert not app.exception
    assert app.radio(key="balancing_view").value=="Controllo giornaliero"
    assert app.radio(key="daily_desk_data_mode").value=="Dati importati"
    assert app.radio(key="daily_desk_section").value=="Giornata"
    assert app.session_state["daily_desk_day"]=="2026-09-05"
    assert app.session_state["settlement_desk_csv_v1"]["sha"]==imported()["sha"]


@pytest.mark.parametrize("mode",["demo","workbench"])
def test_real_route_keeps_legacy_controls_and_opens_the_same_map_point(offline,monkeypatch,mode):
    monkeypatch.setenv("GASOPS_APP_MODE",mode)
    app=AppTest.from_file(ROOT/"app.py",default_timeout=30)
    app.session_state["balancing_view"]="Cockpit"
    # Existing intent routes to the same page before native navigation.
    app.session_state["bso_workspace_intent"]="balancing"
    app.run()
    links={e.proto.page:e.proto.page_script_hash for e in app.get("page_link")}
    app._page_hash=links["balancing"]
    app.run()
    assert not app.exception and app.radio(key="balancing_view").value=="Cockpit"
    point=app.selectbox(key="cockpit_point").value
    app.button(key="cockpit_map").click().run()
    assert not app.exception and app.radio(key="operational_platform").value=="MAP"
    assert app.session_state["net_direction"]==("exit" if point.endswith("exit") else "entry")


def test_legacy_import_without_recorded_authorization_is_not_a_portfolio(offline):
    app=AppTest.from_string(SCRIPT,default_timeout=30)
    saved=imported();saved.pop("authorized")
    app.session_state["settlement_desk_csv_v1"]=saved
    app.session_state["cockpit_context"]="PORTFOLIO / SHIPPER VIEW"
    app.run()
    assert not app.exception and app.metric[0].value=="Non calcolabile"
    assert not app.dataframe


def test_cockpit_displays_structural_type_and_separate_directions(offline):
    app=AppTest.from_string(SCRIPT,default_timeout=30).run()
    assert not app.exception
    table=app.dataframe[0].value
    gries=table.loc[table.Punto=="Passo Gries"]
    assert set(gries.Tipologia)=={"↔ Bidirezionale"}
    assert set(gries["Direzione dati"])=={"↘ Ingresso","↗ Uscita"}
    assert set(table.loc[table.Punto=="Bizzarone","Tipologia"])=={"↗ Solo uscita"}
    app.selectbox(key="cockpit_point").set_value("IT-TSO-0001ITP-00136entry").run()
    assert not app.exception
    assert any("igor-flow-pair" in e.proto.body and "↘ Ingresso" in e.proto.body and "↗ Uscita" in e.proto.body for e in app.get("html"))
    app.selectbox(key="cockpit_point").set_value("IT-TSO-0001ITP-00136exit").run()
    assert not app.exception
    assert any("↔ Bidirezionale" in e.proto.body and "↗ Uscita" in e.proto.body for e in app.get("html"))
