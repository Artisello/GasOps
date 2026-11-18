"""Gas-day aligned weather and sector scenarios. Independent from production forecast."""
from datetime import datetime, time, timedelta, timezone
import json

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from .data import ROME
from .models import utc_now
from .public_data import SourceUnavailable, SourceSchemaError, retrieve
from .weather import ARCHIVE, FORECAST, SOURCE, LOCATIONS, BASE_TEMP, features, available_periods

PREVIOUS = "https://previous-runs-api.open-meteo.com/v1/forecast"
SECTORS = ("distribution_gwh","industry_gwh","power_gwh")
LEAD_VAR = "temperature_2m_previous_day1"
# Equal-weight reference, not estimated regional consumption weights.
FOLDS, HOLDOUT, EMBARGO = 2, 28, 7


def boundary(day):
    return datetime.combine(day,time(6),ROME).astimezone(timezone.utc)


def hourly_weather(text, acquired, *, first,last,variable="temperature_2m",cached=False,failed=False):
    raw=json.loads(text)
    if not isinstance(raw,list) or len(raw)!=len(LOCATIONS):
        raise SourceSchemaError("Meteo: attese tre località")
    start,end=boundary(first),boundary(last+timedelta(days=1))
    # UTC input avoids missing/repeated local hours at DST.
    needed=pd.date_range(start,end,freq="h",inclusive="left")
    cities=[]
    for row,(lat,lon) in zip(raw,LOCATIONS,strict=True):
        if (abs(float(row["latitude"])-lat)>.75 or abs(float(row["longitude"])-lon)>.75
                or row.get("utc_offset_seconds")!=0):
            raise SourceSchemaError("Meteo: coordinate o offset UTC non validi")
        if row["hourly_units"][variable]!="°C":
            raise SourceSchemaError("Meteo: unità non riconosciuta")
        stamps=pd.to_datetime(row["hourly"]["time"],unit="s",utc=True,errors="raise")
        values=pd.to_numeric(pd.Series(row["hourly"][variable]),errors="raise").to_numpy(dtype=float)
        if len(stamps)!=len(values) or stamps.has_duplicates or not stamps.is_monotonic_increasing:
            raise SourceSchemaError("Meteo: asse orario non valido")
        if np.isinf(values).any() or ((values< -60)|(values>60)).any():
            raise SourceSchemaError("Meteo: temperatura non valida")
        if not needed.isin(stamps).all():
            raise SourceSchemaError("Meteo: ore del giorno gas mancanti")
        cities.append(pd.Series(values,index=stamps).reindex(needed).to_numpy())
    arr=np.column_stack(cities)
    days=pd.date_range(first,last,freq="D")
    records=[]
    for day in days:
        mask=(needed>=boundary(day.date()))&(needed<boundary(day.date()+timedelta(days=1)))
        hours=arr[mask]
        valid=np.isfinite(hours).all()
        means=hours.mean(axis=0) if valid else np.full(len(LOCATIONS),np.nan)
        records.append({"temperature_c":float(means.mean()),
                        "hdd":float(np.maximum(BASE_TEMP-means,0).mean()),
                        "hours":len(hours)})
    frame=pd.DataFrame(records,index=days)
    if not frame["hdd"].notna().any():
        raise SourceSchemaError("Meteo: nessun giorno gas completo")
    return frame,acquired,cached,failed


