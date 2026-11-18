"""Local public-data archive. Original bytes and validated observations are distinct."""
import argparse
from contextlib import closing
import csv
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import sqlite3

import requests

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 20 * 1024 * 1024
JRC = "jrc_enagad_it_v1_1"
MASE = "mase_unmig_production"
JRC_URL = "https://doi.org/10.5281/zenodo.6364875"
MASE_URL = "https://unmig.mase.gov.it/ricerca-e-coltivazione-di-idrocarburi/produzione-nazionale-di-idrocarburi/"
MASE_CSV = "https://unmig.mase.gov.it/wp-content/uploads/dati/produzione/produzione-2026.csv"
LICENSE = "https://creativecommons.org/licenses/by/4.0/"
SOURCES = {
    JRC: ("Joint Research Centre (Zaccarelli, Giaccaria, Feofilovs, Bolado-Lavín)", JRC_URL),
    MASE: ("MASE – UNMIG", MASE_URL),
}
FIELDS = {"TOT": "demand", "IND": "industry", "GPP": "power", "DIS": "distribution"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS public_snapshot (
    source_id TEXT NOT NULL, digest TEXT NOT NULL, retrieved_at TEXT NOT NULL,
    publisher TEXT NOT NULL, source_url TEXT NOT NULL, file_ref TEXT NOT NULL,
    license_url TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('validated','raw_pending')),
    payload BLOB NOT NULL, PRIMARY KEY(source_id,digest)
);
CREATE TABLE IF NOT EXISTS public_observation (
    source_id TEXT NOT NULL, digest TEXT NOT NULL, period TEXT NOT NULL,
    geography TEXT NOT NULL, metric TEXT NOT NULL, unit TEXT NOT NULL,
    grain TEXT NOT NULL, value TEXT NOT NULL, source_flag TEXT NOT NULL,
    PRIMARY KEY(source_id,digest,period,geography,metric),
    FOREIGN KEY(source_id,digest) REFERENCES public_snapshot(source_id,digest)
);
"""


def default_path():
    return Path(os.getenv("GASOPS_STATE_DIR") or ROOT / ".gasops") / "public-warehouse.sqlite3"


def _decode(raw):
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("File vuoto o superiore a 20 MiB")
    if b"\x00" in raw or raw.lstrip().startswith((b"<", b"{", b"[")):
        raise ValueError("Il contenuto non sembra un CSV")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            if text.lstrip().startswith(("<", "{", "[")):
                raise ValueError("Il contenuto non sembra un CSV")
            return text
        except UnicodeDecodeError:
            continue
    raise ValueError("Codifica CSV non riconosciuta")


def inspect_csv(raw):
    """Structural preview only; no assertion about MASE's native columns or units."""
    text = _decode(raw)
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
        reader = csv.reader(StringIO(text), dialect, strict=True)
        preview = []
        width = None
        count = 0
        for row in reader:
            if not row or not any(cell.strip() for cell in row):
                continue
            if width is None:
                width = len(row)
            if width < 2 or len(row) != width:
                raise ValueError("CSV non rettangolare: verificare il formato originale")
            count += 1
            if len(preview) < 6:
                preview.append(row)
        if count < 2:
            raise ValueError("CSV senza righe di dati")
    except csv.Error as error:
        raise ValueError("Struttura CSV non riconosciuta") from error
    return {"delimiter": dialect.delimiter, "records_including_header": count,
            "preview": preview, "semantic_validation": False}


def jrc_rows(raw):
    lines = [line for line in _decode(raw).splitlines() if not line.startswith("#")]
    reader = csv.DictReader(lines)
    if not reader.fieldnames or not {"GASDAY", "PROC", *FIELDS} <= set(reader.fieldnames):
        raise ValueError("Schema JRC non riconosciuto")
    rows, seen = [], set()
    for item in reader:
        if None in item or any(value is None for value in item.values()):
            raise ValueError("Riga JRC incompleta")
        period = date.fromisoformat(item["GASDAY"]).isoformat()
        flag = item["PROC"]
        if period in seen or flag not in {"O", "E"}:
            raise ValueError("Giorno duplicato o flag JRC sconosciuto")
        seen.add(period)
        for field, metric in FIELDS.items():
            value = item[field].strip()
            if value in ("", "NA"):
                continue
            try:
                amount = Decimal(value)
            except InvalidOperation as error:
                raise ValueError("Valore JRC non numerico") from error
            if not amount.is_finite() or amount < 0:
                raise ValueError("Valore JRC non valido")
            rows.append((period, "IT", metric, "GWh/d", "gas_day", str(amount), flag))
    if not rows:
        raise ValueError("Nessuna osservazione JRC")
    return rows


