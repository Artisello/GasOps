"""Comparable demand, supply and price facts at the native source frequency."""

import re
import pandas as pd

from .data import FIELDS, period_text
from .italiano import MESI, numero


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
    comparison = "sui 7 giorni precedenti" if grain == "daily" else "sul mese precedente"
    facts = {
        "period": latest.date().isoformat(), "label": period_text(latest, grain),
        **{field: _last(row, field) for field in FIELDS},
        "gap_gwh": supply - demand if supply is not None else None,
        "coverage_pct": 100 * supply / demand if supply is not None and demand else None,
        "comparison": comparison,
    }
    for field in FIELDS:
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
        facts["peak_month"] = MESI[int(season.idxmax()) - 1]
        facts["low_month"] = MESI[int(season.idxmin()) - 1]
    return facts


def demand_trend_question(question):
    """Narrow observational questions need no simulation, causal or forecast model."""
    return bool(re.search(r"\b(?:domanda|consum[oi])\b",question,re.I)
                and re.search(r"cambiat|variaz|andament|ultim|cresciut|diminuit|evoluz",question,re.I)
                and not re.search(r"perch[eéè]|caus|prevision|forecast|scenario|simul|settlement|prezz|offert|stoccagg|import|esport|correl|rispetto all.anno|ann[uo]al|confront.*paes",question,re.I))


def demand_readout(facts,grain):
    if not facts or facts.get("demand_gwh") is None:
        return None
    text=f"{facts['label']}: consumi osservati pari a {numero(facts['demand_gwh'])} GWh."
    change=facts.get("demand_gwh_change_pct")
    if change is not None:
        if grain=="daily":
            text+=" Variazione della media sui giorni confrontabili delle due finestre di 7 giorni: "+numero(change,1,signed=True)+"%."
        else:
            text+=" Variazione sul mese precedente: "+numero(change,1,signed=True)+"%."
    else:
        text+=" Variazione non disponibile per assenza di periodi confrontabili."
    return text
