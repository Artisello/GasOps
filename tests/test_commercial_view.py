from datetime import date
from decimal import Decimal as D

from gasops_app.commercial_controls import demo_invoices,reconcile
from gasops_app.commercial_view import reconciliation_summary,guarantee_scenario,deadline_status,calendar_rows
from gasops_app.operations_ledger import sample_rows


def test_summary_keeps_unknown_amounts_separate():
    summary=reconciliation_summary(reconcile(sample_rows(),demo_invoices()[:1],"DEMO-001",2026,9))
    assert summary=={"issues":2,"known_difference":D(4200),"unknown":1}


def test_guarantee_sensitivity_and_exact_boundary():
    result=guarantee_scenario(D(420000),D(280000),D(220000),D(1000000),D(80000))
    assert result["current"]["status"]=="ATTENZIONE"
    assert result["projected"]["status"]=="LIMITE"
    assert result["projected"]["headroom"]==0
    assert result["to_90"]==D(-20000)
    assert result["additional_meps_90"]==D("111111.12")
    assert guarantee_scenario(D(0),D(0),D(-1),D(100),D(0))["additional_meps_90"]==0


def test_calendar_no_paid_or_overdue_inference():
    day=date(2026,11,18)
    assert deadline_status(date(2026,11,13),day)=={"days_left":-5,"status":"Data trascorsa"}
    assert deadline_status(day,day)["status"]=="Oggi"
    assert deadline_status(date(2026,11,25),day)["status"]=="Entro 7 giorni"
    assert deadline_status(date(2026,11,26),day)["status"]=="Successiva"
    rows=calendar_rows([{"due":None},{"due":day}],day)
    assert rows[0]["status"]=="Oggi" and rows[1]["days_left"] is None
