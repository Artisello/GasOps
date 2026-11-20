"""Independent, session-only reconciliation of declared definitive settlement extracts."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
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
    for row in daily_controls(balances,user,year,month,closed_day=closed_day):
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
    daily=daily_controls(balances,user,year,month,closed_day=closed_day)
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


# Cross-infrastructure control of declared G+1 allocations, not physical flows.
INTERFACE_FIELDS=("user","gas_day","interface","gas_day_convention","match_batch","reference","energy_mwh")
INTERFACE_REFERENCES={
    "HS1":"CdR XCII cap. 9 §§3.1.2, 4.3.1; CdStocc HS1 2026-I cap. 7 §§3.2–3.3",
    "PIOMBINO":"CdR XCII cap. 9 §§3.1.2, 4.3.1; CdRig Piombino 2023-I cap. 9 §§3.1–3.3",
}
CONVENTIONS={"CET_FIXED":timezone(timedelta(hours=1)),"EUROPE_ROME":ZoneInfo("Europe/Rome")}


@dataclass(frozen=True)
class InterfaceAllocation:
    user:str
    day:date
    interface:str
    convention:str
    batch:str
    reference:str
    energy:D


def interface_interval(day,convention):
    """Declared source interval; compare instants, not merely date labels."""
    tz=CONVENTIONS[convention]
    start=datetime.combine(day,time(6),tzinfo=tz).astimezone(timezone.utc)
    end=datetime.combine(day+timedelta(days=1),time(6),tzinfo=tz).astimezone(timezone.utc)
    return start,end


def parse_interface(raw,now):
    """One already-normalized, independently sourced allocation per key.
    References need not match across systems; match_batch must be assigned
    after checking comparable source versions. No automatic version selection.
    """
    if now.utcoffset() is None:raise ValueError("Timestamp senza fuso.")
    result={}
    for r in _rows(raw,INTERFACE_FIELDS):
        user,ref,batch=(_id(r[k]) for k in ("user","reference","match_batch"))
        day=_day(r["gas_day"])
        point,convention=r["interface"],r["gas_day_convention"]
        if point not in INTERFACE_REFERENCES or convention not in CONVENTIONS:
            raise ValueError("Interfaccia o convenzione giorno gas non supportata.")
        if interface_interval(day,convention)[1]>now:
            raise ValueError("Sono ammessi solo giorni gas conclusi.")
        energy=_amount(r["energy_mwh"])
        if point=="PIOMBINO" and energy<0:
            raise ValueError("Piombino: solo riconsegne ordinarie positive o nulle al punto di entrata.")
        key=user,day,point
        if key in result:
            raise ValueError("Duplicato per utente/giorno/interfaccia: normalizza una sola versione.")
        result[key]=InterfaceAllocation(user,day,point,convention,batch,ref,energy)
    return {"rows":tuple(result[k] for k in sorted(result)),"sha":sha256(raw).hexdigest()}


def reconcile_interfaces(transport,infrastructure,tolerance=ENERGY_TOL):
    """Compare independent declared allocations of an ordinary transport user.
    HS1 operator injection positive; SRG storage withdrawal positive.
    Piombino operator communicated allocation for the same transport user
    at physical entry, never PSV, programme alone, terminal total or send-out.
    """
    if not isinstance(tolerance,D) or not tolerance.is_finite() or tolerance<0:
        raise ValueError("Tolleranza diagnostica non valida.")
    def index(rows):
        out={}
        for r in rows:
            key=r.user,r.day,r.interface
            if key in out:raise ValueError("Duplicato nel dossier.")
            out[key]=r
        return out
    left,right=index(transport),index(infrastructure)
    result=[]
    for user,day,point in sorted(left.keys()|right.keys()):
        a,b=left.get((user,day,point)),right.get((user,day,point))
        expected=None if b is None else -b.energy if point=="HS1" else b.energy
        delta=None
        if a is None or b is None:
            status="ESTRATTO ASSENTE"
            reason="Manca SRG." if a is None else "Manca il gestore dell’infrastruttura."
        elif interface_interval(day,a.convention)!=interface_interval(day,b.convention):
            status="PERIODO DISCORDANTE";reason="Intervalli UTC differenti."
        elif a.batch!=b.batch:
            status="VERSIONI NON ALLINEATE";reason="Gruppo di confronto dichiarato differente."
        else:
            delta=a.energy-expected
            status="DIFFERENZA" if abs(delta)>tolerance else "QUADRA"
            reason="Scostamento oltre tolleranza diagnostica." if status=="DIFFERENZA" else ""
        result.append({"user":user,"gas_day":day.isoformat(),"interface":point,
                       "transport_mwh":a.energy if a is not None else None,
                       "operator_mwh":b.energy if b is not None else None,
                       "expected_transport_mwh":expected,"delta_mwh":delta,
                       "status":status,"reason":reason,
                       "transport_convention":a.convention if a else None,
                       "operator_convention":b.convention if b else None,
                       "transport_batch":a.batch if a else None,"operator_batch":b.batch if b else None,
                       "transport_reference":a.reference if a else None,"operator_reference":b.reference if b else None,
                       "rule_reference":INTERFACE_REFERENCES[point]})
    return result


def interface_score(results):
    compared=[r for r in results if r["delta_mwh"] is not None]
    return {"received_keys":len(results),"compared":len(compared),
            "matched":sum(r["status"]=="QUADRA" for r in results),
            "differences":sum(r["status"]=="DIFFERENZA" for r in results),
            "unknown":len(results)-len(compared),
            "absolute_difference_mwh":sum((abs(r["delta_mwh"]) for r in compared),ZERO) if compared else None}


def interface_demo(now):
    """Explicit synthetic paired extracts, not a source or full month."""
    day=(now.astimezone(CONVENTIONS["CET_FIXED"])-timedelta(days=3)).date()
    d=day.isoformat()
    left=template(INTERFACE_FIELDS)+f"""DEMO-001,{d},HS1,CET_FIXED,B1,SRG-S1,40000
DEMO-001,{d},PIOMBINO,CET_FIXED,B1,SRG-L1,25000
DEMO-002,{d},HS1,CET_FIXED,B2,SRG-S2,-8000
DEMO-002,{d},PIOMBINO,CET_FIXED,B2,SRG-L2,12000
"""
    right=template(INTERFACE_FIELDS)+f"""DEMO-001,{d},HS1,CET_FIXED,B1,HS1-S1,-40000
DEMO-001,{d},PIOMBINO,CET_FIXED,B1,LNG-L1,24800
DEMO-002,{d},HS1,CET_FIXED,B3,HS1-S2,8000
"""
    return {"transport":parse_interface(left.encode(),now),"operator":parse_interface(right.encode(),now),"synthetic":True}
