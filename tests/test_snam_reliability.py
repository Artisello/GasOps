from datetime import datetime,timedelta
import pandas as pd
import pytest
from gasops_app.snam_forecast import HEADERS,EXTRA_HEADERS,EXTRA_FIELDS,extract_rows,FIELDS,daily_vintages
from gasops_app.snam_reliability import evaluate_extended,band


def test_native_extended_headers_and_missing():
    row={"A":"2026_11_17_14","B":"17/11/2026 14:45:00","E":"100","C":"50","AA":"10","F":"20","H":"30","J":"40"}
    rows,_=extract_rows([(1,HEADERS|EXTRA_HEADERS),(2,row)],"Storico_G+2","fixture.xlsx","a"*64,include_extended=True)
    assert rows[0][-3:]==(20,30,40)
    rows,_=extract_rows([(1,HEADERS),(2,row)],"Storico_G+2","fixture.xlsx","a"*64,include_extended=True)
    assert all(pd.isna(v) for v in rows[0][-3:])


def test_interval_uses_available_errors_only():
    t=pd.Timestamp("2026-01-01")
    rows=[{"actual":100,"extended":90,"_label_available":t} for _ in range(30)]
    rows.append({"actual":10000,"extended":0,"_label_available":t+pd.Timedelta(days=1)})
    assert band(rows,t,50)=={"low":40,"high":60,"cal_n":30}
    assert band(rows[:29],t,50) is None


def test_common_sample_and_sequential_band():
    rows=[]
    for i in range(400):
        origin=datetime(2025,1,1)+timedelta(days=i)
        for h in (-1,0,1,2):
            target=origin+timedelta(days=h)
            x=(target-datetime(2025,1,1)).days
            actual=1000+x%40
            rows.append((origin,h,origin+timedelta(hours=14),"slot",target,actual if h==-1 else actual+30,
                         500,12,"fixture.xlsx","a"*64,"fixture",i+2,100+x%30,300,20))
    f=pd.DataFrame(rows,columns=(*FIELDS,*EXTRA_FIELDS))
    asof=datetime(2026,3,1,15)
    v,_=daily_vintages(f,asof)
    r=evaluate_extended(v,2,asof)
    assert r["n"]==90 and r["scores"]["official"]["mae"]==30
    assert r["scores"]["extended"]["mae"]<.001
    assert r["empirical"]["n"]>0
    assert all(pd.Timestamp(x["train_target_end"])+pd.Timedelta(days=1)<=pd.Timestamp(x["origin"]) for x in r["records"])
    with pytest.raises(ValueError):
        evaluate_extended(v.drop(columns=["exports"]),2,asof)
