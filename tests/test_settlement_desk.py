from dataclasses import replace
from decimal import Decimal as D

import pytest

from gasops_app.operations_ledger import sample_rows
from gasops_app.settlement_desk import parse_csv,template,daily_controls,monthly_summary,revision_effects


def test_roundtrip_and_complete_daily_month():
    rows=parse_csv(template().encode())
    assert rows==sample_rows()
    days=daily_controls(rows,"DEMO-001",2026,9)
    result=monthly_summary(days)
    assert result["complete"] and result["eligible"]==30
    assert result["debits"]==D("172200.00") and result["credits"]==D("57000.00")
    for row in days:
        assert row["quantity_effect_eur"]+row["price_effect_eur"]==row["delta_cash_eur"]


def test_missing_definitive_and_exception_exclude_from_subtotal():
    rows=sample_rows()
    rows[1]=replace(rows[1],sell=None)
    rows[3]=replace(rows[3],storage_net=D(0))
    days=daily_controls(rows[:-2],"DEMO-001",2026,9)
    assert "Prezzo applicabile mancante" in days[0]["issues"]
    assert "Variazione stoccaggio tra versioni" in days[1]["issues"]
    assert days[-1]["stage"]=="missing"
    assert monthly_summary(days)["eligible"]==27


def test_revision_bridge_handles_sign_flip_and_missing_counterfactual():
    prev=sample_rows()[0]
    last=replace(prev,version=2,stage="definitive",withdrawn=prev.injected+prev.storage_net+prev.psv_net+D(100),
                 buy=D(44),sell=D(39))
    delta,q,p=revision_effects(prev,last)
    assert delta==last.cash-prev.cash and q+p==delta
    assert revision_effects(replace(prev,buy=None),last)==(delta,None,None)


def test_invalid_csv_rejected():
    raw=template()
    with pytest.raises(ValueError,match="duplicati"):
        parse_csv((raw+raw.splitlines()[1]+"\n").encode())
    with pytest.raises(ValueError):
        parse_csv(raw.replace("DEMO-001","=1+2").encode())
    with pytest.raises(ValueError):
        parse_csv(raw.replace(",8000,",",NaN,",1).encode())
