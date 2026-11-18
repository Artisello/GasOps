from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from gasops_app.operations_ledger import BalanceRow, allocate_lng_deviation, monthly_preview, revision_pairs, sample_rows


def row():
    return BalanceRow("U", date(2026, 9, 1), 1, "provisional", D(8000), D(300), D(200), D(9000), D(42), D(38))


def test_full_equation_and_negative_price():
    assert row().imbalance == -500
    assert row().cash == D("-21000.00")
    assert replace(row(), buy=D(-42)).cash == D("21000.00")


def test_missing_price_not_zero():
    assert replace(row(), buy=None).cash is None
    assert replace(row(), withdrawn=D(8500), buy=None, sell=None).cash == 0


def test_versions_and_duplicate():
    first = row()
    last = replace(first, version=2, stage="definitive", withdrawn=D(9100))
    assert revision_pairs([last, first]) == [(first, last)]
    with pytest.raises(ValueError, match="Duplicate"):
        revision_pairs([first, first])
    with pytest.raises(ValueError, match="S_k"):
        revision_pairs([first, replace(last, storage_net=D(0))])


def test_month_requires_complete_definitive_data():
    rows = sample_rows()
    assert monthly_preview(rows[:-1], "DEMO-001", 2026, 9)["status"] == "BLOCKED_REVIEW"
    result = monthly_preview(rows, "DEMO-001", 2026, 9)
    assert result["days"] == 30
    assert result["net_user_cash_eur"] == result["long_group_eur"] - result["short_group_eur"]
    assert result["short_payment_days"] == 15
    assert result["long_payment_days"] == 30


def test_lng_conservation_and_zero_denominator():
    assert allocate_lng_deviation({"A": D(60), "B": D(40)}, D(10)) == {"A": D(6), "B": D(4)}
    assert sum(allocate_lng_deviation({"A": D(1), "B": D(2)}, D(1)).values()) == 1
    with pytest.raises(ValueError, match="denominator"):
        allocate_lng_deviation({"A": D(0)}, D(1))
    with pytest.raises(ValueError, match="Negative"):
        allocate_lng_deviation({"A": D(1)}, D(-2))
