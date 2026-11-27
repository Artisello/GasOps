"""Read-only gas-day projections. Settlement/reconciliation engines stay authoritative."""
from datetime import date,datetime,timedelta
from decimal import Decimal as D
import json
import re

import pandas as pd

from .gas_calendar import gas_day_bounds,closed_gas_day
from .italian_network import verified_bindings, point_direction_labels
from .jarvis_archive import latest_records,merge_extracts,revision_rows
from .settlement_desk import daily_controls
from .reconciliation import reconcile_days
from .source_health import stamp,finite

INDICATORS=("Nomination","Renomination","Allocation","Physical Flow")
BALANCE_STATE="settlement_desk_csv_v1"
REPORT_STATE="settlement_reported_v1"
ESTIMATED="Estimated System Position — I.G.O.R."
CONFIRMED={"confirmed","final","definitive"}


def _cell(rows,indicator,start,stop):
    selected=rows.loc[rows.indicator==indicator]
    if selected.empty:return None,"Dato assente"
    newest=max(selected.retrieved_at)
    selected=selected.loc[selected.retrieved_at==newest]
    if not all(bool(r.usable) and r.value is not None and finite(r.value) and r.source_id
               and r.unit=="GWh/d" and r.time_basis=="gas_day" and r.period_from==start and r.period_to==stop
               for r in selected.itertuples()):
        return None,"Dato mancante, non validato o intervallo incompatibile"
    if selected.value.nunique()!=1:return None,"Valori in conflitto"
    return selected.iloc[0],""


def _difference(a,b):
    if a is None or b is None:return None
    return a.value-b.value


def public_reconciliation(network,frame,day):
    """Rates on the exact same UTC gas-day interval; no point totals or cash flows."""
    start,stop=gas_day_bounds(day)
    bindings={b.point_direction:b for b in verified_bindings(network)}
    lookup={i.id:i for i in network.infrastructure}
    direction_types=point_direction_labels(network)
    source=frame.loc[(frame.provider=="ENTSOG")&(frame.gas_day==day)&frame.indicator.isin(INDICATORS)]
    result=[]
    for point,binding in bindings.items():
        rows=source.loc[(source.point_direction==point)&(source.direction==binding.direction)
                        &(source.infrastructure_id==binding.infrastructure_id)]
        cells,notes={},[]
        for indicator in INDICATORS:
            cell,note=_cell(rows,indicator,start,stop)
            cells[indicator]=cell
            if note:notes.append(indicator+": "+note)
        evidence={k:{name:row[name] for name in ("source_id","observed_at","retrieved_at","quality_status",
            "publication_status","revision_count","revisions","period_from","period_to","source_url","source_unit")}
            for k,row in cells.items() if row is not None}
        complete=all(c is not None for c in cells.values())
        differences={"delta_renomination_nomination":_difference(cells["Renomination"],cells["Nomination"]),
            "delta_allocation_renomination":_difference(cells["Allocation"],cells["Renomination"]),
            "delta_physical_allocation":_difference(cells["Physical Flow"],cells["Allocation"])}
        comparable=complete and all(v is not None for v in differences.values())
        preliminary=any(str(c.publication_status).casefold() not in CONFIRMED for c in cells.values() if c is not None)
        if preliminary:notes.append("Pubblicazioni provvisorie o non confermate: confronto descrittivo, non riconciliazione definitiva")
        result.append({"point_direction":point,"infrastructure_id":binding.infrastructure_id,
            "point":lookup[binding.infrastructure_id].name,"point_type":direction_types[point],
            "direction":binding.direction,"gas_day":day,
            "unit":"GWh/d","period_from":start,"period_to":stop,
            **{name:cells[name].value if cells[name] is not None else None for name in INDICATORS},**differences,
            "available":sum(c is not None for c in cells.values()),"comparable":comparable,
            "state":"Confrontabile · provvisorio" if comparable and preliminary else "Confrontabile" if comparable else "Parziale" if evidence else "Non disponibile",
            "source":"ENTSOG TP","evidence":json.dumps(evidence,ensure_ascii=False,default=str,sort_keys=True),
            "note":" · ".join(notes)})
    return result


