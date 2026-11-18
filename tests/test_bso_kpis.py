from datetime import date,datetime,timedelta,timezone
from decimal import Decimal as D
from dataclasses import replace

import pandas as pd
import pytest

from gasops_app.data import ROME
from gasops_app.bso_kpis import (task_demo,task_template,parse_tasks,operations_metrics,
                                balancing_metrics,closed_gas_day,settlement_metrics)
from gasops_app.operations_ledger import sample_rows

NOW=datetime(2026,11,18,14,tzinfo=ROME)


def test_deadlines_backlog_and_fixed_denominator():
    tasks=parse_tasks(task_template().encode())
    assert tasks==task_demo()
    result=operations_metrics(tasks,NOW,2026,11)
    assert result["due"]==5 and result["on_time"]==3 and result["on_time_pct"]==60
    assert {x["task_id"] for x in result["overdue"]}=={"DEMO-04","DEMO-08"}
    assert result["next24"]==1 and result["next7"]==3
    assert operations_metrics(tasks,NOW,2026,12)["on_time_pct"] is None
    assert len(operations_metrics(tasks,NOW,2026,11,"settlement")["overdue"])==1


def test_timed_and_day_only_deadlines():
    raw=("task_id,area,activity,due_at,completed_at\n"
         "A,operations,Task A,2026-11-18,2026-11-18\n"
         "B,operations,Task B,2026-11-18T14:00+01:00,2026-11-18T13:00Z\n"
         "C,operations,Task C,2026-11-18T13:00+01:00,2026-11-19T12:00+01:00\n"
         "D,operations,Task D,2026-11-18,\n").encode()
    tasks=parse_tasks(raw)
    r=operations_metrics(tasks,NOW,2026,11)
    assert r["due"]==1 and r["on_time"]==0
    assert len(r["overdue"])==1
    r=operations_metrics(tasks,NOW+timedelta(days=1),2026,11)
    assert r["due"]==4 and r["on_time"]==2 and r["late"]==1
    assert len(r["overdue"])==1
    with pytest.raises(ValueError):
        parse_tasks(raw.replace(b"2026-11-18T13:00Z",b"2026-11-18"))
    with pytest.raises(ValueError):
        parse_tasks(raw.replace(b"Task A",b"=1+2"))


def test_balancing_uses_closed_days_no_filling_and_no_future_publications():
    frame=pd.DataFrame([
        {"gas_day":date(2026,11,16),"published_at":datetime(2026,11,16,8,tzinfo=ROME),"sas_gwh":10},
        {"gas_day":date(2026,11,16),"published_at":datetime(2026,11,16,18,tzinfo=ROME),"sas_gwh":-20},
        {"gas_day":date(2026,11,17),"published_at":datetime(2026,11,17,18,tzinfo=ROME),"sas_gwh":float("nan")},
        {"gas_day":date(2026,11,18),"published_at":datetime(2026,11,18,9,tzinfo=ROME),"sas_gwh":999},
    ])
    r=balancing_metrics(frame,2026,11,NOW,15)
    assert r["expected"]==17 and r["observed"]==1
    assert r["mean_abs_sas"]==20 and r["outside_band"]==1
    assert closed_gas_day(NOW.replace(hour=5))==date(2026,11,16)


def test_settlement_only_closed_gas_days():
    rows=sample_rows()
    r=settlement_metrics(rows,"DEMO-001",2026,9,date(2026,9,5))
    assert r["expected"]==5 and r["eligible_pct"]==100
    assert r["revision_abs"]==D("4200.00") and r["revised"]==1
    r=settlement_metrics(rows[:-2],"DEMO-001",2026,9,date(2026,9,30))
    assert r["eligible"]==29 and r["exceptions"]==1


