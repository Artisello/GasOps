"""Observation sets with explicit time grain, units and origin."""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .models import Kind, Origin

ROOT = Path(__file__).resolve().parents[1]
ROME = ZoneInfo("Europe/Rome")
FIELDS = {
    "demand_gwh": "Gas demand",
    "supply_gwh": "Gas supply",
    "storage_gwh": "Storage contribution",
    "price_eur_mwh": "Reference price",
}
COLUMNS = ["period", "timestamp_utc", "energy_unit", "price_unit", *FIELDS, "source_flag"]


@dataclass(frozen=True)
class Bundle:
    rows: pd.DataFrame
    origin: Origin
    fingerprint: str


def make_bundle(data: bytes, origin: Origin) -> Bundle:
    rows = pd.read_csv(BytesIO(data), keep_default_na=False)
    if not set(COLUMNS) <= set(rows.columns) or not set(origin.fields) <= FIELDS.keys():
        raise ValueError("Unsupported observation schema")
    if rows.empty or not origin.fields:
        raise ValueError("No observations in source")
    return Bundle(rows[COLUMNS], origin, sha256(data).hexdigest())


def synthetic() -> Bundle:
    issued = datetime.fromisoformat("2026-11-17T07:10:00+00:00")
    return make_bundle(
        (ROOT / "data" / "italy_gas_demo.csv").read_bytes(),
        Origin(
            name="Italy · offline demo", kind=Kind.SYNTHETIC, grain="daily", fields=tuple(FIELDS),
            description="420 calendar days of simulated Italian gas days. Includes injected gaps, "
                        "duplicates, conflicting readings, outliers and bad metadata. Storage is part of supply.",
            retrieved_at=issued, published_at=issued,
        ),
    )


def utc_starts(periods: pd.DatetimeIndex, grain: str) -> pd.DatetimeIndex:
    """Interpret period labels in Italy, then convert their starts to UTC."""
    starts = periods + pd.offsets.Hour(6) if grain == "daily" else periods
    return starts.tz_localize(ROME).tz_convert("UTC")


def period_text(value: pd.Timestamp, grain: str) -> str:
    return value.strftime("%d %b %Y" if grain == "daily" else "%b %Y")
