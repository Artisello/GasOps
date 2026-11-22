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
    assert all(pd.Timestamp(x["power_power_acquired"])<=pd.Timestamp(x["origin"])+pd.Timedelta(15, unit="h") for x in r["records"])
    assert 0<=r["scores"]["bayesian_multi"]["coverage_80"]<=100
    opts=groups({"terna_history_v1":bs[:14]})
    with pytest.raises(ValueError,match="giorni comuni"):evaluate(v,2,asof,opts,["power"])



def test_joint_power_network_sources_preserve_independent_lineage():
    from datetime import timedelta,timezone
    from gasops_app.snam_forecast import samples
    from gasops_app.entsog_vintages import STATE,SELECT
    from gasops_app.snam_bayesian import align
    v,bs,asof=fixture()
    d=samples(v,2)
    point="IT-TSO-0001ITP-00093entry"
    network=[]
    for target,row in d.iterrows():
        at=(row.origin.to_pydatetime()+timedelta(hours=10)).replace(tzinfo=timezone.utc)
        day=str(target.date())
        network.append({"point":point,"acquired":at.isoformat(),"first":day,"last":day,"complete":True,
                        "rows":[{"day":day,"indicator":"Nomination","gwh":100.,"assumed":False}]})
    opts=groups({"terna_history_v1":bs,STATE:network,SELECT:point})
    keys=["power","network_Nomination"]
    a,cols,lineage=align(d,opts,keys,asof)
    assert len(cols)==5 and len(lineage)==6
    assert a[cols].dropna().shape[0]>=300
    r=evaluate(v,2,asof,opts,keys)
    assert r["n"]==90
    assert all("power_power_sha256" in rec and "network_Nomination_power_sha256" in rec for rec in r["records"])
