"""Linepack diagnostics: publication revisions are not physical inventory change."""
from datetime import timedelta
from decimal import Decimal as D
import math
import pandas as pd
from .intraday import gas_end

REF="CdR XCII · cap. 9 §§3.1.1, 3.3.2 (pp. interne 9-15, 9-21–22)"
FIELD="expected_linepack_gwh"


def _finite(value):
    try:
        v=float(value)
    except (TypeError,ValueError,OverflowError):
        return None
    return v if math.isfinite(v) else None


def revisions(versions,day,now):
    """Only in-day, non-future publications; adjacent revisions, no fill.

    Publication coverage is an hourly diagnostic on the imported extract,
    not a certification of publisher obligations. UTC bins handle DST.
    """
    if now.utcoffset() is None:raise ValueError("Timestamp senza fuso.")
    start,end=gas_end(day-timedelta(days=1)),gas_end(day)
    cutoff=min(now,end)
    f=versions.loc[versions.gas_day==day,["published_at",FIELD]].copy()
    f["published_at"]=pd.to_datetime(f.published_at,utc=True)
    f=f[(f.published_at>=start)&(f.published_at<end)&(f.published_at<=cutoff)].sort_values("published_at")
    if f.published_at.duplicated().any():raise ValueError("Pubblicazioni duplicate.")
    complete_hours=max(0,int((cutoff-start).total_seconds()//3600))
    bins=set()
    detail=[]
    previous=None
    for t,v in f.itertuples(index=False,name=None):
        stamp=t.to_pydatetime()
        value=_finite(v)
        if value is not None and value<0:raise ValueError("Linepack atteso negativo.")
        elapsed=(stamp-start).total_seconds()/3600
        slot=int(elapsed)
        if value is not None and slot<complete_hours:bins.add(slot)
        old=previous["expected_gwh"] if previous else None
        gap=(stamp-previous["published_at"]).total_seconds()/3600 if previous else None
        change=value-old if value is not None and old is not None else None
        item={"published_at":stamp,"expected_gwh":value,"revision_gwh":change,"gap_hours":gap}
        detail.append(item)
        previous=item
    valid=[r for r in detail if r["expected_gwh"] is not None]
    latest=detail[-1] if detail else None
    values=[r["expected_gwh"] for r in valid]
    changes=[r for r in detail if r["revision_gwh"] is not None]
    return {"rows":detail,"latest":latest,"last_valid":valid[-1] if valid else None,
            "valid_count":len(valid),"complete_hours":complete_hours,"covered_hours":len(bins),
            "range_gwh":max(values)-min(values) if values else None,
            "largest_revision":max(changes,key=lambda r:abs(r["revision_gwh"])) if changes else None,
            "age_hours":(cutoff-latest["published_at"]).total_seconds()/3600 if latest else None,
            "historical":now>=end,"start":start,"end":end}


def physical_delta(day,now,opening,closing,reported=None,*,tolerance=D(".01")):
    """Independent boundary stock values in GWh; never use expected linepack."""
    if now.utcoffset() is None or gas_end(day)>now:
        raise ValueError("Serve un giorno gas concluso.")
    for value in (opening,closing,tolerance):
        if not isinstance(value,D) or not value.is_finite() or not 0<=value<=D("1e9"):
            raise ValueError("Valore non valido o negativo.")
    if reported is not None and (not isinstance(reported,D) or not reported.is_finite() or abs(reported)>D("1e9")):
        raise ValueError("ΔLPC dichiarato non valido.")
    delta=closing-opening
    difference=None if reported is None else delta-reported
    return {"delta":delta,"reported":reported,"difference":difference,
            "status":"Solo calcolo" if difference is None else "Entro tolleranza" if abs(difference)<=tolerance else "Da verificare"}


def balance_candidates(rows,day):
    """Do not conflate provisional/definitive or choose the newest silently."""
    out={}
    for row in rows:
        if row["gas_day"]!=day.isoformat():continue
        stage=row["stage"]
        if stage in out:raise ValueError("Fase duplicata.")
        out[stage]=row["delta_LPC"]
    return out
