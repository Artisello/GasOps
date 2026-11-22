"""Presentation-only helpers for published operational data."""
from datetime import timedelta
import math

import pandas as pd


def scope_label(scope):
    return {"IT":"Italia","EU":"Unione europea (aggregato GIE)"}[scope]


def finite(value):
    try:
        v=float(value)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError):
        return None


def inventory_snapshot(frame,platform):
    """One observation date for all headline indicators; no forward fill."""
    measures=["stock_twh"] if platform=="AGSI+" else [
        "sendout_gwh_d","inventory_1000m3_lng","inventory_gwh"]
    if frame.empty or not set(measures+["gas_day"]).issubset(frame.columns):
        raise ValueError("Nessun dato utilizzabile per il riepilogo.")
    valid=frame.loc[frame[measures].apply(lambda column: column.map(finite)).notna().any(axis=1)
                    & frame["gas_day"].notna()].sort_values("gas_day")
    if valid.empty:
        raise ValueError("Nessun dato utilizzabile per il riepilogo.")
    if valid["gas_day"].duplicated().any():
        raise ValueError("Più osservazioni per giorno gas: verificare la fonte.")
    latest=valid.iloc[-1]
    prior=frame.loc[frame["gas_day"]==latest["gas_day"]-timedelta(days=7)]
    changes={}
    for field in measures+["fill_pct","withdrawal_gwh_d","injection_gwh_d"]:
        if field not in frame or prior.empty:
            continue
        old=finite(prior.iloc[0][field])
        new=finite(latest[field])
        if old is not None and new is not None:
            changes[field]=new-old
    return latest,changes


def chart_window(frame,days):
    """Calendar window ending on the last returned day; missing days stay gaps."""
    series=frame.copy().set_index("gas_day")
    series.index=pd.to_datetime(series.index)
    last=series.index.max()
    index=pd.date_range(last-pd.Timedelta(days-1, unit="D"),last,freq="D")
    return series.reindex(index)
