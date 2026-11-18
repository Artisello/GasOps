"""Bounded, attributed public context for a briefing, not a balance calculation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import math

from .data import ROME
from .operational_sources import load_agsi, load_alsi, load_iip, attribution
from .weather_gas import analyse_gas_day
from .models import Kind
from .iip_view import coverage


def inventory_context(result, now, platform):
    cols=("stock_twh","fill_pct","withdrawal_gwh_d","injection_gwh_d") if platform=="AGSI+" else (
          "inventory_1000m3_lng","inventory_gwh","sendout_gwh_d","sendout_reference_pct")
    frame=result["frame"]
    fields=[col for col in cols if col in frame]
    valid=frame.loc[frame[fields].notna().any(axis=1)]
    if valid.empty:
        raise ValueError("Invalid inventory snapshot")
    row=valid.iloc[-1]
    day=row["gas_day"]
    age=(now.astimezone(ROME).date()-day).days
    out={**attribution(platform),"scope":result["scope"],"gas_day":day.isoformat(),
         "acquired":result["acquired"].isoformat(),"source_status":row["status"],
         "status":"stale" if result["failed"] or age>2 or age<0 or result["acquired"]>now else "available"}
    if out["status"]=="available":
        out["values"]={key:round(float(row[key]),3) for key in fields
                       if row[key] is not None and math.isfinite(float(row[key]))}
        if platform=="AGSI+":
            out["quality_review"]=bool(row.get("review",False))
    return out


def iip_context(result,now):
    stale=result["failed"] or not timedelta(0)<=now-result["acquired"]<=timedelta(hours=2)
    return {**attribution("IIP"),"request_from":result.get("request_from"),
            "request_to":result.get("request_to"),"acquired":result["acquired"].isoformat(),
            "status":"stale" if stale else "available",
            "received_records":None if stale else len(result["messages"]),
            "declared_total":None if stale else result.get("reported_total"),
            "coverage":coverage(result),
            "limitation":"Record UMM, non eventi distinti né capacità persa."}


def weather_context(result,now):
    acquired=datetime.fromisoformat(result["forecast_acquired"])
    if now-acquired>timedelta(hours=12) or result["refresh_failed"]:
        return {"source":"Open-Meteo","source_url":"https://open-meteo.com/","status":"stale"}
    return {"source":"Open-Meteo (CC BY 4.0)","source_url":"https://open-meteo.com/",
            "status":"available","acquired":acquired.isoformat(),"evaluation":result["evaluation"],
            "mae":result["mae"],"holdout":result["holdout"],"points":[
                {key:round(float(p[key]),2) if key!="period" else p[key]
                 for key in ("period","temperature_c","hdd","estimate_gwh","calendar_gwh")}
                for p in result["points"][:7]],
            "limitation":"Scenario condizionale settoriale, non previsione principale; tre città a pesi uguali."}


def collect(store, context, now, *, key="", include_gie=False, include_weather=False, weather_snapshots=None):
    """Only called on explicit report launch, never during widget reruns."""
    tasks={}
    out={}
    if include_gie and key:
        tasks["AGSI+"]=lambda: inventory_context(load_agsi(store,key,"IT",now=now),now,"AGSI+")
        tasks["ALSI"]=lambda: inventory_context(load_alsi(store,key,"IT",now=now),now,"ALSI")
        tasks["IIP"]=lambda: iip_context(load_iip(store,key,now=now),now)
    elif include_gie:
        out.update({name:{**attribution(name),"status":"unavailable","reason":"Chiave GIE non configurata."}
                    for name in ("AGSI+","ALSI","IIP")})
    if include_weather:
        origin=context.bundle.origin
        if origin.kind in (Kind.HISTORICAL,Kind.LIVE) and not origin.archive:
            def weather_task():
                from .weather_source import refresh,outlook,STATE
                state={STATE:weather_snapshots} if weather_snapshots is not None else {}
                if weather_snapshots is None:refresh(state,store,now)
                estimate=outlook(state,now)
                result={**estimate,"source_url":estimate["url"],"status":"available"} if estimate else None
                if origin.grain=="daily" and origin.name.startswith("ENTSOG"):
                    try:
                        scenario=weather_context(analyse_gas_day(store,context.inspection.usable,now,
                            snapshots=state.get(STATE,{})),now)
                        if scenario["status"]=="available":return scenario
                    except Exception:
                        pass
                if result:
                    result["limitation"]+=" · nessun forecast consumo derivato disponibile."
                    return result
                raise ValueError("Meteo non disponibile")
            tasks["Open-Meteo"]=weather_task
    if tasks:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures={name:pool.submit(task) for name,task in tasks.items()}
            for name,future in futures.items():
                try:
                    out[name]=future.result()
                except Exception:
                    out[name]={**(attribution(name) if name in ("AGSI+","ALSI","IIP") else {"source":name,"source_url":"https://open-meteo.com/"}),
                               "status":"unavailable","reason":"Fonte non disponibile o dati non validi; nessun valore sostitutivo."}
    return out
