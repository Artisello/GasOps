"""Comparable demand, supply and price facts at the native source frequency."""

import pandas as pd

from .data import period_text


def _change(current: float, previous: float) -> float | None:
    return None if previous == 0 else 100 * (current - previous) / abs(previous)


def _last(row: pd.Series, field: str) -> float | None:
    value = row.get(field)
    return None if pd.isna(value) else float(value)


def market_facts(data: pd.DataFrame, grain: str) -> dict:
    latest = data["demand_gwh"].last_valid_index()
    if latest is None:
        return {}
    row = data.loc[latest]
    demand, supply = _last(row, "demand_gwh"), _last(row, "supply_gwh")
    window = 7 if grain == "daily" else 1
    enough = 5 if window == 7 else 1
    through = data.loc[:latest]
    comparison = "vs prior 7 days" if grain == "daily" else "vs prior month"
    facts = {
        "period": latest.date().isoformat(), "label": period_text(latest, grain),
        "demand_gwh": demand, "supply_gwh": supply, "storage_gwh": _last(row, "storage_gwh"),
        "price_eur_mwh": _last(row, "price_eur_mwh"),
        "gap_gwh": supply - demand if supply is not None else None,
        "coverage_pct": 100 * supply / demand if supply is not None and demand else None,
        "comparison": comparison,
    }
    for field in ("demand_gwh", "supply_gwh", "price_eur_mwh"):
        deltas = None
        if len(through) >= 2 * window:
            current = through[field].iloc[-window:].to_numpy()
            prior = through[field].iloc[-2 * window:-window].to_numpy()
            paired = ~(pd.isna(current) | pd.isna(prior))
            if paired.sum() >= enough:
                deltas = _change(float(current[paired].mean()), float(prior[paired].mean()))
        facts[f"{field}_change_pct"] = deltas

    if grain == "daily":
        last_quarter = through["demand_gwh"].iloc[-84:]
        weekday = last_quarter[last_quarter.index.dayofweek < 5].dropna()
        weekend = last_quarter[last_quarter.index.dayofweek >= 5].dropna()
        if min(len(weekday), len(weekend)) >= 5:
            facts["weekend_vs_weekday_pct"] = _change(float(weekend.mean()), float(weekday.mean()))
    season = through["demand_gwh"].dropna().groupby(lambda day: day.month).mean()
    if len(season) == 12:
        facts["peak_month"] = pd.Timestamp(2020, int(season.idxmax()), 1).strftime("%B")
        facts["low_month"] = pd.Timestamp(2020, int(season.idxmin()), 1).strftime("%B")
    return facts
