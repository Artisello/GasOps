"""Flag malformed observations and build the analytical series from usable values."""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from gasops import gas_hours

from .data import Bundle, FIELDS, ROME, utc_starts
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
            report(key, title, severity, f"{int(mask.sum())} record(s), including {examples}. {consequence}",
                   source.kind.value)

    periods = pd.to_datetime(data["period"], format="%Y-%m-%d", errors="coerce")
    valid_period = periods.notna() & periods.dt.strftime("%Y-%m-%d").eq(data["period"])
    if not daily:
        valid_period &= periods.dt.is_month_start
    flag(~valid_period, "bad-period", "Invalid period labels", "high", "Excluded from analytical series.")
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
    flag(bad_time, "timestamp", "Inconsistent UTC timestamp", "high", "Excluded from analytical series.")
    bad_unit = data["energy_unit"].ne("GWh")
    if "price_eur_mwh" in source.fields:
        bad_unit |= data["price_unit"].ne("EUR/MWh")
    flag(bad_unit, "unit", "Invalid observation units", "high", "Excluded from analytical series.")
    data = data.loc[~(bad_time | bad_unit)].copy()

    duplicates = data.duplicated()
    flag(duplicates, "duplicate", "Duplicate observations", "medium", "Identical copies were counted once.")
    data = data.loc[~duplicates].copy()
    conflicts = data.duplicated("_period", keep=False)
    flag(conflicts, "conflicting", "Conflicting readings for one period", "high", "All versions were quarantined.")
    data = data.loc[~conflicts].set_index("_period").copy()

    for key, label in FIELDS.items():
        if key not in source.fields:
            data[key] = np.nan
            continue
        values = pd.to_numeric(data[key], errors="coerce")
        invalid = data[key].ne("") & ~np.isfinite(values)
        if key != "price_eur_mwh":
            invalid |= values.lt(0)
        flag(invalid, f"invalid-{key}", f"Invalid {label.lower()}", "high", "Value excluded from calculations.")
        data[key] = values.mask(invalid).astype(float)

    if "storage_gwh" in source.fields:
        impossible = data["storage_gwh"].gt(data["supply_gwh"])
        flag(impossible, "storage-component", "Storage exceeds total supply", "high", "Storage values were quarantined.")
        data.loc[impossible, "storage_gwh"] = np.nan

    series = data[list(FIELDS)].reindex(calendar).astype(float)
    absent = calendar.difference(data.index)
    if len(absent):
        samples = ", ".join(day.strftime("%Y-%m-%d") for day in absent[:4])
        report("missing-period", "Missing or quarantined periods", "medium",
               f"{len(absent)} calendar period(s), including {samples}. Gaps remain visible.", source.kind.value)

    for key in source.fields:
        values = series[key]
        nulls = data[key].isna()
        if nulls.any():
            dates = ", ".join(day.strftime("%Y-%m-%d") for day in data.index[nulls][:4])
            report(f"missing-{key}", f"Unavailable {FIELDS[key].lower()}", "medium",
                   f"{int(nulls.sum())} record(s), including {dates}. Missing values remain empty.", source.kind.value)
        # Use only prior observations. For monthly series compare year-on-year changes.
        signal = values if daily else values - values.shift(12)
        prior = signal.shift(1).rolling(28 if daily else 24, min_periods=14)
        median = prior.median()
        mad = prior.apply(lambda window: np.nanmedian(np.abs(window - np.nanmedian(window))), raw=True)
        threshold = (6 * 1.4826 * mad).clip(lower=0.24 * values.shift(1).abs().rolling(6, min_periods=4).median())
        outliers = (signal - median).abs().gt(threshold) & threshold.gt(0)
        if outliers.any():
            dates = ", ".join(day.strftime("%Y-%m-%d") for day in series.index[outliers][:4])
            report(f"outlier-{key}", f"Statistical outlier · {FIELDS[key].lower()}", "medium",
                   f"{int(outliers.sum())} period(s), including {dates}. Flagged for review and excluded.",
                   source.kind.value)
            series.loc[outliers, key] = np.nan

    last = series["demand_gwh"].last_valid_index()
    clock = source.published_at if source.kind == Kind.SYNTHETIC else now
    if last is not None and clock is not None:
        age = (clock.astimezone(ROME).date() - last.date()).days
        if age > (3 if daily else 100):
            report("stale", "Demand series exceeds freshness window", "medium",
                   f"Latest usable period starts {last:%Y-%m-%d}, {age} calendar days before the reference date.",
                   source.kind.value)

    if daily:
        transitions = [f"{day:%d %b %Y} · {hours} h" for day in calendar
                       if (hours := gas_hours(day.date().isoformat())) != 24]
        if transitions:
            report("dst", "Gas-day daylight saving transitions", "info",
                   ", ".join(transitions) + ". Periods start at 06:00 Europe/Rome and retain their elapsed duration.",
                   "Time aggregation")
    if source.refresh_failed:
        report("public-cache", "Public source refresh failed", "medium",
               "Showing a previously verified Eurostat response with its original retrieval time.", source.kind.value)

    return Inspection(series, findings)
