"""Presentation and what-if controls, not additional regulatory obligations."""
from datetime import date
from decimal import Decimal as D, ROUND_CEILING

from .commercial_controls import finite, exposure


def reconciliation_summary(rows):
    issues=[r for r in rows if r["status"] not in ("QUADRA","NON DOVUTA")]
    deltas=[abs(r["delta"]) for r in issues if r["delta"] is not None]
    return {"issues":len(issues),"known_difference":sum(deltas,D(0)),
            "unknown":sum(r["delta"] is None for r in issues)}


def guarantee_scenario(pfat,pdet,patt,meps,shock):
    """Signed hypothetical addition to Patt only; no estimate of collateral rules."""
    current=exposure(pfat,pdet,patt,meps)
    projected=exposure(pfat,pdet,patt+finite(shock),meps)
    # Mathematical denominator for ratio <=90%, not a regulatory collateral request.
    target=(max(D(0),projected["eps"])/D("0.9")).quantize(D(".01"),rounding=ROUND_CEILING)
    return {"current":current,"projected":projected,
            "to_90":D(".9")*meps-current["eps"],
            "additional_meps_90":max(D(0),target-meps)}


def deadline_status(due:date|None,as_of:date):
    if due is None:
        return {"days_left":None,"status":"Data non disponibile"}
    days=(due-as_of).days
    return {"days_left":days,"status":"Data trascorsa" if days<0 else
            "Oggi" if days==0 else "Entro 7 giorni" if days<=7 else "Successiva"}


def calendar_rows(deadlines,as_of):
    return [{**r,**deadline_status(r["due"],as_of),"as_of":as_of,"mode":"SIMULAZIONE"}
            for r in sorted(deadlines,key=lambda d:d["due"] or date.max)]
