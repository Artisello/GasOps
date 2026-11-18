from datetime import date,timedelta
from decimal import Decimal as D
from dataclasses import replace
import pytest

from gasops_app.commercial_controls import (demo_invoices, exposure, imbalance_prices, lng_deadlines,
                                             reconcile, working_offset)
from gasops_app.operations_ledger import sample_rows

DAY=date(2026,9,5)

def test_price_threshold_and_fallback():
    history={DAY-timedelta(days=i):D(39) for i in range(1,31)}
    p=imbalance_prices(DAY,D(2000),D(40),D(42),D(38),D(1),history)
    assert p["mean"]==40 and p["adjustment"]==D(".4")
    assert p["buy"]==42 and p["sell"]==38
    p=imbalance_prices(DAY,D(1999),None,D(39),D(39),D(1),history)
    assert p["mean"]==39 and p["buy"]==D("39.39") and p["sell"]==D("38.61")
    with pytest.raises(ValueError,match="30 giorni"):
        imbalance_prices(DAY,D(1999),D(40),D(42),D(38),D(1),{})
    with pytest.raises(ValueError,match="Regime"):
        imbalance_prices(DAY,D(2000),D(40),D(42),D(38),D(1),ordinary=False)

def test_exposure_boundaries():
    assert exposure(D(80),D(9),D(0),D(100))["status"]=="OK"
    assert exposure(D(80),D(10),D(0),D(100))["status"]=="ATTENZIONE"
    assert exposure(D(80),D(20),D(0),D(100))["status"]=="LIMITE"
    with pytest.raises(ValueError):
        exposure(D(0),D(0),D(0),D(0))

def test_reconciliation_differences_missing_duplicates():
    rows=sample_rows()
    invoices=demo_invoices()
    result=reconcile(rows,invoices,"DEMO-001",2026,9)
    assert result[0]["expected"]==D(172200)
    assert result[0]["delta"]==D(-4200)
    assert result[1]["status"]=="QUADRA"
    assert result[0]["due"]==date(2026,11,13)
    assert result[1]["due"]==date(2026,11,28)
    assert reconcile(rows,invoices[:1],"DEMO-001",2026,9)[1]["status"]=="MANCANTE"
    with pytest.raises(ValueError,match="duplicato"):
        reconcile(rows,invoices+[invoices[0]],"DEMO-001",2026,9)
    assert reconcile(rows,invoices+[replace(invoices[0],identifier="X")],"DEMO-001",2026,9)[0]["status"]=="MULTIPLA · VERIFICA"
    with pytest.raises(ValueError,match="bloccata"):
        reconcile(rows[:-1],invoices,"DEMO-001",2026,9)

def test_calendar_excludes_weekends_and_supplied_holidays():
    assert working_offset(date(2026,12,25),1,{date(2026,12,28)})==date(2026,12,29)
    result=lng_deadlines(date(2026,12,1),date(2026,11,20),set())
    assert result[0]["due"]==date(2026,11,18)
    assert result[1]["due"]==date(2026,11,20)
    assert result[2]["due"]==date(2026,11,23)
    with pytest.raises(ValueError):
        lng_deadlines(date(2026,12,2),None,set())
