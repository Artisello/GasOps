"""Limited, deterministic checks of study editions, not a compliance certification."""
from datetime import date,datetime,time,timedelta
from decimal import Decimal,InvalidOperation
from io import StringIO
import csv,re
from .data import ROME
from .commercial_controls import working_offset
from .bso_kpis import closed_gas_day

CDR="CdR XCII"
LNG="CdRig Piombino 2023-I"
FIELDS=("gas_day","stage","I","S","P","C","PE","delta_LPC","GNC")
STATE="network_balance_study_v1"
MAX_BYTES=1_000_000


def month_after(month):
    return (month.replace(day=28)+timedelta(days=4)).replace(day=1)


def calendar(day,month,holidays):
    """Study calendar. Explicit holidays; no invented hour for date-only deadlines."""
    month=month.replace(day=1)
    final=month_after(month).replace(day=28)
    while final.weekday()>=5 or final in holidays:final+=timedelta(days=1)
    next_day=day+timedelta(days=1)
    return [
        ("Termine riformulazione programma G",datetime.combine(next_day,time(3),ROME),CDR+" · cap. 8 §6.7 · p. 351"),
        ("Bilancio provvisorio G",datetime.combine(next_day,time(11,30),ROME),CDR+" · cap. 9 §4.1 · p. 378"),
        ("Bilancio definitivo M",final,CDR+" · cap. 9 §4.2 · p. 379"),
        ("Richiesta rettifica per errori manifesti",working_offset(final,2,holidays),CDR+" · cap. 9 §4.2 · pp. 379–380"),
        ("Proposta consegne GNL M",datetime.combine(working_offset(month,-9,holidays),time(13),ROME),LNG+" · cap. 9 §1.1.1 · p. 88"),
        ("Comunicazione debitore/creditore GNL M",datetime.combine(working_offset(month,-8,holidays),time(12),ROME),LNG+" · cap. 9 §1.1.1 · p. 88"),
    ]


def template():
    return ",".join(FIELDS)+"\n"


def parse_balance(raw,now):
    """All energy terms in GWh, one row per date and phase. GNC alone optional."""
    if not raw or len(raw)>MAX_BYTES:raise ValueError("CSV vuoto o superiore a 1 MB.")
    try:
        reader=csv.DictReader(StringIO(raw.decode("utf-8-sig")),strict=True)
        if tuple(reader.fieldnames or ())!=FIELDS:raise ValueError("Usa le intestazioni del modello.")
        seen=set();out=[]
        for i,r in enumerate(reader,2):
            if i>4001 or None in r or any(v is None for v in r.values()):raise ValueError("Copertura o colonne non valide.")
            d=date.fromisoformat(r["gas_day"])
            if d>closed_gas_day(now) or d.year<2000 or r["stage"] not in ("provisional","definitive"):raise ValueError("Giorno o fase non validi.")
            key=(d,r["stage"])
            if key in seen:raise ValueError("Giorno e fase duplicati.")
            seen.add(key)
            row={"gas_day":d.isoformat(),"stage":r["stage"]}
            for k in FIELDS[2:]:
                v=r[k].strip()
                if k=="GNC" and not v:row[k]=None;continue
                if not re.fullmatch(r"[+-]?\d{1,12}(?:\.\d{1,9})?",v):raise ValueError("Valori assenti o non validi; usare GWh e punto decimale.")
                val=Decimal(v)
                if k in ("I","P","C","PE") and val<0:raise ValueError("Segno incompatibile.")
                row[k]=val
            out.append(row)
        if not out:raise ValueError("Nessun giorno gas.")
        return sorted(out,key=lambda r:(r["gas_day"],r["stage"]))
    except (UnicodeError,csv.Error,InvalidOperation,OverflowError):raise ValueError("CSV non valido.") from None


def balance_checks(rows,tolerance):
    """GNC is residual by definition. Difference only against independently supplied published GNC."""
    if not isinstance(tolerance,Decimal) or not tolerance.is_finite() or tolerance<0:raise ValueError("Tolleranza non valida.")
    out=[]
    for r in rows:
        gnc=r["I"]+r["S"]-r["P"]-r["C"]-r["PE"]-r["delta_LPC"]
        reported=r["GNC"];delta=gnc-reported if reported is not None else None
        out.append({**r,"GNC_calcolato":gnc,"delta_GNC":delta,
                    "esito":"Solo calcolo" if delta is None else "Da verificare" if abs(delta)>tolerance else "Entro tolleranza"})
    return out
