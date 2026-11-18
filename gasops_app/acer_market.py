"""ACER publications: distinct LNG assessments, benchmark spread and gas-year BAF."""
import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import StringIO
from pathlib import Path
import re

from .public_data import retrieve, SourceSchemaError
from .data import ROME

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = "https://aegis.acer.europa.eu/terminal/price_assessments"
CSV_URL = TERMINAL + "/historical_data"
LEGAL = "https://www.acer.europa.eu/legal-notice"
METHODOLOGY = "https://www.acer.europa.eu/gas/lng-price-assessment"
BALANCING = "https://www.acer.europa.eu/gas/network-codes/monitoring/balancing"
REPORT_2025 = "https://www.acer.europa.eu/sites/default/files/documents/Publications/ACER-Gas-Balancing-Indicators-Highlights-2025.pdf"
REPORT_2026 = "https://acer.europa.eu/sites/default/files/documents/Publications/ACER-Gas-Balancing-Indicators-Highlights-2026.pdf"
CHEST = "https://aegis.acer.europa.eu/chest/dataitems/1136/view"
MAX_BYTES = 2_000_000
CACHE_KEY = "acer-terminal-lng-v1"
FIELDS = ("nwe","south","eu","benchmark")
HEADERS = {
    "date":"date",
    "north-west europe price (eur/mwh)":"nwe",
    "north west europe price (eur/mwh)":"nwe",
    "south europe price (eur/mwh)":"south",
    "eu price (eur/mwh)":"eu",
    "lng benchmark (eur/mwh)":"benchmark",
    "pdf report":"report",
}
# These are the labels observed in the public HTML table. Native CSV headers
# still need a live smoke test. Unknown schemas fail closed, not guessed.
UTC = timezone.utc


@dataclass(frozen=True)
class LNG:
    rows: tuple
    acquired: datetime
    sha256: str
    provenance: str
    cached: bool = False
    failed: bool = False


def _decimal(value):
    raw=value.strip()
    if raw.lower() in ("","-","—","n/a","na"):
        return None
    if not re.fullmatch(r"[+-]?\d{1,8}(?:[.,]\d{1,8})?",raw):
        raise SourceSchemaError("Valore ACER non numerico.")
    return Decimal(raw.replace(",","."))


def _day(value):
    raw=value.strip()
    # The visible TERMINAL date convention is yyyy.mm.dd; also accept ISO.
    if not re.fullmatch(r"\d{4}[-.]\d{2}[-.]\d{2}",raw):
        raise SourceSchemaError("Formato data ACER non riconosciuto.")
    try:
        return date.fromisoformat(raw.replace(".","-"))
    except ValueError as exc:
        raise SourceSchemaError("Data ACER non valida.") from exc


def parse_lng(text, acquired, *, cached=False, failed=False, provenance="download ufficiale"):
    if not text or len(text.encode()) > MAX_BYTES or text.lstrip().startswith("<"):
        raise SourceSchemaError("CSV ACER vuoto, troppo grande o non CSV.")
    try:
        dialect=csv.Sniffer().sniff(text[:8192],delimiters=",;\t")
        reader=csv.DictReader(StringIO(text.lstrip("\ufeff")),dialect=dialect,strict=True)
        raw_headers=reader.fieldnames or []
        mapping={h:HEADERS.get(" ".join(h.strip().lower().split())) for h in raw_headers}
        if (len(raw_headers)!=len(mapping) or None in mapping.values()
                or len(set(mapping.values()))!=len(mapping) or not {"date",*FIELDS}<=set(mapping.values())):
            raise SourceSchemaError("Intestazioni CSV ACER non riconosciute; nessuna unità presunta.")
        rows={}
        for idx,item in enumerate(reader):
            if idx>=10000 or None in item or any(v is None for v in item.values()):
                raise SourceSchemaError("Righe CSV ACER non valide o troppo numerose.")
            r={mapping[k]:v for k,v in item.items()}
            day=_day(r["date"])
            if not date(2023,1,1)<=day<=acquired.astimezone(ROME).date():
                raise SourceSchemaError("Periodo ACER fuori limite o futuro.")
            values=tuple(_decimal(r[k]) for k in FIELDS)
            if all(v is None for v in values):
                # Explicit unavailable dates are retained, never filled by zero.
                pass
            if day in rows and rows[day]!=values:
                raise SourceSchemaError("Pubblicazioni ACER in conflitto.")
            rows[day]=values
    except (csv.Error,InvalidOperation) as exc:
        raise SourceSchemaError("CSV ACER non leggibile.") from exc
    if not rows or not any(v is not None for vals in rows.values() for v in vals):
        raise SourceSchemaError("Nessun valore ACER disponibile.")
    return LNG(tuple({"date":d.isoformat(),**dict(zip(FIELDS,v,strict=True))} for d,v in sorted(rows.items())),
               acquired,sha256(text.encode()).hexdigest(),provenance,cached,failed)