def test_bso_page_demo_and_imported_empty():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string("from gasops_app.bso_kpi_page import page\npage()",default_timeout=30).run()
    assert not app.exception
    app.radio(key="bso_view").set_value("Registro operativo").run()
    assert not app.exception
    assert [t.label for t in app.tabs]==["Scadenze","Calendario Snam","Balancing","Settlement"]
    assert app.radio(key="bso_mode").value=="Dati importati"
    app.radio(key="bso_mode").set_value("Demo").run()
    assert not app.exception
    assert any("Puntualità" in e.proto.body and "60,0" in e.proto.body for e in app.get("html"))
    assert any("Scadute aperte" in e.proto.body for e in app.get("html"))
    assert any("Copertura SAS" in e.proto.body and "16/17" in e.proto.body for e in app.get("html"))
    assert any("Definitivi utilizzabili" in e.proto.body and "30/30" in e.proto.body for e in app.get("html"))
    app.radio(key="bso_mode").set_value("Dati importati").run()
    assert not app.exception
    assert any("Importa il registro" in e.value for e in app.info)
    assert not any("Puntualità" in e.proto.body and "60,0" in e.proto.body for e in app.get("html"))


def test_bso_overview_default_and_no_demo_fallback():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string("from gasops_app.bso_kpi_page import page\npage()",default_timeout=30).run()
    assert not app.exception
    assert app.radio(key="bso_view").value=="Panoramica"
    assert not app.tabs
    metrics={m.label:m.value for m in app.metric}
    assert "Sbilanciamenti / volume" in metrics and metrics["Sbilanciamenti / volume"]=="7,4 %"
    assert metrics["Neutralità netta rettificata"]=="0,03 €/MWh"
    assert len(metrics)==6 and all(v!="—" for v in metrics.values())
    assert not {"Attività aperte in ritardo","|SAS| medio","Definitivi utilizzabili"}&set(metrics)
    assert any("Le assenze non valgono zero" in e.value for e in app.info)
    assert any("Priorità" in t.value.columns and "Azione proposta" in t.value.columns for t in app.dataframe)
    operational=next(t.value for t in app.dataframe if set(t.value.columns)=={"Area","KPI","Valore","Unità","Periodo","Copertura","Stato"})
    assert len(operational)==10
    assert operational["Valore"].isna().all()
    assert operational["Stato"].eq("Non disponibile").all()
    context=next(t.value for t in app.dataframe if set(t.value.columns)=={"Area","KPI","Valore","Unità","Periodo","Perimetro","Stato","Copertura / fonte"})
    assert len(context)==13
    assert context.loc[context["KPI"]=="Sbilanciamenti / volume","Valore"].iloc[0]==7.4
    assert context.loc[context["KPI"]=="Flusso fisico","Valore"].isna().all()

    # Visiting demo mode must not populate or contaminate the overview.
    app.radio(key="bso_view").set_value("Registro operativo").run()
    assert not app.exception
    assert app.radio(key="bso_mode").value=="Dati importati"
    app.radio(key="bso_view").set_value("Panoramica").run()
    assert not app.exception
    assert {m.label:m.value for m in app.metric}==metrics
    assert next(t.value for t in app.dataframe if set(t.value.columns)=={"Area","KPI","Valore","Unità","Periodo","Copertura","Stato"})["Valore"].isna().all()


def test_session_task_import_direct_and_invalid_keeps_previous(monkeypatch):
    from types import SimpleNamespace
    from streamlit.testing.v1 import AppTest
    from gasops_app import bso_kpi_page as page
    raw=task_template().encode()
    upload=SimpleNamespace(size=len(raw),getvalue=lambda:raw)
    monkeypatch.setattr(page.st,"file_uploader",lambda *a,**kw:upload)
    app=AppTest.from_string("from gasops_app.bso_kpi_page import _import_tasks\n_import_tasks()").run()
    assert not app.exception and not app.checkbox
    assert page.STATE not in app.session_state
    next(b for b in app.button if b.label=="Importa").click().run()
    assert not app.exception
    assert app.session_state[page.STATE]["tasks"]==task_demo()
    old=app.session_state[page.STATE]["sha256"]
    raw=b"invalid CSV"
    next(b for b in app.button if b.label=="Importa").click().run()
    assert not app.exception and app.error
    assert app.session_state[page.STATE]["sha256"]==old
