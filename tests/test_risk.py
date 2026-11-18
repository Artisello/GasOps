import numpy as np
import pytest
from gasops_app.risk import RiskSettings, simulate, tail_metrics, forecast_uncertainty


def test_tail_mass_including_zero_ties():
    losses = np.array([0.]*98+[10.,30.])
    p = tail_metrics(losses,.95)
    assert p["var"] == 0
    assert p["cvar"] == pytest.approx(8.)
    assert tail_metrics(losses,.99)["cvar"] == pytest.approx(30.)
    assert tail_metrics([0.,10.,20.],.5)["cvar"] == pytest.approx(50/3)


def test_deterministic_zero_volatility_and_units():
    s = RiskSettings(demand_cv=0,supply_cv=0,price_sd=0)
    r = simulate(100,90,40,s).summary
    assert r["probability_deficit"] == 1
    assert r["expected_deficit_gwh"] == 10
    assert r["gross_cost_tail_eur"]["99"]["cvar"] == 400000
    assert simulate(90,100,40,s).summary["expected_gross_cost_eur"] == 0
    assert simulate(100,90,None,s).summary["gross_cost_tail_eur"] is None
    assert simulate(100,90,-10,s).summary["expected_gross_cost_eur"] == 0


def test_seed_and_consistent_risk():
    a = simulate(2400,2500,42)
    b = simulate(2400,2500,42)
    assert a.summary == b.summary
    np.testing.assert_array_equal(a.gap,b.gap)
    for tails in (a.summary["gross_cost_tail_eur"],a.summary["deficit_tail_gwh"]):
        assert tails["95"]["cvar"] >= tails["95"]["var"]
        assert tails["99"]["cvar"] >= tails["95"]["cvar"]
    assert 0 < a.summary["probability_deficit"] < 1


def test_adverse_correlation_increases_gap_variance():
    pos = simulate(2400,2400,42,RiskSettings(rho_ds=1,demand_cv=.05,supply_cv=.05))
    neg = simulate(2400,2400,42,RiskSettings(rho_ds=-1,demand_cv=.05,supply_cv=.05))
    assert np.std(pos.gap) < 1e-8
    assert np.std(neg.gap) > 200


def test_validation():
    with pytest.raises(ValueError):
        simulate(float("nan"),90,40)
    with pytest.raises(ValueError):
        simulate(100,-1,40)
    with pytest.raises(ValueError):
        RiskSettings(simulations=1000000)
    with pytest.raises(ValueError):
        tail_metrics([float("inf")], .95)


def test_forecast_uncertainty_only_oos_errors():
    from types import SimpleNamespace
    p = SimpleNamespace(backtest=[SimpleNamespace(actual=i+e,estimate=i) for i,e in enumerate(range(25))])
    sd,n = forecast_uncertainty(p)
    assert n == 25 and sd == pytest.approx(np.std(range(25),ddof=1))
    assert forecast_uncertainty(SimpleNamespace(backtest=p.backtest[:10])) == (None,10)
