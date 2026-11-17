"""Prezzo mensile ARERA e unione con il bilancio Eurostat per mese civile."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from html.parser import HTMLParser
import re

import pandas as pd

from . import eurostat
from .data import Bundle, frame_bundle
from .italiano import MESI
from .models import Provider, Kind
from .public_data import SourceUnavailable, retrieve
from .store import Store

ARERA_URL = "https://www.arera.it/area-operatori/prezzi-e-tariffe/valore-cmemm-vulnerabili"
ARERA_CACHE = "arera-cmemm-vulnerabili-eur-mwh"


class _TableRows(HTMLParser):
    """Legge le celle delle tabelle pubbliche, senza dipendenze HTML aggiuntive."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._row = None
            self._cell = None
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None
            self._row = None
            self._cell = None


@dataclass(frozen=True)
class Prices:
    rows: dict[str, Decimal]
    source: Provider


def parse_arera(html: str, retrieved_at: datetime, *, cached: bool = False, failed: bool = False) -> Prices:
    parser = _TableRows()
    parser.feed(html)
    prices = {}
    found_table = False
    month_index = {name: i for i, name in enumerate(MESI, 1)}
    for table in parser.tables:
        if not table or len(table[0]) != 4 or table[0][1].lower() != "euro/mwh":
            continue
        found_table = True
        year = None
        for row in table:
            if len(row) != 4:
                raise ValueError("Tabella ARERA non riconosciuta")
            label, value = row[0].lower(), row[1]
            if re.fullmatch(r"20\d{2}", label):
                year = int(label)
                continue
            if year is None or label not in month_index:
                raise ValueError("Periodo ARERA non valido")
            if value in {"", "-", "–", "—", "n.d."}:
                continue
            if not re.fullmatch(r"[+-]?\d+(?:,\d+)?", value):
                raise ValueError("Valore ARERA in EUR/MWh non valido")
            period = f"{year:04d}-{month_index[label]:02d}-01"
            if period in prices:
                raise ValueError("Mese duplicato nella tabella ARERA")
            prices[period] = Decimal(value.replace(",", "."))
    if not found_table or not prices:
        raise ValueError("Tabella C MEM,m in EUR/MWh non trovata")
    return Prices(prices, Provider(
        name="ARERA · CMEM,m", kind=Kind.HISTORICAL, fields=("price_eur_mwh",), url=ARERA_URL,
        retrieved_at=retrieved_at, latest_period=max(prices),
        description="Componente materia prima CMEM,m, pari alla media mensile pubblicata del PSV day-ahead, "
                    "in EUR/MWh. Riferimento all’ingrosso per il mese di competenza.",
        cached=cached, refresh_failed=failed,
    ))


def load_arera(store: Store, *, refresh: bool = False) -> Prices:
    return retrieve(
        store, key=ARERA_CACHE, name="ARERA", url=ARERA_URL, parse=parse_arera,
        ttl=timedelta(hours=12), refresh=refresh,
    )


def combine(balance: Bundle, prices: Prices) -> Bundle:
    frame = balance.rows.copy()
    frame["price_eur_mwh"] = frame["period"].map({period: float(value) for period, value in prices.rows.items()})
    frame["price_unit"] = frame["price_eur_mwh"].notna().map({True: "EUR/MWh", False: ""})
    fields = (*balance.origin.fields, "price_eur_mwh") if frame["price_eur_mwh"].notna().any() else balance.origin.fields
    return frame_bundle(frame, balance.origin.model_copy(update={
        "fields": fields, "companions": (prices.source,),
    }))


def load_monthly(store: Store, *, refresh: bool = False) -> tuple[Bundle, str | None]:
    with ThreadPoolExecutor(max_workers=2) as pool:
        balances = pool.submit(eurostat.load, store, refresh=refresh)
        prices = pool.submit(load_arera, store, refresh=refresh)
        balance = balances.result()
        try:
            return combine(balance, prices.result()), None
        except SourceUnavailable:
            return balance, "Prezzo ARERA temporaneamente non disponibile. I volumi Eurostat sono disponibili."
