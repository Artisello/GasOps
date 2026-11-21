"""Read-only presentation fixtures; never read or mutate imported user records."""
from datetime import date, datetime

import pandas as pd

from .bso_kpis import operations_metrics, settlement_metrics, task_demo
from .data import ROME
from .operations_ledger import sample_rows

AS_OF = datetime(2026, 11, 18, 14, tzinfo=ROME)
CASE_DAY = date(2026, 9, 5)


def balancing_case():
    """Illustrative intraday publications, not observations or model predictions."""
    values = (-42, -34, -25, -16, -8, 6, 15, 23)
    rows = pd.DataFrame({
        "published_at": [AS_OF.replace(hour=hour) for hour in range(7, 15)],
        "sas_gwh": values,
    })
    previous, latest = rows.iloc[-2], rows.iloc[-1]
    changes = rows.loc[rows.sas_gwh.mul(rows.sas_gwh.shift(1)) < 0]
    return {"rows": rows, "latest": int(latest.sas_gwh),
            "delta": int(latest.sas_gwh - previous.sas_gwh),
            "sign_change_at": changes.iloc[-1].published_at if len(changes) else None}


def cases():
    rows = sample_rows()
    settlement = settlement_metrics(rows, "DEMO-001", 2026, 9, date(2026, 11, 17))
    revision = next(r for r in settlement["records"] if r["day"] == CASE_DAY.isoformat())
    versions = sorted((r for r in rows if r.day == CASE_DAY), key=lambda r: r.version)
    operations = operations_metrics(task_demo(), AS_OF, 2026, 11)
    return {"balancing": balancing_case(), "settlement": settlement, "revision": revision,
            "versions": versions, "operations": operations}


def briefing(pack):
    """Deterministic prose from the same evidence shown in the three workspaces."""
    from .italiano import numero
    b, r, o = pack["balancing"], pack["revision"], pack["operations"]
    change = b["sign_change_at"]
    return (
        f"Balancing · SAS di esempio {numero(b['latest'], 0, signed=True)} GWh alle 14:00. "
        + (f"Cambio di segno alle {change:%H:%M}; " if change is not None else "")
        + "la stima di sistema resta distinta dal saldo del partecipante.",
        f"Settlement · La revisione del 5 settembre modifica l’importo di "
        f"{numero(r['delta_cash_eur'], 0)} €. La variazione deriva dai volumi, a prezzi invariati.",
        f"Operations · {len(o['overdue'])} attività scadute e {len(o['upcoming'])} in scadenza "
        "entro sette giorni. La prima coda separa i ritardi dalle attività future.",
    )
