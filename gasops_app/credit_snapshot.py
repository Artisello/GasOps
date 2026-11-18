"""Reconstruct EPSu/MEPSu from a declared, common-date normalized study snapshot.
No official source authentication or guarantee eligibility decisions.
"""
from calendar import monthrange
from datetime import date,timedelta
from decimal import Decimal as D, ROUND_HALF_UP, InvalidOperation
from hashlib import sha256
import json,re
from .credit_risk import credit_position,patt_horizon,CDR

ZERO=D(0)
LIMIT=2*1024*1024
SAFE=re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")
NUM=re.compile(r"[+-]?\d{1,15}(?:\.\d{1,10})?")
SECTIONS=("obligations","guarantees","withdrawals","psv","prior_prices","regularity")
SCHEMA="igor-credit-v1"


def exact(obj,keys):
    if not isinstance(obj,dict) or set(obj)!=set(keys):
        raise ValueError("Campi mancanti o inattesi: "+", ".join(keys))


def sequence(x):
    if not isinstance(x,list) or len(x)>10000:
        raise ValueError("Registro non valido o oltre 10.000 righe.")
    return x


def number(x,nonnegative=False):
    if not isinstance(x,str) or not NUM.fullmatch(x):
        raise ValueError("Usa numeri decimali come stringhe, con punto.")
    n=D(x)
    if nonnegative and n<0:raise ValueError("Valore negativo non ammesso.")
    return n


def pct(x):
    n=number(x,True)
    if n>100:raise ValueError("Percentuale oltre 100.")
    return n


def day(x):
    if not isinstance(x,str):raise ValueError("Data non valida.")
    d=date.fromisoformat(x)
    if d.isoformat()!=x or not 2000<=d.year<=2100:raise ValueError("Data non valida.")
    return d


def identifier(x):
    if not isinstance(x,str) or not SAFE.fullmatch(x):raise ValueError("Identificativo fittizio non valido.")
    return x


def unique(items,ref):
    if ref in items:raise ValueError("Riferimento duplicato: "+ref)
    items.add(ref)


def regularity(r):
    exact(r,("verifiable","balancing_total_eur","balancing_irregular_eur",
             "transport_total_eur","transport_irregular_eur"))
    if type(r["verifiable"]) is not bool:raise ValueError("Verificabilità non valida.")
    if not r["verifiable"]:
        if any(v is not None for k,v in r.items() if k!="verifiable"):
            raise ValueError("Regolarità non verificabile: lascia null gli importi.")
        return 7,None,None
    rates=[]
    for kind in ("balancing","transport"):
        total=number(r[kind+"_total_eur"],True)
        irregular=number(r[kind+"_irregular_eur"],True)
        if total<=0 or irregular>total:
            raise ValueError("Denominatore regolarità assente o irregolarità incoerente. Verifica il semestre.")
        rates.append(100*irregular/total)
    return patt_horizon(*rates,verifiable=True),*rates


def prior_price(rows,as_of):
    last=as_of.replace(day=1)-timedelta(days=1)
    expected={last.replace(day=i) for i in range(1,monthrange(last.year,last.month)[1]+1)}
    values={}
    for r in sequence(rows):
        exact(r,("day","buy_eur_mwh"))
        d=day(r["day"])
        if d in values or d not in expected:raise ValueError("Prezzi: giorno duplicato o fuori mese precedente.")
        values[d]=number(r["buy_eur_mwh"])
    if set(values)!=expected:raise ValueError("Pr: servono tutti i prezzi di acquisto del mese precedente.")
    mean=sum(values.values(),ZERO)/D(len(values))
    pr_kwh=(mean/1000).quantize(D(".000001"),rounding=ROUND_HALF_UP)
    return pr_kwh,pr_kwh*1000,len(values)


