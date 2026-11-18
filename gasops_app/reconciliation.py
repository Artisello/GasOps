"""Independent, session-only reconciliation of declared definitive settlement extracts."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D
from hashlib import sha256
from collections import defaultdict
import csv,io,re
from .settlement_desk import daily_controls,monthly_summary
from .operations_ledger import monetary
from .commercial_controls import Invoice,BILL_REF

MAX_BYTES=2*1024*1024
MAX_ROWS=10000
SAFE=re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")
AMOUNT=re.compile(r"[+-]?\d{1,12}(?:\.\d{1,8})?")
FIELDS=("user","day","version","reference","ds_mwh","cash_eur")
DOCUMENT_FIELDS=("user","month","group","reference","amount_eur","issue_date")
ZERO=D(0)
# Diagnostic tolerances only, not Snam acceptance rules.
ENERGY_TOL=D(".001")
MONEY_TOL=D(".01")


@dataclass(frozen=True)
class Reported:
    user:str
    day:date
    version:int
    reference:str
    ds:D
    cash:D


def template(fields=FIELDS):
    return ",".join(fields)+"\n"


def _rows(raw,fields):
    if not raw or len(raw)>MAX_BYTES:raise ValueError("CSV vuoto o oltre 2 MiB.")
    try:
        reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")),strict=True)
        if tuple(reader.fieldnames or ())!=fields:raise ValueError("Usa le intestazioni del modello CSV.")
        for i,row in enumerate(reader,1):
            if i>MAX_ROWS or None in row or any(v is None for v in row.values()):
                raise ValueError("Numero di colonne o righe non valido.")
            yield row
    except (UnicodeError,csv.Error):
        raise ValueError("CSV UTF-8 non leggibile.") from None


def _id(value):
    if not SAFE.fullmatch(value):raise ValueError("Usa identificativi fittizi alfanumerici.")
    return value


def _day(value):
    d=date.fromisoformat(value)
    if d.isoformat()!=value or not 2000<=d.year<=2100:raise ValueError("Data non valida.")
    return d


def _amount(value,*,money=False):
    if not AMOUNT.fullmatch(value):raise ValueError("Importo o quantità non validi.")
    n=D(value)
    if money and n!=monetary(n):raise ValueError("Importo comunicato richiesto in centesimi.")
    return n


def parse_report(raw,closed_day):
    result={}
    for r in _rows(raw,FIELDS):
        user,ref=_id(r["user"]),_id(r["reference"])
        day=_day(r["day"])
        if day>closed_day or not re.fullmatch(r"[1-9]\d{0,5}",r["version"]):
            raise ValueError("Solo giorni gas conclusi e revisioni numeriche positive.")
        x=Reported(user,day,int(r["version"]),ref,_amount(r["ds_mwh"]),_amount(r["cash_eur"],money=True))
        key=(user,day,x.version)
        if key in result and result[key]!=x:raise ValueError("Versione comunicata discordante.")
        result[key]=x
    if not result:raise ValueError("Nessuna partita comunicata.")
    return {"rows":tuple(result[k] for k in sorted(result)),"sha":sha256(raw).hexdigest()}


def parse_documents(raw,today):
    result={}
    for r in _rows(raw,DOCUMENT_FIELDS):
        user,ref=_id(r["user"]),_id(r["reference"])
        month=_day(r["month"]+"-01")
        issue=_day(r["issue_date"])
        amount=_amount(r["amount_eur"],money=True)
        next_month=date(month.year+int(month.month==12),month.month%12+1,1)
        if r["group"] not in ("short","long") or amount<0 or not next_month<=issue<=today:
            raise ValueError("Gruppo, importo o data emissione non validi.")
        # Only ordinary monthly original DS documents; no correction notes.
        x=Invoice(ref,user,month.year,month.month,r["group"],amount,issue)
        if ref in result and result[ref]!=x:raise ValueError("Documento con identificativo discordante.")
        result[ref]=x
    if not result:raise ValueError("Nessun documento.")
    return {"rows":tuple(result[k] for k in sorted(result)),"sha":sha256(raw).hexdigest()}


def reconcile_days(balances,reported,user,year,month,closed_day):
    selected=[r for r in reported if r.user==user and (r.day.year,r.day.month)==(year,month)]
    by=defaultdict(dict)
    for r in selected:
        if r.version in by[r.day] and by[r.day][r.version]!=r:raise ValueError("Versioni comunicate discordanti.")
        by[r.day][r.version]=r
    results=[]
    for row in daily_controls(balances,user,year,month):
        day=date.fromisoformat(row["day"])
        if day>closed_day:continue
        versions=by.get(day,{})
        version=row["version"]
        latest=max(versions,default=None)
        observed=versions.get(version)
        # A newer external version invalidates an older matched pair.
        matched=observed is not None and latest==version
        issues=list(row["issues"])
        ds_delta=cash_delta=None
        if not row["eligible"]:
            status="BILANCIO NON VALIDABILE"
        elif not versions:
            status="ESTRATTO ASSENTE"
        elif not matched:
            status="VERSIONE DISCORDANTE"
        else:
            ds_delta=observed.ds-row["ds_mwh"]
            cash_delta=observed.cash-row["cash_eur"]
            status="DIFFERENZA" if abs(ds_delta)>ENERGY_TOL or abs(cash_delta)>MONEY_TOL else "QUADRA"
            if abs(ds_delta)>ENERGY_TOL:issues.append("DS discordante")
            if abs(cash_delta)>MONEY_TOL:issues.append("Importo discordante")
        ref=observed if matched else versions.get(latest)
        results.append({"day":row["day"],"version":version,"reported_version":latest,
                        "reference":ref.reference if ref else None,"ds_expected":row["ds_mwh"],
                        "ds_reported":ref.ds if ref else None,"ds_delta":ds_delta,
                        "cash_expected":row["cash_eur"],"cash_reported":ref.cash if ref else None,
                        "cash_delta":cash_delta,"status":status,"issues":"; ".join(issues)})
    return results


def score(results):
    compared=[r for r in results if r["cash_delta"] is not None]
    return {"expected":len(results),"compared":len(compared),
            "matched":sum(r["status"]=="QUADRA" for r in results),
            "exceptions":sum(r["status"]!="QUADRA" for r in results),
            "gross_difference":sum((abs(r["cash_delta"]) for r in compared),ZERO) if compared else None,
            "unknown":len(results)-len(compared)}


def reconcile_documents(balances,documents,user,year,month,closed_day):
    daily=daily_controls(balances,user,year,month)
    complete=monthly_summary(daily)["complete"] and date.fromisoformat(daily[-1]["day"])<=closed_day
    selected=[r for r in documents if (r.user,r.year,r.month)==(user,year,month)]
    result=[]
    for group in ("short","long"):
        expected=None if not complete else sum((abs(r["cash_eur"]) for r in daily
                    if (r["ds_mwh"]<0 if group=="short" else r["ds_mwh"]>0)),ZERO)
        matches=[r for r in selected if r.group==group]
        observed=matches[0].amount if len(matches)==1 else None
        delta=observed-expected if observed is not None and expected is not None else None
        status=("BILANCI INCOMPLETI" if not complete else "NON DOVUTA" if expected==0 and not matches
                else "MANCANTE" if not matches else "MULTIPLA · VERIFICA" if len(matches)>1
                else "QUADRA" if abs(delta)<=MONEY_TOL else "DIFFERENZA")
        result.append({"group":group,"expected":expected,"observed":observed,"delta":delta,
                       "status":status,"references":"; ".join(sorted(r.identifier for r in matches)),
                       "reference":BILL_REF})
    return result
