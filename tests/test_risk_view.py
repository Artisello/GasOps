import numpy as np
import pytest
from gasops_app.risk import RiskSettings
from gasops_app.risk_view import Stress,compare_stress,gap_distribution,cost_distribution


def test_combined_stress_zero_volatility_and_price_shift():
    s=RiskSettings(demand_cv=0,supply_cv=0,price_sd=0)
    result,base=compare_stress(100,110,40,s,Stress(demand_pct=10,supply_pct=-10,price_delta=10))
    assert base["probability_deficit"]==0
    assert result.summary["probability_deficit"]==1
    assert result.summary["expected_deficit_gwh"]==pytest.approx(11)
    assert result.summary["expected_gross_cost_eur"]==pytest.approx(550000)


def test_same_seed_no_shocks_and_missing_price():
    settings=RiskSettings()
    result,base=compare_stress(100,100,None,settings,Stress())
    assert result.summary==base and result.loss is None
    result,base=compare_stress(100,100,None,settings,Stress(demand_pct=10,price_delta=10),demand_sd=5)
    assert result.summary["inputs"]["demand_sd_gwh"]==base["inputs"]["demand_sd_gwh"]==5
    assert result.loss is None
    assert result.summary["probability_deficit"]>=base["probability_deficit"]


def test_distribution_preserves_zero_and_sign():
    values=np.array([-100.,-1.,0.,0.,1.,100.])
    h=gap_distribution(values)
    assert sum(h["counts"])==len(values)
    assert sum(h["counts"][h["negative"]])==2
    assert sum(h["pct"])==pytest.approx(100)
    h=gap_distribution(np.zeros(1000))
    assert sum(h["counts"][h["negative"]])==0
    c=cost_distribution([0,0,100,200])
    assert c["zero_pct"]==50 and sum(c["pct"])==pytest.approx(50)
    assert cost_distribution([0,0])["zero_pct"]==100