def reconstruct(data,today):
    exact(data,("schema","user","as_of","coverage","vat_pct",*SECTIONS))
    if data["schema"]!=SCHEMA:raise ValueError("Schema non riconosciuto.")
    user=identifier(data["user"]); as_of=day(data["as_of"])
    if as_of>today:raise ValueError("Snapshot futuro.")
    coverage=data["coverage"]
    exact(coverage,SECTIONS)
    if any(v is not True for v in coverage.values()):
        raise ValueError("Copertura non dichiarata completa: nessuna posizione aggregata calcolabile.")
    horizon,bal_rate,tr_rate=regularity(data["regularity"])
    vat=pct(data["vat_pct"])
    pr_kwh,pr_mwh,price_days=prior_price(data["prior_prices"],as_of)
    pfat=pdet=c=ZERO
    ids=set()
    details=[]
    for r in sequence(data["obligations"]):
        exact(r,("reference","kind","day","amount_eur","ds_mwh","price_eur_mwh","vat_pct"))
        ref=identifier(r["reference"]);unique(ids,ref);d=day(r["day"]);kind=r["kind"]
        if d>as_of or (kind in ("pdet_ds","pdet_other") and d>=as_of):
            raise ValueError("Partita fuori data di competenza.")
        if kind=="pdet_ds":
            if r["amount_eur"] is not None:raise ValueError("Pdet DS: non inserire anche un importo.")
            ds=number(r["ds_mwh"]);price=number(r["price_eur_mwh"]);rate=pct(r["vat_pct"])
            # DS sign is from user perspective; exposure from system perspective.
            value=-ds*price*(1+rate/100)
            pdet+=value
        elif kind in ("pfat","overdue","pdet_other"):
            if any(r[k] is not None for k in ("ds_mwh","price_eur_mwh","vat_pct")):
                raise ValueError("Importo lordo già determinato: non duplicare quantità o IVA.")
            value=number(r["amount_eur"],kind=="overdue")
            if kind=="pfat":pfat+=value
            elif kind=="overdue":c+=value
            else:pdet+=value
        else:raise ValueError("Classificazione contabile non riconosciuta.")
        details.append({"reference":ref,"kind":kind,"day":d.isoformat(),"eur":str(value)})
    guaranteed=[]
    for r in sequence(data["guarantees"]):
        exact(r,("reference","recognized_eur"))
        ref=identifier(r["reference"]);unique(ids,ref)
        guaranteed.append(number(r["recognized_eur"],True))
    expected={as_of+timedelta(days=i) for i in range(1,horizon+1)}
    withdrawals={}
    for r in sequence(data["withdrawals"]):
        exact(r,("day","direct_points","distribution_mwh","foreign_exit_mwh","storage_exit_mwh"))
        d=day(r["day"])
        if d in withdrawals or d not in expected:raise ValueError("Giorno Patt duplicato o fuori orizzonte.")
        points=set();direct=ZERO
        for point in sequence(r["direct_points"]):
            exact(point,("point","capacity_mwh","utilization_pct"))
            ref=identifier(point["point"]);unique(points,ref)
            direct+=number(point["capacity_mwh"],True)*pct(point["utilization_pct"])/100
        distribution,foreign,storage=(number(r[k],True) for k in
                   ("distribution_mwh","foreign_exit_mwh","storage_exit_mwh"))
        withdrawals[d]={"direct":direct,"distribution":distribution,"foreign":foreign,"storage":storage,
                        "total":direct+distribution+foreign+storage}
    if set(withdrawals)!=expected:raise ValueError("Patt: copertura giornaliera incompleta.")
    psv={}
    for r in sequence(data["psv"]):
        exact(r,("reference","delivery_day","registered_day","net_sale_mwh"))
        ref=identifier(r["reference"]);unique(ids,ref)
        d=day(r["delivery_day"]); registered=day(r["registered_day"])
        if registered>as_of or d<as_of:raise ValueError("PSV fuori snapshot: le partite precedenti spettano a Pdet/Pfat.")
        psv[d]=psv.get(d,ZERO)+number(r["net_sale_mwh"])
    patt_rows=[]
    for d in sorted(expected|set(psv)):
        w=withdrawals.get(d)
        q=w["total"] if w is not None else ZERO
        sale=psv.get(d,ZERO)
        amount=(q+sale)*pr_mwh*(1+vat/100)
        patt_rows.append({"day":d.isoformat(),"within_horizon":d in expected,
              "direct_mwh":str(w["direct"]) if w else None,"distribution_mwh":str(w["distribution"]) if w else None,
              "foreign_mwh":str(w["foreign"]) if w else None,"storage_mwh":str(w["storage"]) if w else None,
              "withdrawal_mwh":str(q) if w else None,"psv_net_sale_mwh":str(sale),
              "signed_deficit_mwh":str(q+sale),"patt_eur":str(amount)})
    patt=sum((D(r["patt_eur"]) for r in patt_rows),ZERO)
    result=credit_position(pfat,pdet,patt,guaranteed,c)
    return {"user":user,"as_of":as_of.isoformat(),"horizon":horizon,"balancing_late_pct":bal_rate,
            "transport_late_pct":tr_rate,"pr_eur_kwh":pr_kwh,"pr_eur_mwh":pr_mwh,
            "price_days":price_days,"position":result,"patt_rows":patt_rows,"obligations":details,
            "guarantee_count":len(guaranteed),"reference":CDR}


def _pairs(items):
    out={}
    for key,value in items:
        if key in out:raise ValueError("Campo JSON duplicato.")
        out[key]=value
    return out


def load(raw,today):
    if not raw or len(raw)>LIMIT:raise ValueError("JSON vuoto o oltre 2 MiB.")
    try:
        data=json.loads(raw.decode("utf-8-sig"),object_pairs_hook=_pairs)
        result=reconstruct(data,today)
    except (UnicodeError,InvalidOperation,OverflowError,TypeError,RecursionError) as e:
        raise ValueError("Snapshot non valido.") from e
    return {**result,"sha256":sha256(raw).hexdigest()}


def example():
    as_of=date(2026,11,18)
    return {"schema":SCHEMA,"user":"DEMO-001","as_of":str(as_of),
       "coverage":dict.fromkeys(SECTIONS,True),"vat_pct":"22",
       "regularity":{"verifiable":True,"balancing_total_eur":"100000","balancing_irregular_eur":"10000",
                     "transport_total_eur":"200000","transport_irregular_eur":"0"},
       "prior_prices":[{"day":str(date(2026,10,i)),"buy_eur_mwh":"40"} for i in range(1,32)],
       "obligations":[
          {"reference":"F1","kind":"pfat","day":"2026-11-15","amount_eur":"420000","ds_mwh":None,"price_eur_mwh":None,"vat_pct":None},
          {"reference":"F2","kind":"overdue","day":"2026-11-10","amount_eur":"100000","ds_mwh":None,"price_eur_mwh":None,"vat_pct":None},
          {"reference":"D1","kind":"pdet_ds","day":"2026-11-17","amount_eur":None,"ds_mwh":"-5000","price_eur_mwh":"40","vat_pct":"22"}],
       "guarantees":[{"reference":"G1","recognized_eur":"1100000"}],
       "withdrawals":[{"day":str(as_of+timedelta(days=i)),"direct_points":[{"point":"P1","capacity_mwh":"1000","utilization_pct":"50"}],
                        "distribution_mwh":"500","foreign_exit_mwh":"100","storage_exit_mwh":"0"} for i in range(1,4)],
       "psv":[{"reference":"T1","delivery_day":"2026-11-25","registered_day":"2026-11-18","net_sale_mwh":"1200"}]}


def export(result):
    return json.dumps(result,default=str,ensure_ascii=False,indent=2)
