from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest

from gasops_app.data import Bundle, synthetic, utc_starts
from gasops_app.finance import ScenarioCase, ScenarioInput, SettlementInput, scenario, settle
from gasops_app.forecast import forecast
from gasops_app.models import Kind
from gasops_app.quality import inspect

D = Decimal
NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def test_fixture_quarantines_bad_observations_without_imputation():
    bundle = synthetic()
    analysis = inspect(bundle, NOW)
    assert bundle.origin.kind == Kind.SYNTHETIC
    assert len(analysis.usable) == 420
    assert {"timestamp", "unit", "duplicate", "conflicting", "missing-period",
            "missing-demand_gwh", "outlier-supply_gwh", "dst"} <= {f.id for f in analysis.findings}
    assert pd.isna(analysis.usable.loc["2026-11-03", "supply_gwh"])
    assert pd.notna(analysis.usable.loc["2026-11-03", "demand_gwh"])
    assert analysis.usable.loc["2026-10-13"].isna().all()
    assert analysis.usable.loc["2026-11-16", "demand_gwh"] == 2348.4


def test_quality_keeps_published_values_flagged_as_statistically_unusual():
    fixture = synthetic()
    published = Bundle(fixture.rows, fixture.origin.model_copy(update={"kind": Kind.HISTORICAL}), fixture.fingerprint)
    analysis = inspect(published, NOW)
    finding = next(item for item in analysis.findings if item.id == "outlier-supply_gwh")
    assert finding.severity == "info"
    assert pd.notna(analysis.usable.loc["2026-11-03", "supply_gwh"])


@pytest.mark.parametrize(("start", "expected"), [("2026-03-28", 23), ("2026-10-24", 25), ("2026-11-16", 24)])
def test_gas_day_starts_are_utc_and_handle_dst(start, expected):
    stamps = utc_starts(pd.date_range(start, periods=2, freq="D"), "daily")
    assert str(stamps.tz) == "UTC"
    assert (stamps[1] - stamps[0]).total_seconds() == expected * 3600


@pytest.mark.parametrize(
    ("delivered", "withdrawn", "buy", "sell", "side", "cash", "direction"),
    [
        ("8800", "10000", "42", None, "buy", "-50400.00", "charge"),
        ("8800", "10000", "-42", None, "buy", "50400.00", "credit"),
        ("10100", "10000", None, "-38", "sell", "-3800.00", "charge"),
        ("10000", "10000", None, None, "flat", "0.00", "flat"),
    ],
)
def test_settlement_signed_cash_flows(delivered, withdrawn, buy, sell, side, cash, direction):
    result = settle(SettlementInput(
        delivered=delivered, withdrawn=withdrawn, buy_eur_mwh=buy, sell_eur_mwh=sell,
    ))
    assert result.side == side
    assert result.cash_flow_eur == D(cash)
    assert result.direction == direction


def test_settlement_missing_inputs_and_decimal_conversion():
    case = SettlementInput(delivered="8.8", withdrawn="10", unit="GWh", buy_eur_mwh="42.125")
    result = settle(case)
    assert result.imbalance_mwh == D("-1200")
    assert result.cash_flow_eur == D("-50550.00")
    missing = settle(case.model_copy(update={"buy_eur_mwh": None}))
    assert missing.cash_flow_eur is None and missing.side == "buy" and missing.problems
    assert settle(case.model_copy(update={"delivered": None})).imbalance_mwh is None
    with pytest.raises(ValueError):
        SettlementInput(buy_eur_mwh="NaN")


def test_scenario_storage_and_zero_demand():
    case = ScenarioCase(demand_gwh=100, supply_gwh=90, storage_gwh=10, price_eur_mwh=30)
    stress = scenario(case, ScenarioInput(demand_pct=10, supply_pct=-25, storage_pct=50, price_delta_eur_mwh=5))
    assert stress.demand_gwh == D(110)
    assert stress.supply_gwh == D(75)
    assert stress.imbalance_gwh == D(-35)
    assert stress.gap_value_eur == D("-1225000.00")
    assert scenario(case, ScenarioInput(demand_pct=-100)).coverage_pct is None
    with pytest.raises(ValueError, match="stoccaggio"):
        scenario(case.model_copy(update={"storage_gwh": D(100)}), ScenarioInput())


def test_settlement_accepts_italian_decimal_separator():
    result = settle(SettlementInput(delivered="8.800,5", withdrawn="10.000,5", buy_eur_mwh="42,125"))
    assert result.imbalance_mwh == D("-1200.0")
    assert result.cash_flow_eur == D("-50550.00")


@pytest.mark.parametrize("model", ["Seasonal regression", "Seasonal naive"])
def test_backtest_has_no_same_period_or_future_leakage(model):
    data = inspect(synthetic(), NOW).usable["demand_gwh"]
    baseline = forecast(data, "daily", model)
    latest = data.index[-8]
    changed = data.copy()
    changed.loc[latest:] *= 3
    revised = forecast(changed, "daily", model)
    original_by_day = {row.period: row.estimate for row in baseline.backtest}
    for row in revised.backtest:
        assert row.train_end < row.period
        if row.period <= latest.date().isoformat():
            assert row.estimate == original_by_day[row.period]
    assert len(baseline.points) == 14
    assert baseline.points[0].lower_80 is not None
    assert 0 <= baseline.points[0].lower_80 <= baseline.points[0].upper_80