def fetch(store,first,last,kind,*,refresh=False):
    url={"era5":ARCHIVE,"forecast":FORECAST,"previous":PREVIOUS}[kind]
    variable=LEAD_VAR if kind=="previous" else "temperature_2m"
    params={"latitude":",".join(str(x[0]) for x in LOCATIONS),
            "longitude":",".join(str(x[1]) for x in LOCATIONS),
            "hourly":variable,"timeformat":"unixtime","timezone":"GMT",
            "start_date":boundary(first).date().isoformat(),
            "end_date":(boundary(last+timedelta(days=1))-timedelta(hours=1)).date().isoformat()}
    if kind=="era5":
        params["models"]="era5"
    def parse(text,acquired,**kwargs):
        return hourly_weather(text,acquired,first=first,last=last,variable=variable,**kwargs)
    return retrieve(store,key=f"weather-gas-v2-{kind}-{first}-{last}",name="Open-Meteo "+kind,
                    url=url,parse=parse,ttl=timedelta(hours=6 if kind=="forecast" else 24),
                    attempts=1,timeout=(5,25),diagnostics=True,max_bytes=2_000_000,
                    params=params,refresh=refresh and kind=="forecast")


def _predict(train, target, use_hdd, sector):
    cols=list(SECTORS) if sector else ["demand_gwh"]
    x=features(train.index,train["hdd"] if use_hdd else None)
    z=features(target.index,target["hdd"] if use_hdd else None)
    model=Ridge(alpha=2.).fit(x,train[cols].to_numpy())
    pred=np.maximum(np.asarray(model.predict(z),dtype=float).reshape(len(target),len(cols)),0)
    if not np.isfinite(pred).all():
        raise ValueError("Previsione meteo non finita")
    return pred


def evaluate(demand,hist,future,previous=None):
    """Two held-out calendar blocks, embargo approximates ERA5 availability.

    Previous-day1 is a fixed per-hour lead, not a common operational issuance.
    No claim of archived demand vintages or end-to-end 7-day skill.
    """
    cols=["demand_gwh",*SECTORS]
    joined=hist.join(demand[cols],how="inner").sort_index()
    valid=joined[["hdd",*cols]].notna().all(axis=1)
    valid &= np.isfinite(joined[["hdd",*cols]]).all(axis=1)
    valid &= (joined[cols]>=0).all(axis=1)
    valid &= np.isclose(joined[list(SECTORS)].sum(axis=1),joined["demand_gwh"],rtol=1e-8,atol=1e-5)
    joined=joined.loc[valid]
    if joined.index.has_duplicates or future.index.has_duplicates or len(future)!=7 or future["hdd"].isna().any():
        raise ValueError("Date o temperature meteo non valide")
    if len(joined)<120+FOLDS*HOLDOUT+EMBARGO or future.index.min()<=joined.index.max():
        raise ValueError("Servono almeno 183 giorni completi meteo e prelievi settoriali")
    # Last 56 calendar days; never compress missing gas days into a fake timeline.
    end=joined.index.max()
    specs={"calendar":(False,False),"aggregate_weather":(True,False),
           "sector_calendar":(False,True),"sector_weather":(True,True)}
    errors={k:[] for k in specs}
    sector_errors={k:[] for k in ("sector_calendar","sector_weather")}
    conditional={k:[] for k in ("aggregate_weather","sector_weather")}
    count=0
    fold_info=[]
    for fold in range(FOLDS):
        stop=end-pd.Timedelta(days=(FOLDS-fold-1)*HOLDOUT)
        start=stop-pd.Timedelta(days=HOLDOUT-1)
        train=joined.loc[joined.index<start-pd.Timedelta(days=EMBARGO)]
        test=joined.loc[(joined.index>=start)&(joined.index<=stop)]
        if previous is not None:
            test=test.loc[test.index.intersection(previous.index)]
            test=test.loc[previous["hdd"].reindex(test.index).notna()]
        if len(train)<120 or len(test)<21:
            raise ValueError("Copertura insufficiente in una finestra di verifica")
        target=test.copy()
        if previous is not None:
            target["hdd"]=previous["hdd"].reindex(test.index)
        actual=test["demand_gwh"].to_numpy()
        for name,(weather,sector) in specs.items():
            prediction=_predict(train,target,weather,sector)
            errors[name].extend(np.abs(prediction.sum(axis=1)-actual))
            if sector:
                sector_errors[name].extend(np.abs(prediction-test[list(SECTORS)].to_numpy()))
            if weather:
                realized=_predict(train,test,True,sector)
                conditional[name].extend(np.abs(realized.sum(axis=1)-actual))
        count+=len(test)
        fold_info.append({"train_end":train.index.max().date().isoformat(),"test_start":start.date().isoformat(),
                          "test_end":stop.date().isoformat(),"observations":len(test)})
    mae={k:float(np.mean(v)) for k,v in errors.items()}
    realized_mae={k:float(np.mean(v)) for k,v in conditional.items()}
    sector_mae={k:{c:float(v) for c,v in zip(SECTORS,np.mean(np.asarray(vals),axis=0),strict=True)}
                for k,vals in sector_errors.items()}
    # No model promotion on this shared evaluation set. Always show the
    # explicitly labelled sector scenario and baseline, not a chosen winner.
    baseline=_predict(joined,future,False,False).ravel()
    pred=_predict(joined,future,True,True)
    points=[{"period":d.date().isoformat(),"temperature_c":float(future.loc[d,"temperature_c"]),
             "hdd":float(future.loc[d,"hdd"]),"hours":int(future.loc[d,"hours"]),
             "calendar_gwh":float(b),"estimate_gwh":float(p.sum()),
             **{c:float(v) for c,v in zip(SECTORS,p,strict=True)}}
            for d,b,p in zip(future.index,baseline,pred,strict=True)]
    return {"observations":len(joined),"holdout":count,"folds":fold_info,"mae":mae,
            "realized_mae":realized_mae,"sector_mae":sector_mae,"points":points,
            "train_end":joined.index.max().date().isoformat(),
            "evaluation":"archived_day1" if previous is not None else "realized_only"}


