"""HS1 study controls, CdStocc HS1 Rev. 2026-I, chapter 7 §§3.1–3.4.

All energies in GWh, coefficients dimensionless. Positive flow is injection
into storage (opposite to the transport ledger storage sign). No GIE proxy,
official eligibility decision, price, or confidential data transmission.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from io import StringIO
import csv
import re

REFERENCE = "CdStocc HS1 · Rev. 2026-I · cap. 7 §§3.1–3.4"
ZERO = D(0)
HUNDRED = D(100)
FIELDS = ("gas_day","opening_gwh","flow_gwh","consumption_gwh",
          "observed_closing_gwh","confirmed_renominations_gwh","snt_gwh")
NUMBER = re.compile(r"[+-]?\d{1,12}(?:\.\d{1,9})?")


def number(value, *, nonnegative=False):
    if not isinstance(value,D) or not value.is_finite() or abs(value)>D("1e12"):
        raise ValueError("Valore decimale mancante, non finito o fuori limite.")
    if nonnegative and value<0:
        raise ValueError("Valore negativo non ammesso.")
    return value


def system_balance(opening,flow,consumption,*,observed_closing=None,
                   confirmed_renominations=None,snt=None,tolerance=D(".01")):
    opening=number(opening,nonnegative=True)
    flow=number(flow)
    consumption=number(consumption,nonnegative=True)
    tolerance=number(tolerance,nonnegative=True)
    delta=flow-consumption
    closing=opening+delta
    if observed_closing is not None:
        observed_closing=number(observed_closing,nonnegative=True)
    residual=None if observed_closing is None else closing-observed_closing
    stop=None if confirmed_renominations is None else flow-number(confirmed_renominations)
    if snt is not None:
        snt=number(snt)
    st=None if stop is None or snt is None else stop+snt
    findings=[]
    if closing<0:findings.append("Giacenza ricostruita negativa.")
    if residual is not None and abs(residual)>tolerance:
        findings.append("Differenza rispetto alla giacenza finale indipendente.")
    return {"delta":delta,"closing":closing,"observed_closing":observed_closing,
            "residual":residual,"stop":stop,"st":st,"findings":findings,
            "status":"Da verificare" if findings else "Solo calcolo" if residual is None else "Entro tolleranza"}


def user_balance(opening,allocation,exchange,direction,gamma_pct,*,space,guarantee,
                 injection_limit,withdrawal_limit,tolerance=D(".01")):
    opening=number(opening,nonnegative=True)
    allocation=number(allocation); exchange=number(exchange)
    space=number(space,nonnegative=True); guarantee=number(guarantee,nonnegative=True)
    injection_limit=number(injection_limit,nonnegative=True)
    withdrawal_limit=number(withdrawal_limit,nonnegative=True)
    gamma=number(gamma_pct,nonnegative=True)/HUNDRED
    tolerance=number(tolerance,nonnegative=True)
    if gamma>1 or direction not in ("injection","withdrawal"):
        raise ValueError("Verso prevalente o percentuale consumi non valida.")
    coefficient=1-gamma if direction=="injection" else 1+gamma
    adjusted=allocation*coefficient
    closing=opening+adjusted+exchange
    flags=[]
    if opening>space or closing>space:flags.append("Giacenza oltre lo spazio dichiarato.")
    if opening<guarantee or closing<guarantee:flags.append("Giacenza inferiore al gas vincolato dichiarato.")
    if closing<0:flags.append("Giacenza finale negativa.")
    if allocation>injection_limit+tolerance:flags.append("Allocazione oltre la prestazione di iniezione dichiarata.")
    if -allocation>withdrawal_limit+tolerance:flags.append("Allocazione oltre la prestazione di erogazione dichiarata.")
    return {"coefficient":coefficient,"adjusted":adjusted,
            "consumption_effect":adjusted-allocation,"closing":closing,
            "free_stock":max(ZERO,closing-guarantee),"space_remaining":max(ZERO,space-closing),
            "findings":flags,"status":"Da verificare" if flags else "Nessuno scostamento nei controlli selezionati"}


def mgs_limits(space_available,stock_residual,injection_programmable,withdrawal_programmable,
               guarantee,other_reserved):
    """§3.4 simplified single ordinary service, gross inputs BEFORE deductions.
    No aggregation across users/services, no balancing-service treatment.
    """
    sp,g,i,e,blocked,other=(number(x,nonnegative=True) for x in (
        space_available,stock_residual,injection_programmable,withdrawal_programmable,guarantee,other_reserved))
    buy=sp-i; sell=g-e-blocked-other
    return {"buy":max(ZERO,buy),"sell":max(ZERO,sell),
            "findings":(["Spazio residuo insufficiente per l’iniezione dichiarata."] if buy<0 else [])+
                       (["Giacenza residua insufficiente per erogazione e vincoli dichiarati."] if sell<0 else [])}


def closed_hs1_day(now):
    """The HS1 glossary specifies 06:00 standard time (UTC+01) all year."""
    if not isinstance(now,datetime) or now.utcoffset() is None:
        raise ValueError("Timestamp senza fuso.")
    return (now.astimezone(timezone(timedelta(hours=1)))-timedelta(hours=6)).date()-timedelta(days=1)


def template():
    return ",".join(FIELDS)+"\n"


def parse_system_csv(raw,now,tolerance=D(".01")):
    if not raw or len(raw)>1_000_000:
        raise ValueError("CSV vuoto o superiore a 1 MB.")
    latest=closed_hs1_day(now)
    reader=csv.DictReader(StringIO(raw.decode("utf-8-sig")),strict=True)
    if tuple(reader.fieldnames or ())!=FIELDS:
        raise ValueError("Usa le intestazioni del modello HS1.")
    out=[]; seen=set()
    def parse(value,optional=False):
        value=value.strip()
        if optional and not value:return None
        if not NUMBER.fullmatch(value):raise ValueError("Valore assente o non valido: GWh, punto decimale.")
        return D(value)
    for row in reader:
        if len(out)>=2000 or None in row or any(v is None for v in row.values()):
            raise ValueError("Limite 2.000 giorni o colonne non valide.")
        day=date.fromisoformat(row["gas_day"])
        if day.isoformat()!=row["gas_day"] or day.year<2000 or day>latest or day in seen:
            raise ValueError("Giorno gas non concluso, non valido o duplicato.")
        seen.add(day)
        vals={k:parse(row[k],k in FIELDS[4:]) for k in FIELDS[1:]}
        out.append({"gas_day":day.isoformat(),**vals,**system_balance(
            vals["opening_gwh"],vals["flow_gwh"],vals["consumption_gwh"],
            observed_closing=vals["observed_closing_gwh"],
            confirmed_renominations=vals["confirmed_renominations_gwh"],
            snt=vals["snt_gwh"],tolerance=tolerance)})
    if not out:raise ValueError("Nessuna riga.")
    return sorted(out,key=lambda row:row["gas_day"])
