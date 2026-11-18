"""Observation sets with explicit time grain, units and origin."""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .italiano import data_it
from .models import Kind, Origin, utc_now

ROOT = Path(__file__).resolve().parents[1]
ROME = ZoneInfo("Europe/Rome")
FIELDS = {
    "demand_gwh": "Domanda di gas",
    "supply_gwh": "Offerta di gas",
    "storage_gwh": "Contributo dello stoccaggio",
    "price_eur_mwh": "Prezzo di riferimento",
    "production_gwh": "Produzione nazionale",
    "imports_gwh": "Importazioni",
    "exports_gwh": "Esportazioni",
    "net_imports_gwh": "Importazioni nette",
    "stock_change_gwh": "Variazione delle scorte",
    "industry_gwh": "Consumi industriali",
    "power_gwh": "Generazione elettrica",
    "distribution_gwh": "Consumi residenziali e commerciali",
}
META = ["period", "timestamp_utc", "energy_unit", "price_unit", "source_flag"]
COLUMNS = [*META, *FIELDS]
SIGNED = {"price_eur_mwh", "net_imports_gwh", "stock_change_gwh"}
DEMO_FIELDS = ("demand_gwh", "supply_gwh", "storage_gwh", "price_eur_mwh")


@dataclass(frozen=True)
class Bundle:
    rows: pd.DataFrame
    origin: Origin
    fingerprint: str


def make_bundle(data: bytes, origin: Origin) -> Bundle:
    rows = pd.read_csv(BytesIO(data), keep_default_na=False)
    if not set([*META, *origin.fields]) <= set(rows.columns) or not set(origin.fields) <= FIELDS.keys():
        raise ValueError("Schema delle osservazioni non riconosciuto")
    if rows.empty or not origin.fields:
        raise ValueError("Nessuna osservazione nella fonte")
    return Bundle(rows.reindex(columns=COLUMNS, fill_value=""), origin, sha256(data).hexdigest())


def frame_bundle(rows: pd.DataFrame, origin: Origin) -> Bundle:
    return make_bundle(rows.reindex(columns=COLUMNS, fill_value="").to_csv(index=False).encode(), origin)


def synthetic() -> Bundle:
    issued = datetime.fromisoformat("2026-11-17T07:10:00+00:00")
    return make_bundle(
        (ROOT / "data" / "italy_gas_demo.csv").read_bytes(),
        Origin(
            name="Italia · Dati di esempio", kind=Kind.SYNTHETIC, grain="daily", fields=DEMO_FIELDS,
            description="420 giorni gas simulati con stagionalità italiana. La serie include lacune, duplicati, "
                        "letture in conflitto e anomalie inserite per la demo. Lo stoccaggio è già incluso nell’offerta.",
            retrieved_at=issued, published_at=issued,
        ),
    )


def jrc_archive() -> Bundle:
    source = pd.read_csv(ROOT / "data" / "jrc" / "IT.v1.1.csv", comment="#", keep_default_na=False)
    dates = pd.DatetimeIndex(pd.to_datetime(source["GASDAY"], format="%Y-%m-%d"))
    jrc_fields = {"TOT": "demand_gwh", "IND": "industry_gwh", "GPP": "power_gwh", "DIS": "distribution_gwh"}
    rows = source[list(jrc_fields)].replace("NA", "").rename(columns=jrc_fields)
    rows["period"] = source["GASDAY"]
    rows["timestamp_utc"] = [stamp.isoformat() for stamp in utc_starts(dates, "daily")]
    rows["energy_unit"] = "GWh"
    rows["source_flag"] = source["PROC"]
    return frame_bundle(rows, Origin(
        name="JRC · ENaGaD Italia", kind=Kind.HISTORICAL, fields=tuple(jrc_fields.values()),
        grain="daily", archive=True, url="https://doi.org/10.5281/zenodo.6364875",
        retrieved_at=utc_now(), published_at=datetime.fromisoformat("2022-03-15T00:00:00+00:00"),
        latest_period=dates.max().date().isoformat(),
        description="Archivio ENaGaD v1.1 del Joint Research Centre, basato su dati Snam. Consumi nazionali "
                    "e per settore in GWh/giorno. O indica dato originale, E indica stima della fonte. Licenza CC BY 4.0.",
    ))


def utc_starts(periods: pd.DatetimeIndex, grain: str) -> pd.DatetimeIndex:
    """Interpret period labels in Italy, then convert their starts to UTC."""
    starts = periods + pd.offsets.Hour(6) if grain == "daily" else periods
    return starts.tz_localize(ROME).tz_convert("UTC")


def period_text(value: pd.Timestamp, grain: str) -> str:
    return data_it(value, day=grain == "daily")
