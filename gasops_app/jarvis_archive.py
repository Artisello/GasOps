"""Public aggregate Jarvis extracts; explicit provenance, no native schema assumptions."""
import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256

from .data import ROME

SOURCE = "https://jarvis.snam.it/public-data?lang=it"
CATALOG = "https://www.snam.it/it/i-nostri-business/trasporto/informazioni-commerciali.html"
API_CATALOG = "https://www.snam.it/en/our-businesses/news/2025/jarvis-marketplace-access-to-the-API-catalog.html"
Q_NOTICE = "https://www.snam.it/en/our-businesses/news/2025/publication-of-the-calibration-parameter-q-values-pursuant-to-resolution-482-2024-r-gas-and-operational-application-procedures.html"
DAILY = "https://jarvis.snam.it/public-data?lang=it&periodo=2025&pubblicazione=Dati+Operativi+bilanciamento+%E2%80%93+giornalieri"
FIELDS = ("family","gas_day","published_at","stage","scope","metric","unit","value","report_ref")
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 10000
# Narrow aggregate-only model. No user or shipper identifiers.
RULES = {
    "balance": ({"provisional","definitive"}, {"injections","withdrawals","balance_reported"}, {"MWh","GWh","Sm3"}),
    "wkr": ({"forecast","observed"}, {"wkr"}, {"ratio"}),
    "q": ({"published"}, {"q"}, {"fraction","percent"}),
    "gas_stock": ({"published"}, {"gas_stock"}, {"MWh","GWh","Sm3"}),
}
UTC = timezone.utc


@dataclass(frozen=True)
class Record:
    family: str
    gas_day: date
    published_at: datetime
    stage: str
    scope: str
    metric: str
    unit: str
    value: Decimal
    report_ref: str

    @property
    def series(self):
        return (self.family, self.gas_day, self.scope, self.metric, self.unit)

    @property
    def key(self):
        return (*self.series, self.published_at)


def template():
    return ",".join(FIELDS) + "\n"


def parse_extract(raw, *, now=None):
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("CSV vuoto o superiore a 2 MiB.")
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("Ora di riferimento senza offset.")
    rows = {}
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError("Usa esattamente le intestazioni del modello archivio Jarvis.")
        for i, item in enumerate(reader, 1):
            if i > MAX_ROWS or None in item or any(v is None for v in item.values()):
                raise ValueError("CSV non valido o superiore a 10.000 righe.")
            family, day, stamp, stage, scope, metric, unit, value, ref = (item[k].strip() for k in FIELDS)
            if family not in RULES:
                raise ValueError("Famiglia di pubblicazione non riconosciuta.")
            stages, metrics, units = RULES[family]
            if stage not in stages or metric not in metrics or unit not in units:
                raise ValueError("Fase, metrica o unità non compatibile.")
            if family in {"balance","gas_stock"}:
                valid_scope = scope == "SRG"
            elif family == "wkr":
                valid_scope = bool(re.fullmatch(r"climate:[A-Za-z0-9][A-Za-z0-9_-]{0,39}", scope))
            else:
                valid_scope = bool(re.fullmatch(r"cluster:[A-Za-z0-9][A-Za-z0-9_-]{0,39}", scope))
            if not valid_scope:
                raise ValueError("Perimetro non ammesso: solo rete SRG o zona/cluster pubblico.")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. /-]{0,119}", ref):
                raise ValueError("Riferimento report obbligatorio; usa solo il titolo/ID pubblico.")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or not re.fullmatch(
                    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})", stamp):
                raise ValueError("Data e timestamp ISO con offset obbligatori.")
            gas_day = date.fromisoformat(day)
            issued = datetime.fromisoformat(stamp.replace("Z","+00:00")).astimezone(UTC)
            if not 2000 <= gas_day.year <= 2100 or issued > now:
                raise ValueError("Data o pubblicazione futura/non valida.")
            local_day = issued.astimezone(ROME).date()
            if family != "wkr" and local_day < gas_day:
                raise ValueError("Pubblicazione precedente al giorno di competenza.")
            if family == "wkr" and stage == "observed" and local_day < gas_day:
                raise ValueError("WKR osservato anteriore al giorno di competenza.")
            if not re.fullmatch(r"[+-]?\d{1,15}(?:\.\d{1,12})?", value):
                raise ValueError("Valore numerico non valido; usare punto decimale.")
            amount = Decimal(value)
            if (metric in {"injections","withdrawals","gas_stock","wkr"} and amount < 0):
                raise ValueError("Valore negativo incompatibile con la metrica.")
            row = Record(family, gas_day, issued, stage, scope, metric, unit, amount, ref)
            if row.key in rows and rows[row.key] != row:
                raise ValueError("Conflitto tra pubblicazioni con la stessa chiave.")
            rows[row.key] = row
    except (UnicodeError, csv.Error, InvalidOperation, OverflowError) as error:
        raise ValueError("CSV Jarvis non leggibile.") from error
    if not rows:
        raise ValueError("Nessuna osservazione nell'estratto.")
    return tuple(sorted(rows.values(), key=lambda r:r.key))