def bundled_lng():
    path=ROOT/"data/acer/lng-september-2026-extract.csv"
    return parse_lng(path.read_text(encoding="utf-8"),datetime(2026,11,18,tzinfo=UTC),
                     provenance="trascrizione tabella pubblica, 01–25/09/2026; consultata 11/2026")


def load_lng(store, *, refresh=False):
    return retrieve(store,key=CACHE_KEY,name="ACER TERMINAL",url=CSV_URL,
                    parse=parse_lng,ttl=timedelta(hours=24),refresh=refresh,attempts=1,
                    timeout=(5,25),max_bytes=MAX_BYTES,diagnostics=True)


def cached_lng(store, now):
    """Read and validate the shared official cache without a network request."""
    entry=store.cached(CACHE_KEY)
    if not entry:return None
    try:
        at=datetime.fromisoformat(entry[0])
        if at.tzinfo is None or at>now:return None
        return parse_lng(entry[1],at,cached=True)
    except (ValueError,TypeError,IndexError):
        return None


def with_spreads(rows):
    output=[]
    for r in rows:
        south,nwe=r["south"],r["nwe"]
        output.append({**r,"south_minus_nwe":south-nwe if south is not None and nwe is not None else None})
    return output


def balancing_rows():
    path=ROOT/"data/acer/balancing-gy2023-2024.csv"
    result=[]
    known=set()
    with path.open(encoding="utf-8",newline="") as f:
        reader=csv.DictReader(f,strict=True)
        if reader.fieldnames!=["gas_year","zone","metric","unit","value"]:
            raise ValueError("Schema benchmark ACER non valido.")
        for r in reader:
            metric=r["metric"]
            if r["gas_year"]!="2023/2024" or not re.fullmatch(r"[A-Z][A-Z-]{1,10}",r["zone"]):
                raise ValueError("Anno gas o zona non validi.")
            expected={"imbalance_share":"%","net_adjusted_neutrality":"EUR/MWh"}.get(metric)
            key=(r["zone"],metric)
            if expected is None or expected!=r["unit"] or key in known:
                raise ValueError("Metrica ACER non valida o duplicata.")
            value=_decimal(r["value"])
            if value is None or (metric=="imbalance_share" and not 0<=value<=100):
                raise ValueError("Valore benchmark ACER non valido.")
            known.add(key)
            result.append({**r,"value":value,"source":"ACER, report 2025, anno gas 2023/2024",
                           "source_url":REPORT_2025,"page":16 if metric=="imbalance_share" else 19,
                           "provenance":"trascrizione etichette grafico; precisione pubblicata"})
    if sum(r["metric"]=="imbalance_share" for r in result)!=23 or sum(r["metric"]=="net_adjusted_neutrality" for r in result)!=24:
        raise ValueError("Copertura benchmark pubblicato inattesa.")
    return tuple(result)


def lng_export(result):
    out=StringIO()
    fields=("date",*FIELDS,"south_minus_nwe","unit","source","source_url","acquired_at","provenance","sha256_text")
    writer=csv.DictWriter(out,fieldnames=fields,lineterminator="\n")
    writer.writeheader()
    for r in with_spreads(result.rows):
        writer.writerow({**r,"unit":"EUR/MWh","source":"ACER","source_url":TERMINAL,
                         "acquired_at":result.acquired.isoformat(),"provenance":result.provenance,
                         "sha256_text":result.sha256})
    return out.getvalue()
