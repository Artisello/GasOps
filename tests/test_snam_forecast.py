from datetime import datetime,timedelta
import pandas as pd
import numpy as np
import pytest
from gasops_app.snam_forecast import (HEADERS,FIELDS,parse_stamp,extract_rows,daily_vintages,evaluate,samples)


def test_cutoff_and_sheet_targets():
    day="2026_11_17"
    rows=[(1,HEADERS),(2,{"A":day+"_14","B":"17/11/2026 14:45:00","E":"100","C":"50","AA":"10"}),
          (3,{"A":day+"_15","B":"17/11/2026 15:01:00","E":"999","C":"50","AA":"10"})]
    out,bad=extract_rows(rows,"Storico_G+2","source.xlsx","a"*64)
    assert len(out)==1 and bad==0
    assert out[0][4]==datetime(2026,11,19)
    assert parse_stamp("45050.201620370368").hour==4
    actual,_=extract_rows(rows,"Storico_G-1","source.xlsx","a"*64)
    assert actual[0][4]==datetime(2026,11,16)


def fixture():
    records=[]
    for i in range(350):
        origin=datetime(2025,1,1)+timedelta(days=i)
        for h in (-1,0,1,2):
            target=origin+timedelta(days=h)
            n=(target-datetime(2025,1,1)).days
            actual=1000+100*np.sin(n/20)
            value=actual if h==-1 else actual+20
            records.append((origin,h,origin+timedelta(hours=14),origin.strftime("%Y_%m_%d")+"_14",target,value,500,12,"fixture.xlsx","a"*64,"fixture",i+2))
    return pd.DataFrame(records,columns=FIELDS)


@pytest.mark.parametrize("h",[0,1,2])
def test_walk_forward_common_samples(h):
    frame=fixture()
    asof=datetime(2026,1,1,15)
    v,conflicts=daily_vintages(frame,asof)
    assert conflicts==0
    r=evaluate(v,h,asof)
    assert r["n"]==90
    assert r["scores"]["official"]["mae"]==pytest.approx(20)
    assert r["scores"]["igor"]["mae"]<0.001
    assert all(pd.Timestamp(row["train_target_end"])+pd.Timedelta(days=1)<=pd.Timestamp(row["origin"]) for row in r["records"])


def test_conflicting_latest_not_arbitrarily_selected():
    f=fixture()
    extra=f.iloc[[0]].copy()
    extra["demand"]=9999
    v,conflicts=daily_vintages(pd.concat([f,extra]),datetime(2026,1,1,15))
    assert conflicts==1 and len(v)==len(f)-1


def test_forecast_panel_empty():
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_string("from gasops_app.snam_forecast_page import panel\npanel()").run()
    assert not app.exception
    assert any("Carica le annualità" in x.value for x in app.info)
