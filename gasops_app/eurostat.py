"""Bilancio mensile italiano del gas naturale da Eurostat nrg_cb_gasm."""

from datetime import datetime, timedelta, timezone
import json
import math
import re

import pandas as pd

from .data import Bundle, frame_bundle, utc_starts
from .models import Kind, Origin
from .public_data import retrieve
from .store import Store

URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nrg_cb_gasm"
SOURCE_PAGE = "https://doi.org/10.2908/nrg_cb_gasm"
PARAMETERS = {"freq": "M", "siec": "G3000", "unit": "TJ_GCV", "geo": "IT"}
SERIES = {
    "IC_OBS": "demand_gwh",
    "IC_CAL_MG": "supply_gwh",
    "IPRD": "production_gwh",
    "IMP": "imports_gwh",
    "EXP": "exports_gwh",
    "STK_CHG_MG": "stock_change_gwh",
}
CACHE_KEY = "eurostat-nrg_cb_gasm-IT-bilancio-TJ_GCV"


def _indexed(items: dict | list, position: int):
    return items.get(str(position)) if isinstance(items, dict) else items[position]


def parse(payload: dict, retrieved_at: datetime, *, cached: bool = False, failed: bool = False) -> Bundle:
    if payload.get("source") != "ESTAT" or payload.get("class") != "dataset":
        raise ValueError("Risposta Eurostat non riconosciuta")
    dimensions = payload["dimension"]
    codes, sizes = payload["id"], payload["size"]
    if len(codes) != len(sizes) or set(codes) != {*PARAMETERS, "nrg_bal", "time"} or len(set(codes)) != len(codes):
        raise ValueError("Dimensioni Eurostat non riconosciute")
    for field, code in PARAMETERS.items():
        if sizes[codes.index(field)] != 1 or dimensions[field]["category"]["index"] != {code: 0}:
            raise ValueError(f"Filtro Eurostat non valido ({field})")
    balances = dimensions["nrg_bal"]["category"]["index"]
    balance_size = sizes[codes.index("nrg_bal")]
    if set(balances) != SERIES.keys() or set(balances.values()) != set(range(balance_size)):
        raise ValueError("Voci del bilancio Eurostat non riconosciute")
    time_index = dimensions["time"]["category"]["index"]
    time_size = sizes[codes.index("time")]
    if set(time_index.values()) != set(range(time_size)) or not 1 <= time_size <= 500:
        raise ValueError("Asse mensile Eurostat non valido")
    strides = {code: math.prod(sizes[i + 1:]) for i, code in enumerate(codes)}
    values, flags = payload["value"], payload.get("status", {})
    if not isinstance(values, (list, dict)) or not isinstance(flags, (list, dict)):
        raise ValueError("Osservazioni JSON-stat non riconosciute")
    ordered = sorted(time_index.items())
    if any(not re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", month) for month, _ in ordered):
        raise ValueError("Mese Eurostat non valido")

    periods = pd.DatetimeIndex([f"{month}-01" for month, _ in ordered])
    rows = []
    for (month, index), stamp in zip(ordered, utc_starts(periods, "monthly"), strict=True):
        row = {"period": f"{month}-01", "timestamp_utc": stamp.isoformat(), "energy_unit": "GWh"}
        row_flags = set()
        for code, field in SERIES.items():
            position = balances[code] * strides["nrg_bal"] + index * strides["time"]
            value = _indexed(values, position)
            if value is not None and (
                type(value) not in (float, int) or not math.isfinite(value)
                or (value < 0 and field != "stock_change_gwh")
            ):
                raise ValueError(f"Valore Eurostat non valido ({code})")
            flag = _indexed(flags, position)
            if flag:
                row_flags.update(flag.split())
            row[field] = None if value is None else value / 3.6
        row["source_flag"] = " ".join(sorted(row_flags))
        rows.append(row)

    frame = pd.DataFrame(rows)
    frame[list(SERIES.values())] = frame[list(SERIES.values())].apply(pd.to_numeric)
    if frame["demand_gwh"].notna().sum() == 0:
        raise ValueError("Consumi italiani assenti nella risposta Eurostat")
    # Il segno MOS GAS è positivo in caso di aumento delle scorte.
    frame["net_imports_gwh"] = frame["imports_gwh"] - frame["exports_gwh"]
    frame["storage_gwh"] = (-frame["stock_change_gwh"]).clip(lower=0)
    return frame_bundle(frame, Origin(
        name="Eurostat · Italia", kind=Kind.HISTORICAL, grain="monthly",
        fields=(*SERIES.values(), "net_imports_gwh", "storage_gwh"), url=SOURCE_PAGE,
        retrieved_at=retrieved_at,
        published_at=datetime.strptime(payload["updated"], "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc),
        description="nrg_cb_gasm (IT, G3000). Consumo osservato (IC_OBS) e disponibilità contabile "
                    "(consumo interno calcolato MOS GAS, IC_CAL_MG). Produzione, importazioni, esportazioni e "
                    "variazione scorte in TJ a PCS, divisi per 3,6 per ottenere GWh. La variazione scorte è positiva "
                    "in accumulo. Il contributo di prelievo netto è max(0, −variazione scorte).",
        cached=cached, refresh_failed=failed,
    ))


def _parse_text(text: str, fetched_at: datetime, **kwargs) -> Bundle:
    return parse(json.loads(text), fetched_at, **kwargs)


def load(store: Store, *, refresh: bool = False) -> Bundle:
    return retrieve(
        store, key=CACHE_KEY, name="Eurostat", url=URL, parse=_parse_text,
        ttl=timedelta(hours=8), refresh=refresh,
        params={**PARAMETERS, "nrg_bal": tuple(SERIES), "lang": "EN", "sinceTimePeriod": "2018-01"},
    )
