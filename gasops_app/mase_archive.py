"""Attributed transcriptions of public UNMIG tables, not native CSV exports."""
import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MASE_SOURCE = "https://unmig.mase.gov.it/ricerca-e-coltivazione-di-idrocarburi/produzione-nazionale-di-idrocarburi/"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
PUBLISHER = "MASE – UNMIG"
NATIONAL = ("IT", "IT:onshore", "IT:offshore")
REGIONS = ("Abruzzo", "Basilicata", "Calabria", "Emilia-Romagna", "Lombardia", "Marche",
           "Molise", "Puglia", "Sicilia", "Toscana")
ZONES = ("A", "B", "C", "D", "G")


@dataclass(frozen=True)
class Report:
    filename: str
    url: str
    label: str
    first: str
    last: str
    unit: str


REPORTS = {
    "mase_unmig_databook_2025": Report("unmig-databook-2025.csv",
        "https://unmig.mase.gov.it/wp-content/uploads/2025/09/databook-2025.pdf",
        "Databook 2025 · attività 2024 · tabella storica", "2004", "2024", "bcm"),
    "mase_unmig_report_2025": Report("unmig-2025.csv",
        "https://unmig.mase.gov.it/wp-content/uploads/dati/produzione/produzione-2025.pdf",
        "Report 2025 · aggiornamento 27/04/2026", "2025", "2025-12", "Sm3"),
    "mase_unmig_report_2026_feb": Report("unmig-2026-feb.csv",
        "https://unmig.mase.gov.it/wp-content/uploads/dati/produzione/produzione-2026.pdf",
        "Report 2026 · versione 22/05/2026, dati al 28/02", "2026-01", "2026-02", "Sm3"),
}


def read_report(source):
    return (ROOT / "data" / "mase" / REPORTS[source].filename).read_bytes()


def report_rows(source, raw):
    """Strict validation of our normalized transcription, not the upstream format."""
    report = REPORTS[source]
    reader = csv.DictReader(StringIO(raw.decode("utf-8-sig")), strict=True)
    if reader.fieldnames != ["period", "geography", "value", "unit"]:
        raise ValueError("Schema trascrizione UNMIG non riconosciuto")
    rows = {}
    for item in reader:
        if None in item or any(v is None for v in item.values()):
            raise ValueError("Riga UNMIG incompleta")
        period, geo, value, unit = (item[k] for k in reader.fieldnames)
        if not re.fullmatch(r"\d{4}(?:-\d{2})?", period):
            raise ValueError("Periodo UNMIG non valido")
        if len(period) == 7:
            date.fromisoformat(period + "-01")
        if not report.first <= period <= report.last or unit != report.unit:
            raise ValueError("Periodo o unità non coerenti con il report")
        grain = "year" if len(period) == 4 else "month"
        allowed = set(NATIONAL)
        if source == "mase_unmig_report_2025" and grain == "year":
            allowed |= {"region:" + r for r in REGIONS} | {"zone:" + z for z in ZONES}
        if geo not in allowed or (period, geo) in rows:
            raise ValueError("Area sconosciuta o duplicato UNMIG")
        try:
            amount = Decimal(value)
        except InvalidOperation as error:
            raise ValueError("Valore UNMIG non numerico") from error
        if not amount.is_finite() or amount < 0 or (unit == "Sm3" and amount != amount.to_integral_value()):
            raise ValueError("Valore UNMIG non valido")
        rows[(period, geo)] = amount
    if source == "mase_unmig_databook_2025":
        expected = {(str(y), g) for y in range(2004, 2025) for g in NATIONAL}
    elif source == "mase_unmig_report_2025":
        expected = {(f"2025-{m:02d}", g) for m in range(1, 13) for g in NATIONAL}
        expected |= {("2025", g) for g in (*NATIONAL, *("region:" + r for r in REGIONS), *("zone:" + z for z in ZONES))}
    else:
        expected = {(f"2026-{m:02d}", g) for m in (1, 2) for g in NATIONAL}
    if set(rows) != expected:
        raise ValueError("Copertura della trascrizione incompleta o inattesa")
    # Public tables round historical figures and may contain small internal
    # inconsistencies. Preserve all reported values and expose discrepancies.
    result = [(period, geo, "production", report.unit, "year" if len(period) == 4 else "month",
               str(value), "transcribed_public_report") for (period, geo), value in sorted(rows.items())]
    return result


def observations():
    result = []
    for source, report in REPORTS.items():
        for period, geo, metric, unit, grain, value, flag in report_rows(source, read_report(source)):
            result.append(dict(period=period, geography=geo, metric=metric, unit=unit, grain=grain,
                               value=value, source_id=source, source_url=report.url, edition=report.label,
                               publisher=PUBLISHER, license_url=LICENSE_URL, source_flag=flag))
    return result


def as_bcm(value, unit):
    amount = Decimal(value)
    if unit == "bcm":
        return amount
    if unit == "Sm3":
        return amount / Decimal(10**9)
    raise ValueError("Unità non supportata")


def national_gap(rows):
    """Total minus onshore/offshore; no automatic correction."""
    return rows["IT"] - rows["IT:onshore"] - rows["IT:offshore"]
