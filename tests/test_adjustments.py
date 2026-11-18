from datetime import date
from decimal import Decimal as D
import pytest
from gasops_app.adjustments import template,merge,archive_csv,controls,economic_legs,coverage,monthly
from gasops_app.operations_ledger import BalanceRow

NOW=date(2026,11,18)
def raw(*x):return (template()+"\n".join(x)+"\n").encode()

def test_delta_inversion_and_separate_monthly_components():
    a=raw("U1,2026,2025-09-01,DS,balancing,B1,A1,-100,50,150",
          "U1,2026,2025-09-01,IO,balancing,B1,A1,20,30,9",
          "U1,2026,2025-09-01,CVU,balancing,B1,A1,10,30,20")
    saved=merge(None,a,NOW)
    result=controls(saved["rows"],"U1",2026,2025,9)
    ds=next(x for x in result if x["component"]=="DS")
    assert ds["delta_eur"]==150 and ds["credit_eur"]==150
    assert "Inversione" in ds["issues"]
    assert any("discordante" in x["issues"] for x in result)
    assert monthly(result)["debit"]==20
    cov={x["component"]:x for x in coverage(result,2025,9)}
    assert cov["IO"]["expected"]==1 and cov["DS"]["expected"]==30 and cov["CPU"]["received"]==0
    assert merge(saved,a,NOW)==saved
    assert merge(None,archive_csv(saved).encode(),NOW)["rows"]==saved["rows"]
    with pytest.raises(ValueError):merge(saved,raw("U1,2026,2025-09-01,DS,balancing,B1,A1,-100,51,150"),NOW)

def test_baseline_and_other_years():
    saved=merge(None,raw("U1,2026,2025-09-01,DS,balancing,B1,A1,-100,-40,60",
                         "U1,2026,2024-09-01,DS,adjustment,A0,A1,-100,-40,60"),NOW)
    b=BalanceRow("U1",date(2025,9,1),1,"definitive",D(100),D(0),D(0),D(102),D(40),D(30))
    r=controls(saved["rows"],"U1",2026,2025,9,balances=[b])[0]
    assert r["baseline_difference_eur"]==-20 and "Baseline" in r["issues"]
    assert controls(saved["rows"],"U1",2026,2024,9,balances=[b])[0]["baseline_difference_eur"] is None
    with pytest.raises(ValueError):merge(None,raw("U1,2026,2024-09-01,DS,balancing,B1,A1,-100,-40,60"),NOW)
    with pytest.raises(ValueError):merge(None,raw("U1,2026,2025-09-02,IO,balancing,B1,A1,10,20,10"),NOW)

def test_empty_and_signs():
    assert monthly([]) is None
    assert economic_legs(D(20),D(-30),"DS")[0]==(D(-20),D(-30))
    assert economic_legs(D(20),D(30),"CVU")[0]==(D(-10),)
    assert economic_legs(D(0),D(30),"DS")[1].startswith("Passaggio")
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string("from gasops_app.adjustments_page import panel\npanel()").run()
    assert not app.exception and not app.metric


def test_prior_adjustment_predecessor():
    s=merge(None,raw("U1,2025,2024-09-01,DS,balancing,B,A25,-100,-60,40",
        "U1,2026,2024-09-01,DS,adjustment,A25,A26,-50,-30,20",
        "U1,2025,2024-09-01,IO,balancing,B,A25,100,110,10",
        "U1,2026,2024-09-01,IO,adjustment,WRONG,A26,110,115,5"),NOW)
    r={x["component"]:x for x in controls(s["rows"],"U1",2026,2024,9)}
    assert r["DS"]["baseline_difference_eur"]==10
    assert "Baseline" in r["DS"]["issues"]
    assert r["IO"]["baseline_difference_eur"] is None
    assert "Riferimento" in r["IO"]["issues"]
