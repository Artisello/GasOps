"""Local analyses over validated GME observations, isolated from production models."""
from dataclasses import replace
from datetime import date, timedelta
from statistics import quantiles

from .gas_calendar import closed_gas_day
from .gme_market import study_prices


def estimate_prices(rows, day, title_volume, rate, *, ordinary):
    current = next((row for row in rows if row["FlowDate"] == day.isoformat()), None)
    if current is None:
        raise ValueError("Parametri GME assenti per il giorno gas.")
    if current["MaxPurchaseSRGPrice"] is None or current["MinSaleSRGPrice"] is None:
        raise ValueError("Estremi SRG incompleti per il giorno gas. Verifica i prezzi applicati dalla fonte.")
    history = {date.fromisoformat(row["FlowDate"]): row["WeightedAveragePrice"] for row in rows
               if (day - timedelta(days=30)).isoformat() <= row["FlowDate"] < day.isoformat()
               and row["WeightedAveragePrice"] is not None}
    return study_prices(current, title_volume, rate, history, ordinary=ordinary)


def settlement_preview(snapshot, balance, title_volume, rate, *, ordinary):
    if (snapshot["origin"] != "api" or snapshot["kind"] != "prices"
            or balance.day > closed_gas_day(snapshot["acquired"])
            or balance.stage != "definitive"):
        raise ValueError("Servono un bilancio definitivo e parametri acquisiti dall’API per il giorno concluso.")
    prices = estimate_prices(snapshot["rows"], balance.day, title_volume, rate, ordinary=ordinary)
    theoretical = replace(balance, buy=prices["buy"], sell=prices["sell"])
    return prices, theoretical.cash


def price_backtest(snapshot, product):
    """Chronological holdout on a single vintage; not a point-in-time backtest."""
    if snapshot["origin"] != "api" or snapshot["kind"] != "igi":
        raise ValueError("Serve una serie IGI acquisita dall’API GME.")
    if snapshot["last"] > closed_gas_day(snapshot["acquired"]):
        raise ValueError("La serie include giorni non conclusi all’acquisizione.")
    series = {date.fromisoformat(row["FlowDate"]): row["Price"] for row in snapshot["rows"]
              if row["Product"] == product and row["Price"] is not None}
    test_start = snapshot["last"] - timedelta(days=6)
    train, test = [], []
    for day, price in sorted(series.items()):
        previous = day - timedelta(days=1)
        if previous in series:
            (train if day < test_start else test).append(price - series[previous])
    if len(train) < 14 or len(test) < 3:
        raise ValueError("Servono almeno 14 variazioni giornaliere per la calibrazione e 3 negli ultimi 7 giorni.")
    deciles = quantiles(train, n=10, method="inclusive")
    lower, upper = deciles[0], deciles[-1]
    return {"lower": lower, "upper": upper, "test_start": test_start,
            "train_days": len(train), "test_days": len(test),
            "covered_days": sum(lower <= move <= upper for move in test),
            "mae": sum(map(abs, test)) / len(test)}
