from dataclasses import replace
from pathlib import Path

from streamlit.testing.v1 import AppTest

from gasops_app import dashboard, session, workspace
from gasops_app.operations_ledger import sample_rows
from gasops_app.settlement_desk import archive_csv, merge_csv

ROOT=Path(__file__).resolve().parents[1]


def test_home_requires_no_market_or_remote_request(monkeypatch):
    import requests
    def forbidden(*args,**kwargs):
        raise AssertionError("La scrivania iniziale non deve acquisire dati.")
    monkeypatch.setattr(dashboard,"source_filters",forbidden)
    monkeypatch.setattr(requests.Session,"request",forbidden)
    monkeypatch.setattr(session,"_configuration",lambda:None)
    app=AppTest.from_file(ROOT/"app.py",default_timeout=30).run()
    assert not app.exception and app.title[0].value=="Scrivania operativa"
    assert app.radio(key="overview_workspace").value=="Scrivania BSO"
    assert {b.key for b in app.button}>={"workspace_open_balancing","workspace_open_settlement",
                                      "workspace_open_operations","workspace_example"}
    assert "settlement_desk_csv_v1" not in app.session_state
    assert not any(b.key=="analysis_launch" for b in app.button)


def test_intent_opens_the_requested_scope_once_and_preserves_evidence(monkeypatch):
    evidence={"rows":sample_rows()}
    state={workspace.INTENT:"settlement_example","settlement_desk_csv_v1":evidence}
    monkeypatch.setattr(workspace.st,"session_state",state)
    workspace.apply_intent("kpi")
    assert workspace.INTENT in state
    workspace.apply_intent("balancing")
    assert workspace.INTENT not in state
    assert state["balancing_view"]=="Controllo giornaliero"
    assert state["daily_desk_data_mode"]=="Esempio guidato"
    state["balancing_view"]="Stato sistema"
    workspace.apply_intent("balancing")
    assert state["balancing_view"]=="Stato sistema"
    assert state["settlement_desk_csv_v1"] is evidence


def test_home_example_reaches_settlement_without_replacing_imports(monkeypatch):
    monkeypatch.setattr(session,"_configuration",lambda:None)
    rows=sample_rows()
    imported=merge_csv(None,archive_csv([*rows,replace(rows[1],version=3,withdrawn=rows[1].withdrawn+25)]).encode())
    saved={**imported,"name":"fixture.csv"}
    app=AppTest.from_file(ROOT/"app.py",default_timeout=30)
    app.session_state["settlement_desk_csv_v1"]=saved
    app.run()
    app.button(key="workspace_example").click().run()
    assert not app.exception
    assert app.radio(key="balancing_view").value=="Controllo giornaliero"
    assert app.radio(key="daily_desk_data_mode").value=="Esempio guidato"
    assert app.session_state["settlement_desk_csv_v1"]["sha"]==saved["sha"]
    assert any("57.000,00" in h.proto.body for h in app.get("html"))
    assert app.radio(key="daily_desk_filter").value=="Rettifiche"
    assert len(app.dataframe[0].value)==1
    app.radio(key="daily_desk_filter").set_value("Tutte").run()
    assert not app.exception and len(app.dataframe[0].value)==30
    app.radio(key="daily_desk_data_mode").set_value("Dati importati").run()
    assert not app.exception
    assert any("56.050,00" in h.proto.body for h in app.get("html"))
    assert len(app.session_state["settlement_desk_csv_v1"]["rows"])==61


def test_navigation_uses_the_operational_scope(monkeypatch):
    captured=[]
    monkeypatch.setattr(session,"_configuration",lambda:None)
    monkeypatch.setattr(workspace.st,"switch_page",lambda page:captured.append(page.url_path))
    app=AppTest.from_string("from gasops_app.workspace import render\nrender()").run()
    app.button(key="workspace_open_operations").click().run()
    assert not app.exception and captured==["kpi"]
    assert app.session_state[workspace.INTENT]=="operations"


def test_operations_intent_opens_the_task_register(monkeypatch):
    monkeypatch.setattr(session,"_configuration",lambda:None)
    app=AppTest.from_string("from gasops_app.bso_kpi_page import page\npage()",default_timeout=30)
    app.session_state[workspace.INTENT]="operations"
    app.run()
    assert not app.exception
    assert app.radio(key="bso_view").value=="Registro operativo"
    assert app.radio(key="bso_register_section").value=="Scadenze"
    assert app.radio(key="bso_mode").value=="Dati importati"
    assert workspace.INTENT not in app.session_state
