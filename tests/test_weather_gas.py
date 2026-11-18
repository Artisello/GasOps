from datetime import date,datetime,timedelta,timezone
import json

import numpy as np
import pandas as pd
import pytest

from gasops_app.weather_gas import boundary,hourly_weather,evaluate,SECTORS,LOCATIONS

NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)

@pytest.mark.parametrize("day,hours",[(date(2026,3,28),23),(date(2026,10,24),25),(date(2026,11,16),24)])
def test_gas_day_hours_dst(day,hours):
    stamps=pd.date_range(boundary(day),boundary(day+timedelta(days=1)),freq="h",inclusive="left")
    raw=[{"latitude":lat,"longitude":lon,"utc_offset_seconds":0,"hourly_units":{"temperature_2m":"°C"},
          "hourly":{"time":[int(t.timestamp()) for t in stamps],"temperature_2m":[10]*hours}}
         for lat,lon in LOCATIONS]
    frame,*_=hourly_weather(json.dumps(raw),NOW,first=day,last=day)
    assert frame.iloc[0]["hours"]==hours and frame.iloc[0]["hdd"]==8
    raw[0]["hourly"]["time"].pop()
    raw[0]["hourly"]["temperature_2m"].pop()
    with pytest.raises(ValueError,match="ore"):
        hourly_weather(json.dumps(raw),NOW,first=day,last=day)


def fixture():
    idx=pd.date_range("2025-11-01",periods=360)
    hdd=np.random.default_rng(42).uniform(0,18,len(idx))
    data=pd.DataFrame({SECTORS[0]:700+40*hdd,SECTORS[1]:300+4*hdd,SECTORS[2]:500+9*hdd},index=idx)
    data["demand_gwh"]=data.sum(axis=1)
    hist=pd.DataFrame({"hdd":hdd},index=idx)
    future=pd.DataFrame({"hdd":[8.]*7,"temperature_c":[10.]*7,"hours":[24]*7},
                        index=pd.date_range(idx[-1]+pd.Timedelta(days=8),periods=7))
    return data,hist,future


def test_sector_scenario_reconciles_and_archived_forecast_is_used():
    data,hist,future=fixture()
    previous=hist.copy()
    previous["hdd"]+=2
    result=evaluate(data,hist,future,previous)
    assert result["evaluation"]=="archived_day1"
    assert result["holdout"]==56 and len(result["points"])==7
    assert result["mae"]["sector_weather"]<result["mae"]["calendar"]
    assert result["mae"]["sector_weather"]>result["realized_mae"]["sector_weather"]
    for row in result["points"]:
        assert row["estimate_gwh"]==pytest.approx(sum(row[c] for c in SECTORS))
    for fold in result["folds"]:
        assert (date.fromisoformat(fold["test_start"])-date.fromisoformat(fold["train_end"])).days>=8


def test_conditional_fallback_and_no_imputation():
    data,hist,future=fixture()
    data.loc[data.index[-1],SECTORS[0]]=np.nan
    result=evaluate(data,hist,future)
    assert result["evaluation"]=="realized_only" and result["observations"]==359
    future.iloc[0,future.columns.get_loc("hdd")]=np.nan
    with pytest.raises(ValueError):
        evaluate(data,hist,future)
