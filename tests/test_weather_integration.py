from datetime import date,datetime,timedelta,timezone
from unittest.mock import Mock
import pandas as pd
import pytest
from gasops_app import weather_source as w
from gasops_app.data_analyst import catalog,forecast_facts

NOW=datetime(2026,11,18,12,tzinfo=timezone.utc)

def frame(first,last):
    idx=pd.date_range(first,last)
    return pd.DataFrame({"hdd":8.,"temperature_c":10.,"hours":24},index=idx)


def test_enabled_default_independent_history_and_outlook(monkeypatch):
    monkeypatch.delenv("IGOR_WEATHER_ENABLED",raising=False)
    monkeypatch.setattr(w,"utc_now",lambda:NOW)
    mock=Mock(side_effect=lambda store,a,b,kind,**kw:(frame(a,b),NOW,False,False))
    monkeypatch.setattr(w,"fetch",mock)
    state={}
    assert w.enabled(state)
    assert w.refresh(state,None,NOW)==""
    assert mock.call_count==2
    w.refresh(state,None,NOW+timedelta(minutes=5))
    assert mock.call_count==2
    data,_=catalog(state,NOW)
    assert "weather_hdd" in data and data["weather_hdd"].values.index[-1]=="2026-11-11"
    fact=next(x for x in forecast_facts(state,NOW) if x["id"]=="weather_outlook")
    assert fact["from"]=="2026-11-19" and fact["n"]==7
    assert not w.outlook(state,NOW+timedelta(hours=13))
    state["briefing_weather"]=False
    assert "weather_hdd" not in catalog(state,NOW)[0]
    assert not w.outlook(state,NOW)


def test_failure_keeps_history_and_never_promotes_old_outlook(monkeypatch):
    monkeypatch.delenv("IGOR_WEATHER_ENABLED",raising=False)
    monkeypatch.setattr(w,"utc_now",lambda:NOW)
    mock=Mock(side_effect=lambda store,a,b,kind,**kw:(frame(a,b),NOW,False,False))
    monkeypatch.setattr(w,"fetch",mock)
    state={}
    w.refresh(state,None,NOW)
    mock.side_effect=ValueError("fixture failure")
    w.refresh(state,None,NOW+timedelta(minutes=2),force=True)
    assert w.archive(state,NOW)["failed"]
    assert not w.outlook(state,NOW)
    monkeypatch.setenv("IGOR_WEATHER_ENABLED","0")
    assert not w.enabled({})