def system_position(state,day,now):
    """Only an explicitly matched aggregate release can support a residual estimate.

    Existing Jarvis imports validate formats, not official source authenticity.
    They cannot establish an official Snam system position or an individual DS.
    """
    result={"label":ESTIMATED,"value":None,"unit":"GWh","status":"Non calcolabile",
        "official":False,"scope":"SRG · aggregato dichiarato","evidence":[],
        "note":"Componenti pubbliche insufficienti o perimetri non riconciliabili. Nessun saldo ufficiale validato."}
    imported=state.get("jarvis_aggregate_archive_v1",{}).get("records",())
    rows=[r for r in imported if r.family=="balance" and r.gas_day==day and r.scope=="SRG"
          and r.published_at<=now and r.metric in ("injections","withdrawals")]
    if not rows:return result
    # Validate the imported definition again, without treating a declared source as official.
    try:latest=latest_records(merge_extracts((),rows))
    except ValueError:return result
    per_metric={k:[r for r in latest if r.metric==k] for k in ("injections","withdrawals")}
    if any(len(v)!=1 for v in per_metric.values()):return result
    a,b=per_metric["injections"][0],per_metric["withdrawals"][0]
    if ((a.stage,a.published_at,a.report_ref)!=(b.stage,b.published_at,b.report_ref)
        or a.unit not in ("GWh","MWh") or b.unit not in ("GWh","MWh")
        or not a.report_ref or any(not finite(r.value) or r.value<0 for r in (a,b))):return result
    value=a.value/(1000 if a.unit=="MWh" else 1)-b.value/(1000 if b.unit=="MWh" else 1)
    result.update(value=value,status="Stimato · fonte dichiarata",evidence=[{
        "source_id":r.report_ref,"gas_day":day,"metric":r.metric,"value":r.value,"unit":r.unit,
        "observed_at":r.published_at,"retrieved_at":None,"quality_status":"user_declared",
        "version":r.stage} for r in (a,b)],note="Immissioni − prelievi dello stesso report SRG. Residuo stimato sul perimetro dichiarato; non SAS ufficiale o DS individuale.")
    return result


def authorized_portfolio(state):
    saved=state.get(BALANCE_STATE)
    return saved if (saved and saved.get("authorized") is True and saved.get("origin")=="user_upload"
        and re.fullmatch(r"[a-f0-9]{64}",str(saved.get("sha",""))) and saved.get("rows")) else None


def version_key(row):
    return f"{row.user}|{row.day}|{row.version}"


def portfolio_day(state,user,day,now):
    """Delegate every balance, price and reconciliation result to existing engines."""
    saved=authorized_portfolio(state)
    out={"value":None,"cash":None,"unit":"MWh","status":"Non disponibile","versions":[],"control":None,
         "reconciliation":None,"evidence":[],"source_id":None}
    if saved is None or user not in {r.user for r in saved["rows"]}:return out
    closed=closed_gas_day(now)
    control=next(r for r in daily_controls(saved["rows"],user,day.year,day.month,closed_day=closed) if r["day"]==day.isoformat())
    versions=sorted((r for r in saved["rows"] if r.user==user and r.day==day),key=lambda r:r.version)
    out.update(control=control,versions=versions,source_id=saved["sha"],
        value=control["ds_mwh"] if control["closed"] else None,
        cash=control["cash_eur"] if control["eligible"] else None,
        status="Calcolo disponibile" if control["eligible"] else "Da verificare" if versions else "Non disponibile")
    reported=state.get(REPORT_STATE)
    if reported and reported.get("authorized") is True and reported.get("origin")=="user_upload":
        out["reconciliation"]=next((r for r in reconcile_days(saved["rows"],reported["rows"],user,day.year,day.month,closed)
            if r["day"]==day.isoformat()),None)
    trace=saved.get("version_provenance",{})
    previous=None
    unique=len({r.version for r in versions})==len(versions)
    for r in versions:
        provenance=trace.get(version_key(r),{})
        at=provenance.get("retrieved_at")
        known=stamp(at) if at else None
        if known and known>now:known=None
        out["evidence"].append({"gas_day":day,"point_direction":None,"source_id":provenance.get("source_id") or saved["sha"],
            "version":r.version,"publication_timestamp":None,"retrieved_at":known,"unit":"MWh",
            "old_value":previous.imbalance if unique and previous else None,"new_value":r.imbalance,
            "reason":"Versione del bilancio importato" if previous and unique else "Prima versione disponibile" if unique else "Versioni duplicate",
            "quality_flag":r.stage if unique else "conflict"})
        previous=r
    return out