def analyse_gas_day(store,demand,now=None,*,refresh=False,snapshots=None):
    now=now or utc_now()
    first,last,fstart,fend=available_periods(demand["demand_gwh"],now)
    # ERA5 delay plus next day's early UTC hours needed for the gas day.
    last=min(last,now.astimezone(ROME).date()-timedelta(days=7))
    def get(kind,a,b):
        item=(snapshots or {}).get(kind)
        if item and not refresh and not item["failed"] and timedelta(0)<=now-item["acquired"]<=timedelta(hours=12 if kind=="forecast" else 24):
            frame=item["frame"].loc[str(a):str(b)]
            if frame.index.equals(pd.date_range(a,b,freq="D")):
                return frame,item["acquired"],item["cached"],item["failed"]
        return fetch(store,a,b,kind,refresh=refresh and kind=="forecast")
    hist,ha,hc,hf=get("era5",first,last)
    future,fa,fc,ff=get("forecast",fstart,fend)
    if now-fa>timedelta(hours=12):
        raise SourceUnavailable("Previsione meteo in cache troppo vecchia")
    previous=None
    previous_note=None
    try:
        previous,pa,pc,pf=fetch(store,last-timedelta(days=FOLDS*HOLDOUT-1),last,"previous")
        if previous["hdd"].notna().sum()<42:
            raise ValueError("Copertura archivio previsioni insufficiente")
    except (SourceUnavailable,ValueError):
        previous_note="Archivio previsioni a 24 ore non disponibile: confronto solo condizionale."
        previous=None
    try:
        result=evaluate(demand,hist,future,previous)
    except ValueError as exc:
        if previous is None or "Copertura insufficiente" not in str(exc):
            raise
        previous_note="Archivio a 24 ore insufficiente nelle finestre comuni: confronto solo condizionale."
        result=evaluate(demand,hist,future)
    result.update({"source":SOURCE,"historical_acquired":ha.isoformat(),"forecast_acquired":fa.isoformat(),
                   "historical_end":last.isoformat(),"refresh_failed":hf or ff,
                   "historical_cache":hc,"forecast_cache":fc,"previous_note":previous_note})
    return result
