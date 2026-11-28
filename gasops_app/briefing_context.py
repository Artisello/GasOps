"""Bounded, attributed public context for a briefing, not a balance calculation."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import datetime, timedelta
import math

from .data import ROME
from .operational_sources import load_agsi, load_alsi, load_iip, attribution
from .weather_gas import analyse_gas_day
from .models import Kind
from .iip_view import coverage
from .public_data import SourceUnavailable


def inventory_context(result, now, platform, *, day=None):
    requested = day
    if result.get("no_observation"):
        raise ValueError("Nessuna osservazione utilizzabile restituita dall’ultima richiesta GIE.")
    cols=("stock_twh","fill_pct","withdrawal_gwh_d","injection_gwh_d") if platform=="AGSI+" else (
          "inventory_1000m3_lng","inventory_gwh","sendout_gwh_d","sendout_reference_pct")
    frame=result["frame"]
    fields=[col for col in cols if col in frame]
    valid=frame.loc[frame[fields].notna().any(axis=1)]
    if requested is not None:
        valid=valid.loc[valid["gas_day"]==requested]
    if valid.empty:
        raise ValueError("Invalid inventory snapshot")
    row=valid.iloc[-1]
    day=row["gas_day"]
    # Published gas-day labels are not civil-day observations. The local
    # 06:00 boundary, not midnight, advances the briefing freshness window.
    reference_day=(now.astimezone(ROME)-timedelta(hours=6)).date()
    age=(reference_day-day).days
    out={**attribution(platform),"scope":result["scope"],"gas_day":day.isoformat(),
         "acquired":result.get("acquired_by_day",{}).get(day,result["acquired"]).isoformat(),
         "source_status":row["status"],"kind":"estimated" if row["status"]=="E" else "observed",
         "status":"stale" if result["failed"] or (requested is None and age>2) or age<0 or result["acquired"]>now else "available"}
    out["limitation"]=("Giacenza fisica, riempimento e flussi giornalieri di stoccaggio; non capacità libera o deficit."
                       if platform=="AGSI+" else "Inventario GNL e send-out giornaliero; non prezzo o capacità disponibile.")
    if out["status"]=="available":
        out["values"]={key:round(float(row[key]),3) for key in fields
                       if row[key] is not None and math.isfinite(float(row[key]))}
        if platform=="AGSI+":
            out["quality_review"]=bool(row.get("review",False))
    else:
        out["reason"]=("Aggiornamento non riuscito" if result["failed"] else
                       "Data non coerente con l’acquisizione" if age<0 or result["acquired"]>now else
                       "Ultimo giorno gas oltre la finestra di 2 giorni")
        if age>=0 and result["acquired"]<=now:
            out["last_observed_values"]={key:round(float(row[key]),3) for key in fields
                       if row[key] is not None and math.isfinite(float(row[key]))}
    return out


def iip_context(result,now):
    age=now-result["acquired"]
    reason=("Aggiornamento IIP non riuscito; ultimo dato valido conservato." if result["failed"] else
            "Data di acquisizione futura: verifica orologio e cache." if age<timedelta(0) else
            "Ultima acquisizione oltre 2 ore." if age>timedelta(hours=2) else None)
    if result["failed"] and result.get("refresh_error"):
        reason="Aggiornamento IIP non riuscito ("+result["refresh_error"]+"); ultimo dato valido conservato."
    stale=reason is not None
    return {**attribution("IIP"),"request_from":result.get("request_from"),
            "request_to":result.get("request_to"),"acquired":result["acquired"].isoformat(),
            "status":"stale" if stale else "available",
            **({"reason":reason} if reason else {}),
            "received_records":None if stale else len(result["messages"]),
            "declared_total":None if stale else result.get("reported_total"),
            "coverage":coverage(result),
            "limitation":"Conteggio dei record UMM attivi nella finestra richiesta, non eventi distinti, capacità persa o conteggio specifico dell’Italia. Finestre diverse non sono direttamente confrontabili."}


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


def collect(store, context, now, *, key="", include_gie=False, include_weather=False,
            weather_snapshots=None, clock=None, only=None, day=None, scope="IT"):
    """Only called on explicit report launch, never during widget reruns."""
    tasks={}
    out={}
    # Request windows use the start time; freshness uses the time after retrieval.
    # Explicit clock injection keeps historical/offline tests deterministic.
    checked_at=clock or (lambda:now)
    gie = ("AGSI+","ALSI","IIP") if scope=="IT" else ("AGSI+","ALSI") if scope=="EU" else ("AGSI+",)
    if include_gie:
        loaders = {"AGSI+":load_agsi,"ALSI":load_alsi}
        for name in gie:
            if only is not None and name not in only:
                continue
            if not key:
                out[name]={**attribution(name),"status":"unavailable","reason":"Chiave GIE non configurata."}
            elif name=="IIP":
                tasks[name]=lambda: iip_context(load_iip(store,key,now=now),checked_at())
            else:
                def inventory_task(name=name):
                    # An explicitly requested day may be outside the default
                    # recent window; request that exact closed gas day.
                    from .gas_calendar import closed_gas_day
                    if day is not None and day>closed_gas_day(now):
                        raise ValueError("Giorno gas non concluso")
                    bounds={"first":day,"last":day} if day is not None else {}
                    return inventory_context(loaders[name](store,key,scope,now=now,**bounds),
                                             checked_at(),name,day=day)
                tasks[name]=inventory_task
    if include_weather and (only is None or "Open-Meteo" in only):
        origin=context.bundle.origin if context is not None else None
        if origin is None or origin.kind in (Kind.HISTORICAL,Kind.LIVE) and not origin.archive:
            def weather_task():
                from .weather_source import refresh,outlook,STATE
                state={STATE:weather_snapshots} if weather_snapshots is not None else {}
                if weather_snapshots is None:refresh(state,store,now)
                estimate=outlook(state,checked_at())
                result={**estimate,"source_url":estimate["url"],"status":"available"} if estimate else None
                if origin is not None and origin.grain=="daily" and origin.name.startswith("ENTSOG"):
                    try:
                        scenario=weather_context(analyse_gas_day(store,context.inspection.usable,now,
                            snapshots=state.get(STATE,{})),checked_at())
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
            futures={name:pool.submit(copy_context().run,task) for name,task in tasks.items()}
            for name,future in futures.items():
                try:
                    out[name]=future.result()
                except SourceUnavailable as error:
                    out[name]={**(attribution(name) if name in ("AGSI+","ALSI","IIP") else {"source":name,"source_url":"https://open-meteo.com/"}),
                               "status":"unavailable","reason":str(error)}
                except Exception:
                    out[name]={**(attribution(name) if name in ("AGSI+","ALSI","IIP") else {"source":name,"source_url":"https://open-meteo.com/"}),
                               "status":"unavailable","reason":"Fonte non disponibile o dati non validi; nessun valore sostitutivo."}
    return out
