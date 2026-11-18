from datetime import datetime,date,timedelta,timezone
import numpy as np
import pandas as pd
import pytest
from gasops_app.terna_history import make_batch,merge,parse,export,store_batch,read_db,windows
from gasops_app.snam_forecast import FIELDS,EXTRA_FIELDS,daily_vintages
from gasops_app.snam_power_forecast import join_power,evaluate
from gasops_app.snam_forecast import samples

UTC=timezone.utc


def fixture_batch(day,acquired,thermal=30):
    from gasops_app.data import ROME
    from datetime import time
    start=datetime.combine(day,time(6),ROME).astimezone(UTC)
    finish=datetime.combine(day+timedelta(days=1),time(6),ROME).astimezone(UTC)
    n=int((finish-start).total_seconds()/3600)
    rows=[{"gas_day":day.isoformat(),"metric":m,"gwh":v,"valid_slots":n*(4 if m=="load" else 1),"expected_slots":n*(4 if m=="load" else 1)}
          for m,v in (("Thermal",thermal),("Wind",20),("Photovoltaic",10),("load",90))]
    rows.append({"gas_day":day.isoformat(),"metric":"load_forecast","gwh":99,"valid_slots":n*4,"expected_slots":n*4})
    return make_batch({"first":day,"last":day,"acquired":acquired.isoformat(),"rows":rows},acquired)


def test_portable_and_private_archive(tmp_path):
    d=date(2026,3,28)
    now=datetime(2026,4,1,12,tzinfo=UTC)
    b=fixture_batch(d,now)
    assert b["rows"][0]["slots"]==23
    assert len(b["rows"])==4
    assert parse(export([b,b]).encode(),now)==[b]
    path=tmp_path/"private.sqlite3"
    store_batch(path,b);store_batch(path,b)
    b2=fixture_batch(d,now+timedelta(days=1),35)
    store_batch(path,b2)
    assert read_db(path)==merge([b],[b2])
    with pytest.raises(ValueError):parse(export([b2]).encode(),now)
    assert len(list(windows(date(2025,1,1),date(2025,1,15))))==2


def fixture():
    rows=[];batches=[]
    start=datetime(2025,1,1)
    for i in range(340):
        origin=start+timedelta(days=i)
        for h in (-1,0,1,2):
            target=origin+timedelta(days=h)
            n=(target-start).days
            actual=1000+20*np.sin(n/3)
            rows.append((origin,h,origin+timedelta(hours=14),"slot",target,actual if h==-1 else 1000,500,12,
                         "fixture","a"*64,"fixture",i+2,100,200,10))
        day=origin.date()-timedelta(days=3)
        batches.append(fixture_batch(day,(origin-timedelta(hours=1)).replace(tzinfo=UTC),100+20*np.sin((i+2)/3)))
    asof=datetime(2026,1,1,15)
    vintages,_=daily_vintages(pd.DataFrame(rows,columns=(*FIELDS,*EXTRA_FIELDS)),asof)
    return vintages,batches,asof


def test_join_never_uses_target_or_future_acquisition():
    v,bs,asof=fixture()
    d=samples(v,2).tail(1)
    day=(d.iloc[0].origin-pd.Timedelta(days=3)).date()
    late=fixture_batch(day,datetime(2025,12,31,10,tzinfo=UTC),900)
    strict,_=join_power(d,[late],asof,strict=True,load=True)
    assert strict.power_Thermal.isna().all()
    retrospective,_=join_power(d,[late],asof,strict=False,load=True)
    assert retrospective.power_Thermal.iloc[0]==900
    assert retrospective.power_day.iloc[0]==day.isoformat()


def test_power_common_sample():
    v,bs,asof=fixture()
    r=evaluate(v,bs,2,asof,strict=True,load=True)
    assert r["n"]==90
    assert r["scores"]["power"]["mae"]<r["scores"]["extended"]["mae"]
    assert all(pd.Timestamp(x["power_day"])==pd.Timestamp(x["origin"])-pd.Timedelta(days=3) for x in r["records"])
    with pytest.raises(ValueError,match="giorni con dati comuni"):
        evaluate(v,bs[:14],2,asof,strict=True,load=True)
