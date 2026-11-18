from datetime import date,datetime,timezone
import json

import numpy as np
import pandas as pd
import pytest

from gasops_app.weather import LOCATIONS,parse_weather,conditional_scenario,available_periods

NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)

def payload():
    return [{"latitude":a,"longitude":b,"timezone":"Europe/Rome",
             "daily_units":{"temperature_2m_mean":"°C"},
             "daily":{"time":["2026-11-01","2026-11-02"],"temperature_2m_mean":[t,None]}}
            for (a,b),t in zip(LOCATIONS,[10,20,15],strict=True)]

def test_weather_units_alignment_and_missing():
    frame,*_=parse_weather(json.dumps(payload()),NOW,first=date(2026,11,1),last=date(2026,11,2))
    assert frame.iloc[0]["temperature_c"]==15
    assert frame.iloc[0]["hdd"]==pytest.approx(11/3)
    assert pd.isna(frame.iloc[1]["hdd"])
    raw=payload()
    raw[0]["daily_units"]["temperature_2m_mean"]="°F"
    with pytest.raises(ValueError,match="Unità"):
        parse_weather(json.dumps(raw),NOW,first=date(2026,11,1),last=date(2026,11,2))

def test_weather_signal_and_no_signal():
    dates=pd.date_range("2025-11-01",periods=365,freq="D")
    hdd=np.random.default_rng(9).uniform(0,15,len(dates))
    history=pd.DataFrame({"hdd":hdd},index=dates)
    future=pd.DataFrame({"hdd":np.arange(7)+1.,"temperature_c":np.arange(7)+8.},
                        index=pd.date_range(dates[-1]+pd.Timedelta(1, unit="D"),periods=7,freq="D"))
    r=conditional_scenario(pd.Series(800+60*hdd,index=dates),history,future)
    assert r["improved"] and len(r["points"])==7
    assert r["mae"]["weather"]<r["mae"]["calendar"]
    r=conditional_scenario(pd.Series(1000.,index=dates),history,future)
    assert not r["improved"] and not r["points"]

def test_stale_and_short_history():
    with pytest.raises(ValueError,match="recente"):
        available_periods(pd.Series([2.],index=pd.DatetimeIndex(["2022-01-01"])),NOW)
    with pytest.raises(ValueError,match="breve"):
        available_periods(pd.Series([2.],index=pd.DatetimeIndex(["2026-11-16"])),NOW)
    dates=pd.date_range("2025-11-01","2026-11-16")
    assert available_periods(pd.Series(1.,index=dates),NOW)[1]==date(2026,11,12)
