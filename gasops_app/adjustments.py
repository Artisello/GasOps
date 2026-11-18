"""Independent economic adjustment ledger, study edition CdR XCII §§5.1–5.2.
No modification of definitive transport balances or generation of invoices.
Amounts are already determined, normalized, signed pre-tax EUR.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D, InvalidOperation
from collections import defaultdict
from calendar import monthrange
import csv,io,re
from hashlib import sha256

STATE="adjustment_ledger_v1"
MAX_BYTES=2*1024*1024
MAX_ROWS=20000
REF="CdR XCII · cap. 9 §§5.1–5.2 (pp. 404–408); cap. 18 §4.1.5 (pp. 591–593)"
COMPONENTS=("DS","IO","VAR","SCOST","CVU","CVFC","CPU","CMT")
MONTHLY={"IO","SCOST"}
USER_SIGN={"DS","IO"}
FIELDS=("user","session_year","competence","component","baseline_kind","baseline_ref","result_ref",
        "previous_eur","current_eur","published_delta_eur")
SAFE_ID=re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")
AMOUNT=re.compile(r"[+-]?\d{1,12}(?:\.\d{1,8})?")
ZERO=D(0)

@dataclass(frozen=True)
class Row:
    user:str
    session_year:int
    competence:date
    component:str
    baseline_kind:str
    baseline_ref:str
    result_ref:str
    previous:D
    current:D
    published_delta:D|None

    @property
    def key(self):
        return self.user,self.session_year,self.competence,self.component


def template():
    return ",".join(FIELDS)+"\n"


def decimal(v,optional=False):
    v=v.strip()
    if optional and not v:return None
    if not AMOUNT.fullmatch(v):raise ValueError("Importo non valido.")
    return D(v)


def parse(raw,now):
    if not raw or len(raw)>MAX_BYTES:raise ValueError("CSV vuoto o oltre 2 MiB.")
    out={}
    try:
        reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")),strict=True)
        if tuple(reader.fieldnames or ())!=FIELDS:raise ValueError("Intestazioni non riconosciute.")
        for i,x in enumerate(reader,2):
            if i>MAX_ROWS+1 or None in x or any(v is None for v in x.values()):raise ValueError("Copertura o colonne non valide.")
            user,baseline,result=(x[k].strip() for k in ("user","baseline_ref","result_ref"))
            if not all(SAFE_ID.fullmatch(v) for v in (user,baseline,result)) or baseline==result:raise ValueError("Usa ID fittizi e riferimenti distinti.")
            if not re.fullmatch(r"\d{4}",x["session_year"]):raise ValueError("Anno sessione non valido.")
            y=int(x["session_year"]);p=date.fromisoformat(x["competence"])
            c=x["component"];kind=x["baseline_kind"]
            if p.isoformat()!=x["competence"] or p.year<2020 or y>now.year or not 1<=y-p.year<=5 or c not in COMPONENTS or c in MONTHLY and p.day!=1:
                raise ValueError("Periodo o componente non validi.")
            if kind!=("balancing" if y-p.year==1 else "adjustment"):
                raise ValueError("Baseline non coerente con sessione annuale/pluriennale.")
            r=Row(user,y,p,c,kind,baseline,result,decimal(x["previous_eur"]),decimal(x["current_eur"]),decimal(x["published_delta_eur"],True))
            if r.key in out and out[r.key]!=r:raise ValueError("Riga in conflitto.")
            out[r.key]=r
    except (UnicodeError,csv.Error,InvalidOperation,OverflowError):raise ValueError("CSV non valido.") from None
    if not out:raise ValueError("Nessuna partita.")
    return tuple(sorted(out.values(),key=lambda r:r.key))


def _write(records):
    s=io.StringIO()
    w=csv.DictWriter(s,fieldnames=FIELDS,lineterminator="\n");w.writeheader()
    for r in records:
        w.writerow(dict(zip(FIELDS,(r.user,r.session_year,r.competence.isoformat(),r.component,r.baseline_kind,
             r.baseline_ref,r.result_ref,r.previous,r.current,r.published_delta),strict=True)))
    return s.getvalue()


def merge(previous,raw,now):
    incoming=parse(raw,now)
    rows={r.key:r for r in (previous or {}).get("rows",())}
    for r in incoming:
        if r.key in rows and rows[r.key]!=r:raise ValueError("Versione in conflitto: non sovrascrivere un esito. Esporta e verifica.")
        rows[r.key]=r
    if len(rows)>MAX_ROWS:raise ValueError("Archivio al limite.")
    ordered=tuple(sorted(rows.values(),key=lambda r:r.key))
    hashes=tuple(dict.fromkeys((*(previous or {}).get("hashes",()),sha256(raw).hexdigest())))
    if len(hashes)>100:raise ValueError("Limite estratti raggiunto.")
    return {"rows":ordered,"hashes":hashes,"sha256":sha256(_write(ordered).encode()).hexdigest()}


def archive_csv(saved):
    return _write(saved["rows"])


def economic_legs(previous,current,component):
    """Signed variation from user perspective. Tariff costs have reverse sign.
    Sign reversals on DS/IO require separate reversal/rebooking; not document types.
    Zero and special cases require review rather than guessing the legal treatment.
    """
    delta=current-previous
    if component in USER_SIGN and previous*current<0:
        return (-previous,current),"Inversione segno · verifica documenti"
    change=delta if component in USER_SIGN else -delta
    if not delta:return (ZERO,),"Invariata"
    if component in USER_SIGN and (previous==0 or current==0):label="Passaggio per zero · verifica"
    elif component in ("CPU","CMT"):label="Applicabilità e adeguamento sistemi da verificare"
    else:label="Variazione economica"
    return (change,),label


def controls(rows,user,session_year,year,month,tolerance=D(".01"),balances=()):
    if not tolerance.is_finite() or tolerance<0:raise ValueError("Tolleranza non valida.")
    selected=[r for r in rows if r.user==user and r.session_year==session_year and (r.competence.year,r.competence.month)==(year,month)]
    # Use only an unambiguous definitive baseline from the existing ledger.
    orig=defaultdict(list)
    for x in balances:
        if x.user==user and x.day.year==year and x.day.month==month:orig[x.day].append(x)
    prior={}
    for day,versions in orig.items():
        versions.sort(key=lambda x:x.version)
        if len({x.version for x in versions})!=len(versions) or versions[-1].stage!="definitive":continue
        if any(x.storage_net!=versions[0].storage_net for x in versions):continue
        if any(a.stage=="definitive" and b.stage=="provisional" for a,b in zip(versions,versions[1:])):continue
        if versions[-1].buy is not None and versions[-1].sell is not None and versions[-1].buy<versions[-1].sell:continue
        prior[day]=versions[-1].cash
    previous_sessions={r.key:r for r in rows}
    out=[]
    for r in selected:
        delta=r.current-r.previous
        legs,label=economic_legs(r.previous,r.current,r.component)
        discrepancy=None if r.published_delta is None else r.published_delta-delta
        baseline_difference=None
        if r.component=="DS" and r.baseline_kind=="balancing" and prior.get(r.competence) is not None:
            baseline_difference=r.previous-prior[r.competence]
        issues=[]
        baseline_check="Non confrontata"
        if baseline_difference is not None:baseline_check="Definitivo importato"
        if r.baseline_kind=="adjustment":
            predecessor=previous_sessions.get((r.user,r.session_year-1,r.competence,r.component))
            if predecessor is not None:
                if predecessor.result_ref!=r.baseline_ref:issues.append("Riferimento alla sessione precedente discordante")
                else:
                    baseline_difference=r.previous-predecessor.current
                    baseline_check="Precedente esito importato"
        if discrepancy is not None and abs(discrepancy)>tolerance:issues.append("Delta pubblicato discordante")
        if baseline_difference is not None and abs(baseline_difference)>tolerance:issues.append("Baseline DS discordante" if r.component=="DS" else "Baseline economica discordante")
        if "verifica" in label:issues.append(label)
        out.append({"competence":r.competence.isoformat(),"component":r.component,"previous_eur":r.previous,"current_eur":r.current,
                    "delta_eur":delta,"published_delta_eur":r.published_delta,"difference_eur":discrepancy,
                    "baseline_difference_eur":baseline_difference,"baseline_check":baseline_check,"debit_eur":sum((-v for v in legs if v<0),ZERO),
                    "credit_eur":sum((v for v in legs if v>0),ZERO),"classification":label,"issues":"; ".join(issues),
                    "baseline_kind":r.baseline_kind,"baseline_ref":r.baseline_ref,"result_ref":r.result_ref})
    return out


def coverage(results,year,month):
    """Absent component/day is missing, not zero or proven inapplicable."""
    out=[]
    for c in COMPONENTS:
        rows=[r for r in results if r["component"]==c]
        need=1 if c in MONTHLY else monthrange(year,month)[1]
        out.append({"component":c,"received":len(rows),"expected":need,
                    "compared":sum(r["published_delta_eur"] is not None for r in rows),
                    "issues":sum(bool(r["issues"]) for r in rows)})
    return out


def monthly(results):
    if not results:return None
    return {"debit":sum((r["debit_eur"] for r in results),ZERO),"credit":sum((r["credit_eur"] for r in results),ZERO),
            "exceptions":sum(bool(r["issues"]) for r in results),"compared":sum(r["published_delta_eur"] is not None for r in results),
            "rows":len(results)}
