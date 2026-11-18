"""Exploratory direct multi-horizon backtest with calendar-safe lags.

Historical final/revised values are not historical publication vintages.
All delays below are conservative modelling assumptions, not source SLAs.
"""
from dataclasses import dataclass
from datetime import date, timedelta
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

SECTORS=("distribution_gwh","industry_gwh","power_gwh")
MIN_TRAIN=45
HOLDOUT=28
MIN_TEST=14
GAS_LAG=2
EXTERNAL_LAG=7
MODELS=("weekly","autoregressive","multivariate")
HORIZONS=(1,3,7)
ALPHA=10.0


@dataclass(frozen=True)
class Covariate:
    name: str
    values: pd.Series
    unit: str
    scope: str
    source: str
    provenance: str


def _calendar(series):
    if not isinstance(series.index,pd.DatetimeIndex) or series.index.tz is not None:
        raise ValueError("Date giornaliere locali senza timezone richieste.")
    if series.index.has_duplicates or not series.index.equals(series.index.normalize()):
        raise ValueError("Date duplicate o non giornaliere.")
    s=pd.to_numeric(series,errors="raise").astype(float).sort_index()
    return s.where(np.isfinite(s))


def _days(frame):
    if not isinstance(frame.index,pd.DatetimeIndex) or frame.index.has_duplicates or frame.index.tz is not None or not frame.index.equals(frame.index.normalize()):
        raise ValueError("Indice domanda non giornaliero o duplicato.")
    if frame.empty or len(frame)>3000 or (frame.index.max()-frame.index.min()).days>3000:
        raise ValueError("Storico domanda assente o eccessivo.")
    if not {"demand_gwh",*SECTORS}<=set(frame):
        raise ValueError("Servono domanda e tre settori.")
    frame=frame[["demand_gwh",*SECTORS]].sort_index().apply(lambda s:_calendar(s).where(lambda v:v>=0))
    return frame.asfreq("D")


def origin_frame(frame,external,horizon,reference=None):
    """Index = model reference day; label = prelievi at reference + H.

    No forward fill, index compression, same-day exogenous values, or global
    scaling. For training at reference R, labels must be dated <= R-2.
    """
    if horizon not in HORIZONS or len(external)>4 or len({c.name for c in external})!=len(external):
        raise ValueError("Orizzonte o variabili non validi.")
    gas=_days(frame)
    last=gas["demand_gwh"].last_valid_index()
    if last is None:
        raise ValueError("Domanda non disponibile.")
    ref=pd.Timestamp(reference) if reference is not None else last+pd.Timedelta(days=GAS_LAG)
    if ref.tz is not None or ref!=ref.normalize() or ref>last+pd.Timedelta(days=GAS_LAG) or ref<gas.index.min():
        raise ValueError("Data di riferimento incompatibile con lo storico.")
    idx=pd.date_range(gas.index.min(),max(gas.index.max(),ref)+pd.Timedelta(days=horizon),freq="D")
    gas=gas.reindex(idx)
    target=idx+pd.Timedelta(days=horizon)
    result=pd.DataFrame(index=idx)
    result["actual"]=gas["demand_gwh"].shift(-horizon)
    # Use the most recent same-weekday target lag that is available by R-2.
    weekly_lag=7 if 7-horizon>=GAS_LAG else 14
    result["weekly"]=gas["demand_gwh"].shift(weekly_lag-horizon)
    result["lag2"]=gas["demand_gwh"].shift(GAS_LAG)
    result["lag7"]=gas["demand_gwh"].shift(7)
    result["mean7"]=gas["demand_gwh"].shift(GAS_LAG).rolling(7,min_periods=7).mean()
    angle=2*np.pi*(target-pd.Timestamp("2020-01-01")).days.to_numpy()/365.2425
    result["sin"]=np.sin(angle)
    result["cos"]=np.cos(angle)
    result["weekend"]=(target.dayofweek>=5).astype(float)
    ar=["lag2","lag7","mean7","sin","cos","weekend"]
    multi=ar.copy()
    for key in SECTORS:
        col=key+"_lag2"
        result[col]=gas[key].shift(GAS_LAG)
        multi.append(col)
    for i,c in enumerate(external):
        s=_calendar(c.values).reindex(idx)
        name=f"external_{i}"
        result[name]=s.shift(EXTERNAL_LAG)
        multi.append(name)
    return result,ar,multi,last,ref


