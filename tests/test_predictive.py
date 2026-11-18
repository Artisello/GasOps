from datetime import datetime,timezone
import numpy as np
import pandas as pd
import pytest

from gasops_app.predictive import Covariate,evaluate,origin_frame,series_from_rows,HORIZONS
from gasops_app.data import jrc_archive
from gasops_app.quality import inspect


def fixture(n=200):
    idx=pd.date_range("2025-01-01",periods=n,freq="D")
    x=np.arange(n,dtype=float)
    industry=40+np.sin(x/5)
    power=70+np.cos(x/4)*10
    distribution=90+np.sin(x/16)*25
    return pd.DataFrame({"industry_gwh":industry,"power_gwh":power,"distribution_gwh":distribution,
                         "demand_gwh":industry+power+distribution},index=idx)


@pytest.mark.parametrize("h",HORIZONS)
def test_common_dates_and_no_future_labels(h):
    frame=fixture()
    c=Covariate("HDD",pd.Series(np.sin(np.arange(len(frame))/10),index=frame.index),"C","IT","fixture","test")
    r=evaluate(frame,[c],h)
    assert r["test_n"]==28
    assert r["forecast"] is not None
    assert all(pd.Timestamp(p["train_target_end"])<=pd.Timestamp(p["origin"])-pd.Timedelta(days=2) for p in r["records"])
    assert all(p["train_n"]>=45 for p in r["records"])
    assert pd.Timestamp(r["forecast"]["target"])-pd.Timestamp(r["forecast"]["origin"])==pd.Timedelta(days=h)
    assert all(np.isfinite(s["mae"]) for s in r["scores"].values())


def test_lag_features_and_calendar_gaps():
    f=fixture()
    s=pd.Series(np.arange(len(f)),index=f.index)
    c=Covariate("x",s,"TWh","IT","test","test")
    a,ar,multi,last,ref=origin_frame(f,[c],7)
    day=f.index[100]
    assert a.loc[day,"external_0"]==93
    assert a.loc[day,"lag2"]==f.iloc[98]["demand_gwh"]
    assert a.loc[day,"weekly"]==f.iloc[93]["demand_gwh"]
    changed=f.copy()
    changed.loc[day:,"demand_gwh"]*=999
    s2=s.copy();s2.loc[day:]*=999
    b,*_=origin_frame(changed,[Covariate("x",s2,"TWh","IT","test","test")],7)
    pd.testing.assert_series_equal(a.loc[day,multi],b.loc[day,multi])
    gap=f.drop(f.index[98])
    g,*_=origin_frame(gap,[c],7)
    assert pd.isna(g.loc[day,"lag2"])


def test_short_external_no_silent_fallback():
    f=fixture()
    c=Covariate("Terna",f.demand_gwh.tail(14),"GWh","IT","test","test")
    with pytest.raises(ValueError,match="date valutabili"):
        evaluate(f,[c],1)


def test_real_jrc_archive():
    b=jrc_archive()
    f=inspect(b,datetime(2026,11,18,tzinfo=timezone.utc)).usable.tail(730)
    r=evaluate(f,[],1)
    assert r["test_n"]>=14 and r["last_observed"].startswith("2021")


def test_duplicate_external_conflict():
    with pytest.raises(ValueError):
        series_from_rows([{"day":"2025-01-01","v":1},{"day":"2025-01-01","v":2}],"day","v")
