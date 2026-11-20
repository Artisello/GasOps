"""Daily settlement control on explicitly supplied gas days; not an official ledger."""
import csv
import io
import re
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal as D, InvalidOperation
from hashlib import sha256

from .gas_calendar import closed_gas_day, gas_day_bounds
from .operations_ledger import BalanceRow, monetary, sample_rows

FIELDS=("user","day","version","stage","injected_mwh","storage_net_mwh","psv_net_mwh","withdrawn_mwh","buy_eur_mwh","sell_eur_mwh")
MAX_BYTES=2*1024*1024
MAX_ROWS=10000
LIMIT=D("1e12")
PRICE_LIMIT=D("1e6")


def csv_text(rows,fields=None):
    output=io.StringIO()
    writer=csv.DictWriter(output,fieldnames=fields or list(rows[0]),lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def template():
    return csv_text([dict(zip(FIELDS,(r.user,r.day.isoformat(),r.version,r.stage,r.injected,r.storage_net,
                        r.psv_net,r.withdrawn,r.buy,r.sell),strict=True)) for r in sample_rows()],FIELDS)


def archive_csv(rows):
    ordered = sorted(rows, key=lambda row: (row.user, row.day, row.version))
    records = [dict(zip(FIELDS, (row.user, row.day.isoformat(), row.version, row.stage,
                    row.injected, row.storage_net, row.psv_net, row.withdrawn, row.buy, row.sell), strict=True))
               for row in ordered]
    return csv_text(records, FIELDS)


def merge_csv(previous, raw):
    """Add immutable versions atomically. Identical rows in a later file are idempotent."""
    incoming = parse_csv(raw)
    existing = (previous or {}).get("rows", ())
    merged = {(row.user, row.day, row.version): row for row in existing}
    if len(merged) != len(existing):
        raise ValueError("Il registro precedente contiene versioni duplicate. Verifica il file originale.")
    added = 0
    for row in incoming:
        key = row.user, row.day, row.version
        if key in merged and merged[key] != row:
            raise ValueError(
                f"Versione in conflitto per {row.user}, {row.day}, v{row.version}. "
                "Correggi la fonte o importa una nuova versione."
            )
        if key not in merged:
            merged[key] = row
            added += 1
    if len(merged) > MAX_ROWS:
        raise ValueError("Il registro supera il limite di 10.000 versioni.")
    prior_hashes = (previous or {}).get("hashes", ())
    if not prior_hashes and previous and previous.get("sha"):
        prior_hashes = (previous["sha"],)
    hashes = tuple(dict.fromkeys((*prior_hashes, sha256(raw).hexdigest())))
    if len(hashes) > 100:
        raise ValueError("Limite di 100 estratti raggiunto. Esporta il registro prima di iniziare una nuova sessione.")
    rows = sorted(merged.values(), key=lambda row: (row.user, row.day, row.version))
    return {"rows": rows, "sha": sha256(archive_csv(rows).encode()).hexdigest(),
            "hashes": hashes, "added": added, "unchanged": len(incoming) - added}


def parse_csv(raw):
    if not raw or len(raw)>MAX_BYTES:
        raise ValueError("CSV vuoto o superiore a 2 MiB.")
    try:
        reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")),strict=True)
        if reader.fieldnames!=list(FIELDS):
            raise ValueError("Intestazioni non riconosciute. Usa il modello CSV.")
        rows=[]
        seen=set()
        for line,item in enumerate(reader,start=2):
            if len(rows)>=MAX_ROWS:
                raise ValueError("Limite di 10.000 righe superato.")
            if None in item or any(v is None for v in item.values()):
                raise ValueError(f"Riga {line}: numero di colonne errato.")
            user=item["user"].strip()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,39}",user):
                raise ValueError(f"Riga {line}: usa solo un identificativo fittizio.")
            def decimal(name,optional=False):
                raw_value=item[name].strip()
                if not raw_value and optional:
                    return None
                if not re.fullmatch(r"[+-]?\d{1,15}(?:\.\d{1,8})?",raw_value):
                    raise ValueError(f"Riga {line}: {name} non valido (decimale con punto).")
                n=D(raw_value)
                bound=PRICE_LIMIT if optional else LIMIT
                if abs(n)>bound:
                    raise ValueError(f"Riga {line}: {name} fuori limite.")
                return n
            try:
                day=date.fromisoformat(item["day"].strip())
                if day.isoformat()!=item["day"].strip():
                    raise ValueError()
                raw_version=item["version"].strip()
                if not re.fullmatch(r"[1-9]\d{0,5}",raw_version):
                    raise ValueError()
                version=int(raw_version)
                stage=item["stage"].strip()
                row=BalanceRow(user,day,version,stage,decimal("injected_mwh"),
                               decimal("storage_net_mwh"),decimal("psv_net_mwh"),decimal("withdrawn_mwh"),
                               decimal("buy_eur_mwh",True),decimal("sell_eur_mwh",True))
                if row.injected<0 or row.withdrawn<0:
                    raise ValueError()
            except (ValueError,InvalidOperation):
                raise ValueError(f"Riga {line}: data, versione, fase o valore numerico non valido.") from None
            key=(user,day,version)
            if key in seen:
                raise ValueError(f"Riga {line}: utente/giorno/versione duplicati.")
            seen.add(key)
            rows.append(row)
        if not rows:
            raise ValueError("Nessuna riga dati.")
        return rows
    except (UnicodeError,csv.Error):
        raise ValueError("CSV non leggibile: usa UTF-8 e separatore virgola.") from None


