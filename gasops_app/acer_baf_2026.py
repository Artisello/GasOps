"""Visually transcribed labelled observations from the supplied October 2026 ACER PDF."""
import csv
from decimal import Decimal, InvalidOperation
from collections import Counter
from pathlib import Path
import re

from .acer_market import balancing_rows, REPORT_2026

ROOT=Path(__file__).resolve().parents[1]
PDF_SHA256="3fea1b14791aba9dc6ed6b926fb5bec000126c60adada2d043fef22d182e1807"
SELECTED="EU-SELECTED"
METRICS={"imbalance_share":"%","net_adjusted_neutrality":"EUR/MWh","tso_buy_share":"%",
         "tso_action_days_share":"%","tso_action_volume_share":"%"}
PAGES={9:(SELECTED,"tso_action_days_share"),10:(SELECTED,"tso_action_volume_share"),
       11:(SELECTED,"imbalance_share"),15:(None,"imbalance_share"),16:(None,"tso_buy_share"),
       19:(None,"net_adjusted_neutrality")}
EXPECTED={9:8,10:8,11:8,15:23,16:13,19:23}


def report_2026_rows():
    result=[]
    seen=set()
    path=ROOT/"data/acer/balancing-report-2026.csv"
    with path.open(encoding="utf-8",newline="") as f:
        r=csv.DictReader(f,strict=True)
        if r.fieldnames!=["gas_year","zone","metric","unit","value","page"]:
            raise ValueError("Schema report ACER 2026 inatteso.")
        for item in r:
            if None in item or any(v is None for v in item.values()):
                raise ValueError("Riga report ACER non valida.")
            year,zone,metric,unit=item["gas_year"],item["zone"],item["metric"],item["unit"]
            page=int(item["page"])
            if not re.fullmatch(r"20\d{2}/20\d{2}",year) or int(year[5:])!=int(year[:4])+1:
                raise ValueError("Anno gas non valido.")
            if not re.fullmatch(r"[A-Z][A-Z-]{1,14}",zone) or METRICS.get(metric)!=unit or page not in PAGES:
                raise ValueError("Zona, metrica, unità o pagina non valida.")
            expected_zone,expected_metric=PAGES[page]
            if metric!=expected_metric or (zone==SELECTED)!=(expected_zone==SELECTED):
                raise ValueError("Perimetro o pagina incompatibile.")
            if (zone==SELECTED and not "2017/2018"<=year<="2024/2025"
                or zone!=SELECTED and year!="2024/2025" and not (page==16 and year=="2023/2024")):
                raise ValueError("Anno gas incompatibile con il grafico.")
            try:
                value=Decimal(item["value"])
            except InvalidOperation as exc:
                raise ValueError("Valore ACER non valido.") from exc
            if not value.is_finite() or (unit=="%" and not 0<=value<=100):
                raise ValueError("Valore ACER fuori intervallo.")
            key=(year,zone,metric)
            if key in seen:
                raise ValueError("Dato ACER duplicato.")
            seen.add(key)
            result.append({**item,"value":value,"page":page,"source":"ACER, report ottobre 2026",
                           "source_url":REPORT_2026,"provenance":"trascrizione visiva PDF fornito, etichette arrotondate",
                           "source_pdf_sha256":PDF_SHA256})
    if Counter(r["page"] for r in result)!=EXPECTED:
        raise ValueError("Copertura trascrizione ACER inattesa.")
    return tuple(result)


def all_baf_rows():
    historical=[{**r,"source_pdf_sha256":""} for r in balancing_rows()]
    return (*historical,*report_2026_rows())


def zone_changes(rows,metric):
    """Compare same zone/metric/unit only. Missing pairs stay None."""
    groups={}
    for r in rows:
        if r["metric"]!=metric or r["zone"]==SELECTED or r["gas_year"] not in ("2023/2024","2024/2025"):
            continue
        group=groups.setdefault((r["zone"],r["unit"]),{})
        if r["gas_year"] in group:
            raise ValueError("Anno gas duplicato.")
        group[r["gas_year"]]=r
    result=[]
    for (zone,unit),g in sorted(groups.items()):
        a,b=g.get("2023/2024"),g.get("2024/2025")
        result.append({"zone":zone,"unit":unit,"2023/2024":a["value"] if a else None,
                       "2024/2025":b["value"] if b else None,
                       "delta":b["value"]-a["value"] if a and b else None})
    return result