def workflow(rows,portfolio=None):
    if portfolio is not None:
        reconciliation=portfolio.get("reconciliation")
        return [(name,"Non disponibile") for name in ("Nomination","Renomination","Allocation")]+[
            ("Reconciliation",reconciliation["status"] if reconciliation else "Non disponibile"),
            ("Settlement",portfolio["status"] if portfolio.get("cash") is not None else "Non disponibile")]
    n=len(rows)
    steps=[]
    for name in INDICATORS[:3]:
        count=sum(r[name] is not None for r in rows)
        steps.append((name,f"{count}/{n} disponibili" if count else "Non disponibile"))
    count=sum(r["comparable"] for r in rows)
    return [*steps,("Reconciliation",f"{count}/{n} confrontabili" if count else "Non disponibile"),
            ("Settlement","Non disponibile")]


def jarvis_audit(state,day,now):
    records=state.get("jarvis_aggregate_archive_v1",{}).get("records",())
    try:records=merge_extracts((),[r for r in records if r.gas_day==day and r.published_at<=now])
    except ValueError:return []
    summary={(r["gas_day"],r["scope"],r["metric"],r["unit"]):r for r in revision_rows(records)}
    out=[]
    for r in records:
        revision=summary.get((day.isoformat(),r.scope,r.metric,r.unit),{})
        paired=revision.get("delta") is not None and revision.get("definitive_at")==r.published_at.isoformat()
        out.append({"source_id":r.report_ref,"gas_day":day,"point_direction":None,"indicator":r.metric,
            "retrieved_at":None,"publication_timestamp":r.published_at,"old_value":revision["provisional"] if paired else None,
            "new_value":r.value,"unit":r.unit,"version":r.stage,"quality_flag":"user_declared",
            "reason":"Provvisorio → definitivo" if paired else "Pubblicazione importata"})
    return out


def inventory_state(context,state,day,*,history=False):
    """Project the newest national inventory and bounded SRG cache into P0 state."""
    combined=dict(state)
    for provider in ("AGSI+","ALSI"):
        candidates=[]
        for p,identifier,scope,result,failed in context["inventory"]:
            frame=result.get("frame")
            if p!=provider or identifier or scope!="IT" or frame is None:continue
            first=result.get("first") or (min(frame.gas_day) if not frame.empty else None)
            last=result.get("last") or (max(frame.gas_day) if not frame.empty else None)
            if first is None or last is None:continue
            if history or day is None or first<=day<=last:candidates.append((result["acquired"],result,failed))
        if candidates:
            at=max(c[0] for c in candidates)
            tied=[c for c in candidates if c[0]==at]
            _,result,failed=tied[-1]
            frames=[r["frame"] for _,r,_ in tied]
            if history:
                editions, acquired_by_day = [], {}
                for acquired,query,_ in sorted(candidates,key=lambda c:c[0]):
                    frame = query["frame"]
                    days = set(frame.gas_day)
                    editions = [(when,rows.loc[~rows.gas_day.isin(days)] if when<acquired else rows)
                                for when,rows in editions]
                    editions.append((acquired,frame))
                    acquired_by_day.update(dict.fromkeys(days,acquired))
                frames = [frame for _,frame in editions]
                result = {**result,"acquired_by_day":acquired_by_day}
            result={**result,"frame":pd.concat(frames,ignore_index=True).drop_duplicates(),
                    "failed":any(r.get("failed") or error for _,r,error in tied)}
            combined[provider+"_IT"]={"result":result,"error":failed}
    ranges = sorted(context.get("srg",()), key=lambda r:r[2].retrieved_at)
    if ranges and (day is None or any(first<=day<=last for first,last,_ in ranges)):
        from .entsog import combine
        from .live_sources import BUNDLES
        from .public_data import SourceUnavailable
        selected = [r for r in ranges if day is None or r[0]<=day<=r[1]]
        first = context["first"] if day is None else day
        last = context["last"] if day is None else day
        try:
            bundle = combine([r[2] for r in selected],first,last)
        except SourceUnavailable:
            pass
        else:
            prior=state.get(BUNDLES,{}).get("daily")
            if prior is None or prior.origin.retrieved_at<=bundle.origin.retrieved_at:
                combined[BUNDLES]={**state.get(BUNDLES,{}),"daily":bundle}
                combined["srg_window_acquisitions"]={
                    d:query.retrieved_at for a,b,query in selected
                    for d in query.flags if first<=d<=last and a<=d<=b}
    return combined