def applicable_price(row):
    return row.buy if row.imbalance<0 else row.sell if row.imbalance>0 else None


def revision_effects(prev,last):
    """Ordered bridge: value final DS at prior side-specific prices, then reprice.
    Known total delta is retained even when a counterfactual price is absent.
    """
    delta=None if prev.cash is None or last.cash is None else last.cash-prev.cash
    if delta is None:
        return None,None,None
    old_price=prev.buy if last.imbalance<0 else prev.sell if last.imbalance>0 else D(0)
    if old_price is None:
        return delta,None,None
    intermediate=monetary(last.imbalance*old_price)
    quantity=intermediate-prev.cash
    return delta,quantity,last.cash-intermediate


def daily_controls(rows, user, year, month, *, closed_day=None):
    cutoff = closed_day if closed_day is not None else closed_gas_day(datetime.now(timezone.utc))
    grouped=defaultdict(list)
    for row in rows:
        if row.user==user and (row.day.year,row.day.month)==(year,month):
            grouped[row.day].append(row)
    days=[]
    for day_no in range(1,monthrange(year,month)[1]+1):
        day=date(year,month,day_no)
        versions=sorted(grouped[day],key=lambda r:r.version)
        start, end = gas_day_bounds(day)
        closed = day <= cutoff
        issues = [] if closed else ["Giorno gas non concluso"]
        record = {
            "day": day.isoformat(), "version": None, "stage": "missing" if closed else "pending",
            "ds_mwh": None, "cash_eur": None, "prior_ds_mwh": None, "delta_ds_mwh": None,
            "delta_cash_eur": None, "quantity_effect_eur": None, "price_effect_eur": None,
            "previous_version": None, "previous_stage": None, "version_delta_ds_mwh": None,
            "version_delta_cash_eur": None, "version_quantity_effect_eur": None, "version_price_effect_eur": None,
            "issues": issues, "eligible": False, "closed": closed,
            "start_utc": start.isoformat(), "end_utc": end.isoformat(),
            "elapsed_hours": int((end - start).total_seconds() / 3600),
        }
        if not versions:
            if closed:
                issues.append("Giorno assente")
            days.append(record)
            continue
        if len({row.version for row in versions}) != len(versions):
            record["stage"] = "invalid"
            issues.append("Versioni duplicate o in conflitto")
            days.append(record)
            continue
        last=versions[-1]
        prior=[r for r in versions[:-1] if r.stage=="provisional"]
        prev=prior[-1] if last.stage=="definitive" and prior else None
        storage_change=any(r.storage_net!=versions[0].storage_net for r in versions)
        stage_regression=any(a.stage=="definitive" and b.stage=="provisional" for a,b in zip(versions,versions[1:]))
        if storage_change:
            issues.append("Variazione stoccaggio tra versioni")
        if stage_regression:
            issues.append("Regressione definitiva → provvisoria")
        if last.stage!="definitive":
            issues.append("Definitivo assente")
        if last.cash is None:
            issues.append("Prezzo applicabile mancante")
        if applicable_price(last) is not None and applicable_price(last)<0:
            issues.append("Prezzo applicabile negativo")
        if last.buy is not None and last.sell is not None and last.buy<last.sell:
            issues.append("Prezzo acquisto inferiore a vendita")
        previous = versions[-2] if len(versions) > 1 else None
        delta, quantity, price = revision_effects(prev, last) if prev and closed else (None, None, None)
        version_delta, version_quantity, version_price = (
            revision_effects(previous, last) if previous and closed else (None, None, None)
        )
        record.update({"version": last.version, "stage": last.stage,
                       "ds_mwh": last.imbalance, "cash_eur": last.cash,
                       "prior_ds_mwh": prev.imbalance if prev else None,
                       "delta_ds_mwh": last.imbalance - prev.imbalance if prev and closed else None,
                       "delta_cash_eur": delta, "quantity_effect_eur": quantity, "price_effect_eur": price,
                       "previous_version": previous.version if previous else None,
                       "previous_stage": previous.stage if previous else None,
                       "version_delta_ds_mwh": last.imbalance - previous.imbalance if previous and closed else None,
                       "version_delta_cash_eur": version_delta,
                       "version_quantity_effect_eur": version_quantity, "version_price_effect_eur": version_price,
                       "eligible": not issues and last.stage == "definitive" and last.cash is not None})
        days.append(record)
    return days


def monthly_summary(days):
    eligible=[r for r in days if r["eligible"]]
    priced=[r for r in eligible if r["cash_eur"] is not None]
    # Amounts are explicitly a subtotal of eligible days only.
    debits=sum((-r["cash_eur"] for r in priced if r["cash_eur"]<0),D(0)) if priced else None
    credits=sum((r["cash_eur"] for r in priced if r["cash_eur"]>0),D(0)) if priced else None
    revisions=[r for r in days if r["delta_cash_eur"] is not None]
    return {"eligible":len(eligible),"expected":len(days),
            "exceptions":sum(bool(r["issues"]) and r.get("closed", True) for r in days),
            "complete":bool(days) and len(eligible)==len(days),
            "debits":debits,"credits":credits,"revision_abs":sum((abs(r["delta_cash_eur"]) for r in revisions),D(0)) if revisions else None,
            "comparable":len(revisions), "closed":sum(r.get("closed", True) for r in days),
            "pending":sum(not r.get("closed", True) for r in days)}
