import numpy as np
import pandas as pd
import pytest
from gasops_app.forecast import forecast


@pytest.mark.parametrize("model", ["ARIMA", "SARIMAX"])
def test_state_space_daily(model):
    rng = np.random.default_rng(12)
    t = np.arange(300)
    series = pd.Series(300 + .1*t + 30*np.sin(2*np.pi*t/7) + rng.normal(0, 4, len(t)),
                       index=pd.date_range("2024-01-01", periods=len(t), freq="D"))
    series.iloc[240] = np.nan
    result = forecast(series, "daily", model)
    assert result.interval_kind == "model_based"
    assert len(result.points) == 14 and len(result.backtest) >= 50
    assert all(p.train_end < p.period for p in result.backtest)
    assert all(0 <= p.lower_80 <= p.estimate <= p.upper_80 for p in result.points)


def test_short_and_constant_series_unavailable():
    series = pd.Series(10., index=pd.date_range("2024-01-01", periods=40))
    assert not forecast(series, "daily", "ARIMA").points
    series = pd.Series(10., index=pd.date_range("2024-01-01", periods=200))
    assert not forecast(series, "daily", "SARIMAX").points


def test_monthly_state_space():
    t = np.arange(100)
    dates = pd.date_range("2017-01-01", periods=len(t), freq="MS")
    rng = np.random.default_rng(21)
    series = pd.Series((300 + 35*np.cos(2*np.pi*t/12) + rng.normal(0, 6, len(t))) * dates.days_in_month, index=dates)
    result = forecast(series, "monthly", "SARIMAX")
    assert len(result.points) == 6
    assert result.coverage_samples >= 12