def merge_extracts(previous, incoming):
    """Reject the whole import on conflict; retain all distinct publication vintages."""
    merged = {row.key:row for row in previous}
    for row in incoming:
        if row.key in merged and merged[row.key] != row:
            raise ValueError("Conflitto con una pubblicazione già importata; archivio invariato.")
        merged[row.key] = row
    if len(merged) > MAX_ROWS:
        raise ValueError("Archivio sessione superiore a 10.000 osservazioni.")
    return tuple(sorted(merged.values(), key=lambda r:r.key))


def revision_rows(records):
    groups = defaultdict(list)
    for row in records:
        if row.family == "balance":
            groups[row.series].append(row)
    result = []
    for key, rows in sorted(groups.items()):
        rows.sort(key=lambda r:r.published_at)
        final = rows[-1]
        prior = [r for r in rows[:-1] if r.stage == "provisional"]
        # A later provisional version does not silently become a final.
        previous = prior[-1] if final.stage == "definitive" and prior else None
        result.append({"gas_day":final.gas_day.isoformat(),"scope":final.scope,"metric":final.metric,"unit":final.unit,
                       "versions":len(rows),"latest_stage":final.stage,
                       "provisional":previous.value if previous else None,
                       "definitive":final.value if final.stage == "definitive" else None,
                       "delta":final.value-previous.value if previous else None,
                       "provisional_at":previous.published_at.isoformat() if previous else None,
                       "definitive_at":final.published_at.isoformat() if final.stage == "definitive" else None,
                       "provisional_ref":previous.report_ref if previous else None,
                       "definitive_ref":final.report_ref if final.stage == "definitive" else None})
    return result


def latest_records(records):
    latest = {}
    for row in sorted(records,key=lambda r:r.published_at):
        latest[row.series] = row
    return tuple(latest.values())


def record_dict(row):
    return dict(zip(FIELDS,(row.family,row.gas_day.isoformat(),row.published_at.isoformat(),row.stage,
                            row.scope,row.metric,row.unit,str(row.value),row.report_ref),strict=True))


def export_csv(records):
    out = io.StringIO()
    writer = csv.DictWriter(out,fieldnames=(*FIELDS,"source_url","provenance"),lineterminator="\n")
    writer.writeheader()
    for row in records:
        writer.writerow({**record_dict(row),"source_url":SOURCE,"provenance":"user-declared public extract; not independently verified"})
    return out.getvalue()


def import_session(previous, raw, *, now=None):
    previous = previous or {"records":(),"hashes":()}
    incoming = parse_extract(raw, now=now)
    digest = sha256(raw).hexdigest()
    records = merge_extracts(previous["records"],incoming)
    hashes = tuple(dict.fromkeys((*previous["hashes"],digest)))
    if len(hashes)>100:
        raise ValueError("Limite di 100 estratti distinti per sessione.")
    return {"records":records,"hashes":hashes}
