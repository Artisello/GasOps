import numpy as np
import pandas as pd
import pytest
from gasops_app.predictive import evaluate as lab,Covariate
from gasops_app.snam_bayesian import evaluate,groups
from gasops_app.bayesian import posterior_regression
from test_terna_history_forecast import fixture


def test_standardized_posterior_finite_ordered():
    x=np.arange(180,dtype=float)
    t=pd.DataFrame({"x":x,"actual":10+2*x})
    p=posterior_regression(t,pd.DataFrame({"x":[180.]}),["x"])
    assert p["low"]<=p["estimate"]<=p["high"]
    assert p["estimate"]==pytest.approx(370,abs=1)


def test_lab_bayesian_out_of_sample():
    from test_predictive import fixture as gas
    frame=gas()
    c=Covariate("HDD",pd.Series(np.sin(np.arange(len(frame))/10),index=frame.index),"C","IT","fixture","test")
    r=lab(frame,[c],1)
    assert r["test_n"]==28 and 0<=r["scores"]["bayesian_multi"]["coverage_80"]<=100
    assert r["forecast"]["bayesian_multi_low"]<=r["forecast"]["bayesian_multi"]<=r["forecast"]["bayesian_multi_high"]


def test_snam_power_posterior_same_dates_and_cutoff():
    v,bs,asof=fixture()
    opts=groups({"terna_history_v1":bs})
    r=evaluate(v,2,asof,opts,["power"])
    assert r["n"]==90
    assert r["scores"]["bayesian_multi"]["mae"]<r["scores"]["bayesian_base"]["mae"]
    assert all(pd.Timestamp(x["power_power_acquired"])<=pd.Timestamp(x["origin"])+pd.Timedelta(hours=15) for x in r["records"])
    assert 0<=r["scores"]["bayesian_multi"]["coverage_80"]<=100
    opts=groups({"terna_history_v1":bs[:14]})
    with pytest.raises(ValueError,match="giorni comuni"):evaluate(v,2,asof,opts,["power"])
