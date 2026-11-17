"""Verified Eurostat monthly Italian inland gas consumption (nrg_cb_gasm)."""

from datetime import datetime, timedelta, timezone
import json
import logging
import math
import re

import pandas as pd
import requests

from .data import Bundle, COLUMNS, make_bundle, utc_starts
from .models import Kind, Origin, utc_now
from .store import Store

LOGGER = logging.getLogger(__name__)
URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nrg_cb_gasm"
SOURCE_PAGE = "https://doi.org/10.2908/nrg_cb_gasm"
PARAMETERS = {"freq": "M", "siec": "G3000", "nrg_bal": "IC_OBS", "unit": "TJ_GCV", "geo": "IT"}
CACHE_KEY = "eurostat-nrg_cb_gasm-IT-IC_OBS-TJ_GCV"
TTL = timedelta(hours=8)


class SourceUnavailable(RuntimeError):
    pass


def _indexed(items: dict | list, position: int):
    if isinstance(items, dict):
        return items.get(str(position))
    return items[position]


def parse(payload: dict, retrieved_at: datetime, *, cached: bool = False, failed: bool = False) -> Bundle:
    if payload.get("source") != "ESTAT" or payload.get("class") != "dataset":
        raise ValueError("Unexpected Eurostat response")
    dimensions = payload["dimension"]
    codes, sizes = payload["id"], payload["size"]
    if len(codes) != len(sizes) or set(codes) != {*PARAMETERS, "time"} or len(set(codes)) != len(codes):
        raise ValueError("Unexpected Eurostat dimensions")
    for field, code in PARAMETERS.items():
        if sizes[codes.index(field)] != 1 or dimensions[field]["category"]["index"] != {code: 0}:
            raise ValueError(f"Unexpected Eurostat {field} filter")
    time_index = dimensions["time"]["category"]["index"]
    time_size = sizes[codes.index("time")]
    if set(time_index.values()) != set(range(time_size)) or not 1 <= time_size <= 500:
        raise ValueError("Unexpected monthly time axis")
    values, flags = payload["value"], payload.get("status", {})
    if not isinstance(values, (list, dict)) or not isinstance(flags, (list, dict)):
        raise ValueError("Unsupported JSON-stat observations")
    ordered = sorted(time_index.items())
    if any(not re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", month) for month, _ in ordered):
        raise ValueError("Invalid Eurostat month")
    periods = pd.DatetimeIndex([f"{month}-01" for month, _ in ordered])
    rows = []
    for (month, index), stamp in zip(ordered, utc_starts(periods, "monthly"), strict=True):
        value = _indexed(values, index)
        if value is not None and (type(value) not in (float, int) or value < 0 or not math.isfinite(value)):
            raise ValueError("Invalid gas consumption value")
        flag = _indexed(flags, index)
        rows.append([f"{month}-01", stamp.isoformat(), "GWh", "",
                     None if value is None else value / 3.6, None, None, None, flag or ""])
    frame = pd.DataFrame(rows, columns=COLUMNS)
    if frame["demand_gwh"].notna().sum() == 0:
        raise ValueError("Eurostat returned no Italian consumption values")
    return make_bundle(frame.to_csv(index=False).encode(), Origin(
        name="Eurostat · Italy", kind=Kind.HISTORICAL, grain="monthly", fields=("demand_gwh",),
        url=SOURCE_PAGE, retrieved_at=retrieved_at,
        published_at=datetime.strptime(payload["updated"], "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc),
        description="nrg_cb_gasm · observed inland consumption (IC_OBS), natural gas (G3000), Italy (IT). "
                    "Monthly energy in TJ (gross calorific value) ÷ 3.6 = GWh. Provider flags retained.",
        cached=cached, refresh_failed=failed,
    ))


def load(store: Store, *, refresh: bool = False) -> Bundle:
    now = utc_now()
    existing = store.cached(CACHE_KEY)
    cache_at = None
    if existing:
        try:
            cache_at = datetime.fromisoformat(existing[0])
            if not refresh and now - cache_at < TTL:
                return parse(json.loads(existing[1]), cache_at, cached=True)
        except (ValueError, TypeError, KeyError, IndexError):
            cache_at = None

    for attempt in range(2):
        try:
            with requests.get(URL, params={**PARAMETERS, "lang": "EN", "sinceTimePeriod": "2018-01"},
                              timeout=(3, 5), stream=True) as response:
                response.raise_for_status()
                body = bytearray()
                for part in response.iter_content(chunk_size=16_384):
                    body.extend(part)
                    if len(body) > 1_000_000:
                        raise ValueError("Eurostat response exceeded its expected size")
            bundle = parse(json.loads(body), now)
        except (requests.RequestException, ValueError, KeyError, TypeError, IndexError) as error:
            LOGGER.warning("Eurostat attempt %s failed (%s)", attempt + 1, type(error).__name__)
            continue
        store.cache(CACHE_KEY, now.isoformat(), body.decode("utf-8"))
        return bundle

    if existing and cache_at is not None:
        try:
            return parse(json.loads(existing[1]), cache_at, cached=True, failed=True)
        except (ValueError, KeyError, TypeError, IndexError):
            pass
    raise SourceUnavailable("Eurostat is unavailable and there is no verified cache. Retry or select the offline demo.")