def _fit(train,point,cols):
    model=make_pipeline(StandardScaler(),Ridge(alpha=ALPHA))
    model.fit(train[cols],train["actual"])
    prediction=float(model.predict(point[cols])[0])
    if not np.isfinite(prediction):
        raise ValueError("Previsione non finita.")
    return max(0.0,prediction)


def _scores(records):
    actual=np.array([r["actual"] for r in records],dtype=float)
    scores={}
    for model in MODELS:
        error=np.array([r[model] for r in records])-actual
        scores[model]={"mae":float(np.abs(error).mean()),"rmse":float(np.sqrt((error**2).mean())),
                       "bias":float(error.mean()),"wape":float(100*np.abs(error).sum()/actual.sum()) if actual.sum()>0 else None}
    return scores


def evaluate(frame,external=(),horizon=1,reference=None):
    features,ar,multi,last,ref=origin_frame(frame,external,horizon,reference)
    # Identical train and test samples for both Ridge models and weekly naive.
    columns=["actual","weekly",*multi]
    eligible=features.dropna(subset=columns)
    end=min(last-pd.Timedelta(days=horizon),ref-pd.Timedelta(days=1))
    start=end-pd.Timedelta(days=HOLDOUT-1)
    records=[]
    residuals=[]
    for origin in pd.date_range(start,end,freq="D"):
        if origin not in eligible.index:
            continue
        limit=origin-pd.Timedelta(days=horizon+GAS_LAG)
        train=eligible.loc[eligible.index<=limit]
        if len(train)<MIN_TRAIN:
            continue
        point=eligible.loc[[origin]]
        r={"origin":origin.date().isoformat(),"target":(origin+pd.Timedelta(days=horizon)).date().isoformat(),
           "train_target_end":(train.index.max()+pd.Timedelta(days=horizon)).date().isoformat(),
           "train_n":len(train),"actual":float(point["actual"].iloc[0]),"weekly":float(point["weekly"].iloc[0]),
           "autoregressive":_fit(train,point,ar),"multivariate":_fit(train,point,multi)}
        records.append(r)
    if len(records)<MIN_TEST:
        raise ValueError(f"Solo {len(records)}/{HOLDOUT} date valutabili; servono almeno {MIN_TEST} e {MIN_TRAIN} coppie di training per origine. Riduci le variabili o amplia lo storico.")
    scores=_scores(records)
    limit=ref-pd.Timedelta(days=horizon+GAS_LAG)
    train=eligible.loc[eligible.index<=limit]
    point=features.loc[[ref]]
    forecast=None
    if len(train)>=MIN_TRAIN and point[["weekly",*multi]].notna().all(axis=None):
        forecast={"origin":ref.date().isoformat(),"target":(ref+pd.Timedelta(days=horizon)).date().isoformat(),
                  "train_target_end":(train.index.max()+pd.Timedelta(days=horizon)).date().isoformat(),
                  "weekly":float(point["weekly"].iloc[0]),"autoregressive":_fit(train,point,ar),
                  "multivariate":_fit(train,point,multi)}
        # Empirical descriptive range, not calibrated coverage. No interval for
        # small samples and no auto-promoting a contender from this evaluation.
        if len(records)>=20:
            residuals=np.array([r["actual"]-r["multivariate"] for r in records])
            low,high=np.quantile(residuals,[.1,.9])
            estimate=forecast["multivariate"]
            forecast["empirical_low"]=max(0.,min(estimate,estimate+float(low)))
            forecast["empirical_high"]=max(estimate,estimate+float(high))
    return {"horizon":horizon,"last_observed":last.date().isoformat(),"reference":ref.date().isoformat(),
            "test_start":start.date().isoformat(),"test_end":end.date().isoformat(),"test_n":len(records),
            "scores":scores,"records":records,"forecast":forecast,
            "features":[*SECTORS,*[c.name for c in external]],"external_lag":EXTERNAL_LAG,"gas_lag":GAS_LAG}


def series_from_rows(rows,day_key,value_key):
    """One value per exact calendar label; conflicting duplicate dates fail."""
    values={}
    for row in rows:
        day=pd.Timestamp(row[day_key])
        val=row[value_key]
        val=float(val) if val is not None else np.nan
        if day in values and not (values[day]==val or np.isnan(values[day]) and np.isnan(val)):
            raise ValueError("Valori esterni in conflitto.")
        values[day]=val
    if not values:
        return pd.Series(dtype=float,index=pd.DatetimeIndex([]))
    return _calendar(pd.Series(values,dtype=float))
