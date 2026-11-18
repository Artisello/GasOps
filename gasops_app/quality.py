"""Flag malformed observations and build the analytical series from usable values."""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from gasops import gas_hours

from .data import Bundle, FIELDS, ROME, SIGNED, utc_starts
from .italiano import TIPI, data_it
from .models import Finding, Kind


@dataclass(frozen=True)
class Inspection:
    usable: pd.DataFrame
    findings: list[Finding]


def inspect(bundle: Bundle, now: datetime) -> Inspection:
    data = bundle.rows.copy()
    source = bundle.origin
    daily = source.grain == "daily"
    findings: list[Finding] = []

    def report(key: str, title: str, severity: str, detail: str, category: str) -> None:
        findings.append(Finding(id=key, title=title, severity=severity, detail=detail, category=category))

    def flag(mask: pd.Series, key: str, title: str, severity: str, consequence: str) -> None:
        if mask.any():
            examples = ", ".join(map(str, data.loc[mask, "period"].head(4)))
            report(key, title, severity, f"Record interessati {int(mask.sum())}, tra cui {examples}. {consequence}",
                   TIPI[source.kind])

    periods = pd.to_datetime(data["period"], format="%Y-%m-%d", errors="coerce")
    valid_period = periods.notna() & periods.dt.strftime("%Y-%m-%d").eq(data["period"])
    if not daily:
        valid_period &= periods.dt.is_month_start
    flag(~valid_period, "bad-period", "Date non valide", "high", "Record esclusi dall’analisi.")
    data = data.loc[valid_period].copy()
    periods = periods.loc[valid_period]
    data["_period"] = periods

    if data.empty:
        empty = pd.DataFrame(columns=list(FIELDS), index=pd.DatetimeIndex([], name="period"), dtype=float)
        return Inspection(empty, findings)

    freq = "D" if daily else "MS"
    # Keep unusable periods on the calendar as gaps, including at either end.
    calendar = pd.date_range(periods.min(), periods.max(), freq=freq, name="period")
    times = pd.to_datetime(data["timestamp_utc"], format="ISO8601", utc=True, errors="coerce")
    explicit_utc = data["timestamp_utc"].astype(str).str.endswith(("Z", "+00:00"))
    expected = pd.Series(utc_starts(pd.DatetimeIndex(periods), source.grain), index=data.index)
    bad_time = ~explicit_utc | times.ne(expected)
    flag(bad_time, "timestamp", "Orario UTC incoerente", "high", "Record esclusi dall’analisi.")
    bad_unit = data["energy_unit"].ne("GWh")
    if "price_eur_mwh" in source.fields:
        bad_price_unit = data["price_unit"].ne("EUR/MWh") & data["price_eur_mwh"].ne("")
        flag(bad_price_unit, "price-unit", "Unità di prezzo non valida", "high", "I prezzi interessati sono esclusi.")
        data.loc[bad_price_unit, "price_eur_mwh"] = np.nan
    flag(bad_unit, "unit", "Unità di misura non valide", "high", "Record esclusi dall’analisi.")
    data = data.loc[~(bad_time | bad_unit)].copy()

    duplicates = data.duplicated()
    flag(duplicates, "duplicate", "Osservazioni duplicate", "medium", "Le copie identiche sono contate una volta.")
    data = data.loc[~duplicates].copy()
    conflicts = data.duplicated("_period", keep=False)
    flag(conflicts, "conflicting", "Letture in conflitto nello stesso periodo", "high", "Tutte le versioni sono escluse.")
    data = data.loc[~conflicts].set_index("_period").copy()

    for key, label in FIELDS.items():
        if key not in source.fields:
            data[key] = np.nan
            continue
        values = pd.to_numeric(data[key], errors="coerce")
        invalid = data[key].notna() & data[key].ne("") & ~np.isfinite(values)
        if key not in SIGNED:
            invalid |= values.lt(0)
        flag(invalid, f"invalid-{key}", f"Valori non validi · {label.lower()}", "high", "Valori esclusi dai calcoli.")
        data[key] = values.mask(invalid).astype(float)

    if "storage_gwh" in source.fields:
        impossible = data["storage_gwh"].gt(data["supply_gwh"])
        flag(impossible, "storage-component", "Prelievo da stoccaggio superiore all’offerta", "high",
             "I valori dello stoccaggio sono esclusi.")
        data.loc[impossible, "storage_gwh"] = np.nan

    series = data[list(FIELDS)].reindex(calendar).astype(float)
    absent = calendar.difference(data.index)
    if len(absent):
        samples = ", ".join(day.strftime("%Y-%m-%d") for day in absent[:4])
        report("missing-period", "Periodi mancanti o esclusi", "medium",
               f"{len(absent)} periodi, tra cui {samples}. Le lacune restano visibili.", TIPI[source.kind])

    companion_fields = {field for companion in source.companions for field in companion.fields}
    for key in source.fields:
        values = series[key]
        nulls = data[key].isna()
        if key in companion_fields:
            first, last = values.first_valid_index(), values.last_valid_index()
            nulls &= (data.index >= first) & (data.index <= last) if first is not None else False
        if nulls.any():
            dates = ", ".join(day.strftime("%Y-%m-%d") for day in data.index[nulls][:4])
            report(f"missing-{key}", f"Valori mancanti · {FIELDS[key].lower()}", "medium",
                   f"Record interessati {int(nulls.sum())}, tra cui {dates}. I valori mancanti restano vuoti.", TIPI[source.kind])
        # Use only prior observations. For monthly series compare year-on-year changes.
        signal = values if daily else values - values.shift(12)
        prior = signal.shift(1).rolling(28 if daily else 24, min_periods=14)
        median = prior.median()
        mad = prior.apply(lambda window: np.nanmedian(np.abs(window - np.nanmedian(window))), raw=True)
        threshold = (6 * 1.4826 * mad).clip(lower=0.24 * values.shift(1).abs().rolling(6, min_periods=4).median())
        outliers = (signal - median).abs().gt(threshold) & threshold.gt(0)
        if outliers.any():
            dates = ", ".join(day.strftime("%Y-%m-%d") for day in series.index[outliers][:4])
            synthetic = source.kind == Kind.SYNTHETIC
            detail = "Anomalie di esempio escluse dall’analisi." if synthetic else "Valori pubblicati mantenuti nella serie."
            affected = int(outliers.sum())
            periods_note = f"Un periodo ({dates})" if affected == 1 else f"{affected} periodi, tra cui {dates}"
            report(f"outlier-{key}", f"Valori statistici insoliti · {FIELDS[key].lower()}", "medium" if synthetic else "info",
                   f"{periods_note}. {detail}", TIPI[source.kind])
            if synthetic:
                series.loc[outliers, key] = np.nan

    last = series["demand_gwh"].last_valid_index()
    clock = source.published_at if source.kind == Kind.SYNTHETIC else now
    if last is not None and clock is not None and not source.archive:
        age = (clock.astimezone(ROME).date() - last.date()).days
        if age > (3 if daily else 100):
            report("stale", "Serie della domanda da aggiornare", "medium",
                   f"Ultimo periodo {last:%Y-%m-%d}, {age} giorni prima della data di riferimento.", TIPI[source.kind])

    if daily:
        transitions = [f"{data_it(day)} · {hours} h" for day in calendar
                       if (hours := gas_hours(day.date().isoformat())) != 24]
        if transitions:
            report("dst", "Cambio dell’ora nel giorno gas", "info",
                   ", ".join(transitions) + ". I periodi iniziano alle 06:00 Europe/Rome e conservano la durata effettiva.",
                   "Aggregazione temporale")
    for index, feed in enumerate((source, *source.companions)):
        if feed.refresh_failed:
            report("public-cache" if index == 0 else f"public-cache-{index}",
                   f"Aggiornamento non riuscito · {feed.name}", "medium",
                   "È disponibile una copia già verificata con la data di acquisizione originale.", TIPI[feed.kind])

    return Inspection(series, findings)
