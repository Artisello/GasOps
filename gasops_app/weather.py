"""Optional, zero-key weather context for the non-commercial demo.

Three equal-weight city proxies, not a national demand-weighted temperature.
Daily civil-day weather is intentionally not represented as gas-day metering.
The conditional holdout uses realised/reanalysis weather, not archived forecasts.
"""
from datetime import date, datetime, timedelta
import json

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from .data import ROME
from .models import utc_now
from .public_data import SourceUnavailable, retrieve

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST = "https://api.open-meteo.com/v1/forecast"
SOURCE = "https://open-meteo.com/"
LOCATIONS = ((45.46,9.19),(41.90,12.50),(40.85,14.27))
BASE_TEMP = 18.0


def parse_weather(text, acquired, *, first, last, cached=False, failed=False):
    payload = json.loads(text)
    if not isinstance(payload,list) or len(payload)!=len(LOCATIONS):
        raise ValueError("Attese tre località Open-Meteo.")
    target = pd.date_range(first,last,freq="D")
    columns = []
    for item,(lat,lon) in zip(payload,LOCATIONS,strict=True):
        if (abs(float(item["latitude"])-lat)>.75 or abs(float(item["longitude"])-lon)>.75
                or item["timezone"]!="Europe/Rome"):
            raise ValueError("Coordinate o fuso orario non riconosciuti.")
        if item["daily_units"]["temperature_2m_mean"]!="°C":
            raise ValueError("Unità di temperatura diversa da °C.")
        daily=item["daily"]
        dates=pd.DatetimeIndex(pd.to_datetime(daily["time"],format="%Y-%m-%d",errors="raise"))
        values=pd.to_numeric(pd.Series(daily["temperature_2m_mean"]),errors="raise").to_numpy(dtype=float)
        if len(dates)!=len(values) or dates.has_duplicates or not dates.equals(target):
            raise ValueError("Asse temporale meteo incompleto.")
        if np.isinf(values).any() or ((values< -60)|(values>60)).any():
            raise ValueError("Temperatura non valida.")
        columns.append(values)
    temperatures=np.column_stack(columns)
    # Average HDD across cities, not HDD computed on the average temperature.
    hdd=np.maximum(BASE_TEMP-temperatures,0).mean(axis=1)
    frame=pd.DataFrame({"temperature_c":temperatures.mean(axis=1),"hdd":hdd},index=target)
    if frame["hdd"].notna().sum()==0:
        raise ValueError("Temperature non disponibili.")
    return frame, acquired, cached, failed


def _get(store, url, first, last, *, future=False):
    def parse(text,acquired,**kwargs):
        return parse_weather(text,acquired,first=first,last=last,**kwargs)
    params={"latitude":",".join(str(x[0]) for x in LOCATIONS),
            "longitude":",".join(str(x[1]) for x in LOCATIONS),
            "daily":"temperature_2m_mean","timezone":"Europe/Rome",
            "start_date":first.isoformat(),"end_date":last.isoformat()}
    if not future:
        params["models"]="era5"
    kind="forecast" if future else "era5"
    return retrieve(store,key=f"weather-v1-{kind}-{first}-{last}",name="Open-Meteo",
                    url=url,parse=parse,ttl=timedelta(hours=6 if future else 24),
                    params=params,attempts=1)


def available_periods(series, now):
    today=now.astimezone(ROME).date()
    latest=series.last_valid_index()
    if latest is None or not 0 <= (today-latest.date()).days <= 5:
        raise ValueError("Serve una serie giornaliera recente (ultimo dato entro cinque giorni).")
    first=max(series.index.min().date(),today-timedelta(days=365))
    # ERA5 updates with a lag; do not substitute forecast values into history.
    last=min(latest.date(),today-timedelta(days=6))
    if (last-first).days<119:
        raise ValueError("Storico meteo/domanda troppo breve (almeno 120 giorni).")
    return first,last,today+timedelta(days=1),today+timedelta(days=7)


def features(index, hdd=None):
    angle=2*np.pi*(index-pd.Timestamp("2020-01-01")).days.to_numpy()/365.2425
    terms=[np.sin(angle),np.cos(angle),np.sin(2*angle),np.cos(2*angle)]
    terms.extend((index.dayofweek==d).astype(float) for d in range(6))
    if hdd is not None:
        terms.append(np.asarray(hdd,dtype=float))
    return np.column_stack(terms)


def conditional_scenario(series, historical, future):
    """Calendar Ridge vs calendar + HDD; same chronological holdout.

    Holdout is conditional on historical realised weather; NOT a fair live
    model-selection score versus operational/archived weather forecasts.
    """
    joined=historical.join(series.rename("demand"),how="inner").dropna(subset=["hdd","demand"]).sort_index()
    joined=joined[np.isfinite(joined["demand"]) & (joined["demand"]>=0)]
    if len(joined)<120:
        raise ValueError("Meno di 120 giorni completi meteo/prelievi.")
    if joined.index.has_duplicates or future.index.has_duplicates or future.index.min()<=joined.index.max():
        raise ValueError("Date meteo/domanda incoerenti.")
    train,test=joined.iloc[:-28],joined.iloc[-28:]
    if train["hdd"].std()<.5 or test["hdd"].std()<.25:
        raise ValueError("Variabilità termica insufficiente per il confronto.")
    if len(future)!=7 or future["hdd"].isna().any():
        raise ValueError("Sette giorni di meteo futuro completi necessari.")
    def fit(frame,with_hdd):
        return Ridge(alpha=2.).fit(features(frame.index,frame["hdd"] if with_hdd else None),frame["demand"])
    errors={}
    for name,with_hdd in (("calendar",False),("weather",True)):
        model=fit(train,with_hdd)
        pred=np.maximum(model.predict(features(test.index,test["hdd"] if with_hdd else None)),0)
        errors[name]=float(np.mean(np.abs(test["demand"].to_numpy()-pred)))
    output={"observations":len(joined),"holdout":len(test),"mae":errors,
            "train_end":joined.index.max().date().isoformat(),"test_end":test.index.max().date().isoformat(),
            "improved":errors["weather"]<errors["calendar"],"points":[]}
    # Do not advertise an alternative scenario where the weather variable
    # fails even this limited conditional comparison.
    if output["improved"]:
        model=fit(joined,True)
        prediction=np.maximum(model.predict(features(future.index,future["hdd"])),0)
        if not np.isfinite(prediction).all():
            raise ValueError("Scenario meteo non finito.")
        output["points"]=[{"period":d.date().isoformat(),"temperature_c":float(t),"hdd":float(h),
                            "estimate_gwh":float(p)}
                          for d,t,h,p in zip(future.index,future["temperature_c"],future["hdd"],prediction,strict=True)]
    return output


def analyse(store, series, now:datetime|None=None):
    now=now or utc_now()
    first,last,fstart,fend=available_periods(series,now)
    hist,ha,hcached,hfailed=_get(store,ARCHIVE,first,last)
    future,fa,fcached,ffailed=_get(store,FORECAST,fstart,fend,future=True)
    if now-fa>timedelta(hours=12):
        raise SourceUnavailable("Previsione meteo in cache troppo vecchia.")
    result=conditional_scenario(series,hist,future)
    result.update({"historical_acquired":ha.isoformat(),"forecast_acquired":fa.isoformat(),
                   "historical_cache":hcached,"forecast_cache":fcached,"refresh_failed":hfailed or ffailed,
                   "source":SOURCE,"historical_end":last.isoformat()})
    return result
