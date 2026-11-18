"""Deterministic educational controls for the reviewed regulatory editions.
All money is Decimal; no official invoices, market orders, or access decisions.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping

from .operations_ledger import BalanceRow, monthly_preview, monetary

D = Decimal
PRICE_REF = "CdR XCII, cap. 9 §4.4.1, PDF pp. 392–394"
BILL_REF = "CdR XCII, cap. 18 §4.1.2, PDF pp. 588–589"
EPS_REF = "CdR XCII, cap. 5 §§1.4.1, 1.4.4–1.4.5"
LNG_REF = "CdRig Piombino 2023-I, cap. 9 e allegato 14/A"


def finite(value):
    if not isinstance(value, D) or not value.is_finite():
        raise ValueError("Valore decimale mancante o non valido.")
    return value


def imbalance_prices(day: date, title_mwh: D, market_mean: D | None,
                     tso_buy_max: D | None, tso_sell_min: D | None,
                     adjustment_pct: D | None,
                     history: Mapping[date, D] | None = None,
                     *, ordinary: bool = True) -> dict:
    """Standard regime only, with supplied published percentage and both extrema.
    The percentage is NOT inferred from Euribor; no absent-action policy guessed.
    """
    if not ordinary:
        raise ValueError("Regime speciale: applicare le disposizioni specifiche con revisione umana.")
    if finite(title_mwh) < 0:
        raise ValueError("Volume title non valido.")
    if title_mwh < D(2000):
        expected = {day-timedelta(days=i) for i in range(1,31)}
        if history is None or set(history) != expected:
            raise ValueError("Servono esattamente i prezzi medi dei 30 giorni precedenti.")
        mean = sum((finite(v) for v in history.values()), D(0))/D(30)
        method = "Media 30 giorni precedenti"
    else:
        mean = finite(market_mean)
        method = "Prezzo medio di remunerazione del giorno"
    if mean < 0:
        raise ValueError("Prezzo medio negativo: verificare interpretazione dello small adjustment.")
    if day <= date(2025,9,30):
        raise ValueError("Periodo storico escluso: verificare regime e validità della revisione.")
    rate = finite(adjustment_pct)
    if not D(0) <= rate <= D(10):
        raise ValueError("Percentuale pubblicata non valida (0–10%).")
    buy, sell = finite(tso_buy_max), finite(tso_sell_min)
    if buy < sell:
        raise ValueError("Estremi TSO incoerenti: richiedono verifica.")
    sa = mean*rate/D(100)
    return {"mean":mean, "adjustment":sa, "buy":max(buy,mean+sa),
            "sell":min(sell,mean-sa), "method":method, "reference":PRICE_REF}


@dataclass(frozen=True)
class Invoice:
    identifier: str
    user: str
    year: int
    month: int
    group: str
    amount: D
    issue_date: date


def reconcile(rows: list[BalanceRow], invoices: list[Invoice], user: str,
              year: int, month: int) -> list[dict]:
    """Demo pre-tax comparison of separately grouped DS amounts; no netting."""
    preview = monthly_preview(rows,user,year,month)
    if preview["status"] != "SIMULATION_ONLY":
        raise ValueError("Bilanci definitivi incompleti o eccezioni: riconciliazione bloccata.")
    selected = [i for i in invoices if (i.user,i.year,i.month)==(user,year,month)]
    if len({i.identifier for i in selected}) != len(selected):
        raise ValueError("Identificativo fattura duplicato.")
    if any(i.group not in ("short","long") or finite(i.amount)<0 for i in selected):
        raise ValueError("Tipo di partita o importo non valido.")
    out = []
    for group, days in (("short",15),("long",30)):
        expected = preview[group+"_group_eur"]
        matches = [i for i in selected if i.group == group]
        observed = sum((i.amount for i in matches),D(0)) if len(matches)==1 else None
        status = ("NON DOVUTA" if expected==0 and not matches else
                  "MANCANTE" if not matches else "MULTIPLA · VERIFICA" if len(matches)>1 else
                  "QUADRA" if observed==expected else "DIFFERENZA")
        out.append({"group":group, "expected":expected, "observed":observed,
                    "delta":None if observed is None else observed-expected,
                    "status":status, "invoice":matches[0].identifier if len(matches)==1 else None,
                    "due":matches[0].issue_date+timedelta(days=days) if len(matches)==1 else None,
                    "reference":BILL_REF})
    return out


def exposure(pfat:D,pdet:D,patt:D,meps:D) -> dict:
    """Monitor supplied, already validated components (VAT included where applicable)."""
    total = sum(map(finite,(pfat,pdet,patt)),D(0))
    if finite(meps)<=0:
        raise ValueError("MEPSu non positivo: verifica manuale necessaria.")
    ratio = total/meps*100
    return {"eps":total,"meps":meps,"headroom":meps-total,"ratio":ratio,
            "status":"LIMITE" if total>=meps else "ATTENZIONE" if total>=meps*D(".90") else "OK",
            "reference":EPS_REF}


def working_offset(anchor:date, days:int, holidays:set[date]) -> date:
    """Exclude anchor, weekends and explicit calendar dates supplied by operator."""
    step = 1 if days>=0 else -1
    cursor = anchor
    for _ in range(abs(days)):
        cursor += timedelta(days=step)
        while cursor.weekday()>=5 or cursor in holidays:
            cursor += timedelta(days=step)
    return cursor


def lng_deadlines(month_start:date, acceptance:date|None, holidays:set[date]) -> list[dict]:
    if month_start.day!=1:
        raise ValueError("Indicare il primo giorno del mese.")
    return [{"task":"Accettazione/rifiuto scambio di capacità","due":working_offset(month_start,-9,holidays),"reference":LNG_REF},
            {"task":"Accettazione programma consegne","due":working_offset(month_start,-7,holidays),"reference":LNG_REF},
            {"task":"Comunicazione programma riconsegna","due":None if acceptance is None else working_offset(acceptance,1,holidays),"reference":LNG_REF}]


def demo_invoices() -> list[Invoice]:
    return [Invoice("DEMO-FT-01","DEMO-001",2026,9,"short",D("168000"),date(2026,10,29)),
            Invoice("DEMO-FT-02","DEMO-001",2026,9,"long",D("57000"),date(2026,10,29))]
