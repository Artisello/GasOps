"""Formattazione italiana indipendente dalle impostazioni locali del sistema."""

from datetime import date
from math import isfinite

from .models import Kind

MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre")
MESI_BREVI = ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic")
TIPI = {
    Kind.SYNTHETIC: "DATI DI ESEMPIO", Kind.HISTORICAL: "DATI PUBBLICI STORICI",
    Kind.LIVE: "DATI PUBBLICI CORRENTI", Kind.FORECAST: "PREVISIONE",
    Kind.SIMULATION: "SIMULAZIONE", Kind.ACCOUNTING: "CONVENZIONE CONTABILE", Kind.PHYSICAL: "MISURA FISICA",
}
MODELLI = {"Automatic": "Automatico", "Bayesian seasonal": "Bayesiano stagionale",
           "Seasonal regression": "Regressione stagionale", "Seasonal naive": "Riferimento stagionale", "ARIMA": "ARIMA", "SARIMAX": "SARIMAX"}
MODALITA = {"Deterministic": "Deterministica", "LLM-assisted": "Assistita da LLM",
            "Deterministic fallback": "Deterministica di riserva"}
GRANULARITA = {"daily": "giornaliera", "monthly": "mensile"}
GRAVITA = {"high": "Alta", "medium": "Media", "info": "Informativa"}
ESITI = {"charge": "Addebito", "credit": "Credito", "flat": "Neutro", "buy": "Acquisto", "sell": "Vendita",
          "queued": "In coda", "running": "In corso", "completed": "Completato", "review": "Da rivedere",
          "unavailable": "Non disponibile", "skipped": "Non selezionato", "failed": "Errore", "ready": "Pronto"}


def numero(value, decimals: int = 1, *, signed: bool = False) -> str:
    if value is None:
        return "—"
    try:
        # NaN/Inf are missing observations, not values or zero.
        if not isfinite(value):
            return "—"
        style = "+" if signed else ""
        result = format(value, f"{style},.{decimals}f")
    except (TypeError, ValueError, ArithmeticError):
        return "—"
    # Avoid misleading negative zero after rounding for display only.
    if result.startswith("-") and not any(c in "123456789" for c in result):
        result = ("+" if signed else "") + result[1:]
    return result.translate(str.maketrans(",.", ".,"))


def data_it(value: date, *, day: bool = True) -> str:
    month = MESI_BREVI[value.month - 1]
    return f"{value.day:02d} {month} {value.year}" if day else f"{MESI[value.month - 1].capitalize()} {value.year}"