class Warehouse:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.executescript(SCHEMA)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def ingest(self, source, raw):
        publisher, url = SOURCES[source]
        if source == JRC:
            rows, status, file_ref = jrc_rows(raw), "validated", "data/jrc/IT.v1.1.csv"
        else:
            inspect_csv(raw)
            rows, status, file_ref = [], "raw_pending", MASE_CSV
        digest = sha256(raw).hexdigest()
        with closing(self.connect()) as db, db:
            cursor = db.execute("""INSERT INTO public_snapshot VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_id,digest) DO NOTHING""",
                (source, digest, datetime.now(timezone.utc).isoformat(), publisher, url,
                 file_ref, LICENSE, status, raw))
            if cursor.rowcount:
                db.executemany("INSERT INTO public_observation VALUES (?,?,?,?,?,?,?,?,?)",
                               [(source, digest, *row) for row in rows])
        return {"source": source, "sha256": digest, "status": status,
                "observations": len(rows), "new_snapshot": bool(cursor.rowcount)}

    def manifest(self):
        with closing(self.connect()) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("""SELECT s.source_id,s.digest,s.retrieved_at,s.publisher,s.source_url,
                s.file_ref,s.license_url,s.status,length(s.payload) AS bytes,
                (SELECT count(*) FROM public_observation o WHERE o.source_id=s.source_id AND o.digest=s.digest) AS observations,
                (SELECT min(period) FROM public_observation o WHERE o.source_id=s.source_id AND o.digest=s.digest) AS first_period,
                (SELECT max(period) FROM public_observation o WHERE o.source_id=s.source_id AND o.digest=s.digest) AS last_period
                FROM public_snapshot s ORDER BY retrieved_at DESC, source_id,digest""").fetchall()
            return [dict(row) for row in rows]


def fetch_mase():
    """One request to the exact official link, no redirects or credentials."""
    with requests.get(MASE_CSV, stream=True, timeout=(5, 30), allow_redirects=False) as response:
        if response.status_code != 200:
            raise ValueError(f"MASE: HTTP {response.status_code}; scaricare dal portale ufficiale")
        raw = bytearray()
        for chunk in response.iter_content(65536):
            raw.extend(chunk)
            if len(raw) > MAX_BYTES:
                raise ValueError("CSV superiore a 20 MiB")
    return bytes(raw)


def read_local(path):
    with Path(path).open("rb") as file:
        return file.read(MAX_BYTES + 1)


def main():
    parser = argparse.ArgumentParser(description="Archivio locale di dati pubblici I.G.O.R.")
    parser.add_argument("--db", type=Path, default=default_path())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed-jrc")
    sub.add_parser("fetch-mase")
    manual = sub.add_parser("inspect-mase")
    manual.add_argument("file", type=Path)
    sub.add_parser("manifest")
    args = parser.parse_args()
    try:
        warehouse = Warehouse(args.db)
        if args.command == "seed-jrc":
            result = warehouse.ingest(JRC, read_local(ROOT / "data/jrc/IT.v1.1.csv"))
        elif args.command == "fetch-mase":
            raw = fetch_mase()
            result = {"snapshot": warehouse.ingest(MASE, raw), "structure": inspect_csv(raw)}
        elif args.command == "inspect-mase":
            result = inspect_csv(read_local(args.file))
        else:
            result = warehouse.manifest()
    except (ValueError, OSError, sqlite3.Error, requests.RequestException) as error:
        parser.exit(1, f"Archivio: {error if isinstance(error, ValueError) else type(error).__name__}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
