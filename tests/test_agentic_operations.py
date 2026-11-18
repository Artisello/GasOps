from datetime import datetime,timezone,timedelta
from gasops_app.agentic_operations import scan,merge_cases,decide,handover
from gasops_app.bso_kpis import task_demo,balancing_demo
from gasops_app.operations_ledger import sample_rows
import json
import pytest

NOW=datetime(2026,11,18,13,tzinfo=timezone.utc)


def test_empty_is_not_success():
    rows,checks=scan(now=NOW,year=2026,month=11)
    assert rows==[]
    assert len(checks)==4
    assert all("non " in s for s in checks.values())


def test_deterministic_controls_and_human_review():
    kwargs=dict(now=NOW,year=2026,month=11,tasks=task_demo(),versions=balancing_demo(),mode="demo")
    p,checks=scan(**kwargs)
    assert sum(x.title=="Attività oltre termine" for x in p)==2
    assert sum(x.title=="Attività entro 24 ore" for x in p)==1
    assert sum(x.title=="Stima SAS non disponibile" for x in p)==1
    ledger=merge_cases([],p,NOW)
    row=ledger[0]
    with pytest.raises(ValueError):
        decide(row,"Verificato","test",NOW)
    changed=decide(row,"In revisione","Controllo manuale",NOW)
    with pytest.raises(ValueError):
        decide(changed,"Verificato","",NOW)
    ledger=[changed,*ledger[1:]]
    again,_=scan(**kwargs)
    assert merge_cases(ledger,again,NOW+timedelta(minutes=1))==ledger
    empty=merge_cases(ledger,[],NOW)
    assert empty==ledger
    payload=json.loads(handover(empty,set(),checks,"demo",NOW.isoformat()))
    assert not any(c["in_latest_scan"] for c in payload["cases"])
    assert payload["cases"][0]["status"]=="In revisione"


def test_settlement_revision_is_proposal_not_payment():
    p,_=scan(now=NOW,year=2026,month=9,balances=sample_rows(),participant="DEMO-001",mode="demo")
    assert len(p)==1 and p[0].title=="Rettifica da riconciliare"
    assert "4200" in p[0].evidence
    assert "DEMO-001" not in p[0].evidence


def test_agentic_demo_not_contaminating_session():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string("from gasops_app.bso_kpi_page import page\npage()",default_timeout=30).run()
    app.radio(key="bso_view").set_value("Centro operativo").run()
    assert not app.exception
    app.radio(key="agentic_mode").set_value("Demo sintetica").run()
    app.button(key="agentic_scan").click().run()
    assert not app.exception
    assert app.session_state["bso_agentic_v1_demo"]["cases"]
    app.radio(key="agentic_mode").set_value("Dati di sessione").run()
    assert not app.exception
    assert "bso_agentic_v1_session" not in app.session_state
    app.radio(key="bso_view").set_value("Panoramica").run()
    assert not app.exception
    assert next(t.value for t in app.dataframe if set(t.value.columns)=={"Area","KPI","Valore","Unità","Periodo","Copertura","Stato"})["Valore"].isna().all()
