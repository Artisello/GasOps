"""Bounded public evidence for the operational assistant and market briefing.

Only fixed public adapters are consulted. No uploads, participant records,
private PDFs, credential fields or raw API bodies enter this context.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from math import isfinite

from .data import ROME
from .models import Kind, utc_now
from .quality import inspect
from .market import market_facts
from .mensile import load_monthly
from .entsog import load as load_daily, SOURCE as ENTSOG
from .acer_market import load_lng, TERMINAL
from .terna_power import load_power, latest_day, PORTAL
from .terna_forward import acquire as load_forward, outlook as power_outlook, STATE as FORWARD
from .advanced_kpis import benchmark_scores
from .public_data import SourceUnavailable, SourceSchemaError

CACHE="briefing_terna_api_v1"

SOURCES={
    "Eurostat / ARERA":("Eurostat / ARERA","https://ec.europa.eu/eurostat/"),
    "ENTSOG · SRG":("ENTSOG · aggregati SRG",ENTSOG),
    "ACER · GNL":("ACER TERMINAL",TERMINAL),
    "Terna · elettricità":("Terna · consuntivi",PORTAL),
    "Terna · outlook":("Terna · MSD1",PORTAL),
    "Benchmark storici":("ACER / MASE / Terna · benchmark pubblicati",None),
}


def _finite(v):
    try:
        return v is not None and not isinstance(v,bool) and isfinite(float(v))
    except (TypeError,ValueError,OverflowError):
        return False


def _num(v):
    return round(float(v),3) if _finite(v) else None


def _missing(name,reason):
    label,url=SOURCES[name]
    return {"source":label,"source_url":url,"status":"unavailable","reason":reason}


def market_context(bundle,now):
    o=bundle.origin
    if o.archive or o.kind not in (Kind.LIVE,Kind.HISTORICAL):
        raise ValueError("Fonte non corrente")
    checked=inspect(bundle,now)
    facts=market_facts(checked.usable,o.grain)
    if not facts:
        raise ValueError("Assenza di prelievi utilizzabili")
    daily=o.grain=="daily"
    observed=date.fromisoformat(facts["period"])
    today=now.astimezone(ROME).date()
    age=(today-observed).days
    stale=o.refresh_failed or not 0<=age<=(3 if daily else 93) or o.retrieved_at>now
    fields=("demand_gwh","distribution_gwh","industry_gwh","power_gwh") if daily else (
        "demand_gwh","supply_gwh","production_gwh","net_imports_gwh","imports_gwh","exports_gwh","stock_change_gwh")
    values={key:_num(facts.get(key)) for key in fields if _finite(facts.get(key))}
    changes={key:_num(facts.get(key+"_change_pct")) for key in fields if _finite(facts.get(key+"_change_pct"))}
    out={"source":o.name,"source_url":o.url,"acquired":o.retrieved_at.isoformat(),
         "period":facts["period"],"scope":"Tre aggregati di uscita SRG" if daily else "Italia",
         "grain":"giorno gas" if daily else "mese","unit":"GWh/giorno gas" if daily else "GWh/mese",
         "status":"stale" if stale else "available","values":values,"changes_pct":changes,
         "comparison":"medie di finestre da 7 giorni, minimo 5 coppie" if daily else "mese precedente",
         "quality_review":any(f.severity in ("high","medium") for f in checked.findings),
         "kind":"observed","limitation":"Somma dei prelievi dei tre aggregati SRG, non domanda netta, totale nazionale o saldo fisico. Variazione: medie su finestre di sette giorni con almeno cinque coppie." if daily else "Bilancio nazionale mensile; IC_CAL_MG è consumo interno calcolato, non disponibilità fisica. Variazione delle scorte: positiva in accumulo."}
    if daily and "source_flag" in bundle.rows:
        flags=bundle.rows.loc[bundle.rows.period.astype(str).str[:10]==facts["period"],"source_flag"]
        out["quality_review"]=out["quality_review"] or bool(flags.astype(str).str.contains("discordante|conflitto").any())
    if not daily:
        prices=checked.usable["price_eur_mwh"].dropna()
        provider=next((p for p in o.companions if "price_eur_mwh" in p.fields),None)
        if provider and len(prices):
            pday=prices.index[-1].date()
            price=_num(prices.iloc[-1])
            price_stale=provider.refresh_failed or provider.retrieved_at>now or not 0<=(today-pday).days<=93
            out["price"]={"source":provider.name,"source_url":provider.url,"period":pday.isoformat(),
                          "acquired":provider.retrieved_at.isoformat(),"status":"stale" if price_stale else "available",
                          "value":price,"change_pct":_num(facts.get("price_eur_mwh_change_pct")) if pday.isoformat()==facts["period"] else None,
                          "unit":"€/MWh","limitation":"ARERA CMEM,m medio mensile; non prezzo spot."}
    return out


def acer_context(result,now):
    today=now.astimezone(ROME).date()
    values={}
    definitions={"eu":"Valutazione prezzo GNL UE","nwe":"Valutazione prezzo GNL Europa nord-occidentale",
                 "south":"Valutazione prezzo GNL Europa meridionale","benchmark":"Benchmark GNL ACER: differenziale GNL–TTF"}
    for key in ("eu","nwe","south","benchmark"):
        valid=[(r["date"],_num(r.get(key))) for r in result.rows if _finite(r.get(key)) and date.fromisoformat(r["date"])<=today]
        if valid:
            day,value=max(valid,key=lambda x:x[0])
            values[key]={"period":day,"value":value,"definition":definitions[key],"status":"available" if not result.failed and result.acquired<=now and (today-date.fromisoformat(day)).days<=7 else "stale"}
    if not values:
        raise ValueError("Nessuna quotazione")
    return {"source":"ACER TERMINAL","source_url":TERMINAL,"scope":"UE / regioni ACER",
            "acquired":result.acquired.isoformat(),"period":max(v["period"] for v in values.values()),
            "status":"available" if any(v["status"]=="available" for v in values.values()) else "stale",
            "unit":"€/MWh","kind":"observed","values":values,
            "limitation":"Valutazioni di prezzo GNL e differenziale GNL–TTF, in €/MWh; non riserve, scorte, capacità o PSV. Date per singola serie; nessuna variazione storica implicita."}


def power_context(result,now):
    acquired=datetime.fromisoformat(result["acquired"])
    limit=latest_day(now).isoformat()
    by={}
    for row in result["rows"]:
        day=row["gas_day"]
        metric=row["metric"]
        if (metric not in ("Thermal","Wind","Photovoltaic","Hydro","Geothermal","load")
            or day>limit or not _finite(row.get("gwh"))
            or row.get("valid_slots")!=row.get("expected_slots") or not row.get("expected_slots")):
            continue
        by.setdefault(day,{}).setdefault(metric,set()).add(float(row["gwh"]))
    values={}
    for metric in ("Thermal","Wind","Photovoltaic","Hydro","Geothermal","load"):
        valid=[(d,next(iter(v[metric]))) for d,v in by.items() if len(v.get(metric,set()))==1]
        if valid:
            day,val=max(valid,key=lambda x:x[0])
            values[metric]={"period":day,"value":_num(val)}
    if not values:
        raise ValueError("Nessun giorno elettrico completo")
    period=max(v["period"] for v in values.values())
    stale=not timedelta(0)<=now-acquired<=timedelta(hours=24) or (date.fromisoformat(limit)-date.fromisoformat(period)).days>2
    return {"source":"Terna · consuntivi","source_url":PORTAL,"scope":"Italia elettrica",
            "period":period,"acquired":acquired.isoformat(),"status":"stale" if stale else "available",
            "kind":"observed","unit":"GWh elettrici/giorno gas","values":values,
            "quality_review":bool(result.get("warning")),
            "limitation":"Giorni completi; timestamp assunto inizio intervallo; termoelettrico include tutti i combustibili, non consumo gas."}


def benchmarks():
    rows=[]
    for item in benchmark_scores():
        if _finite(item.value):
            rows.append({"label":item.label,"value":_num(item.value),"unit":item.unit,"period":item.period,
                         "scope":item.scope,"source":item.source,"source_url":item.source_url})
    return {"source":SOURCES["Benchmark storici"][0],"status":"available","kind":"historical benchmark",
            "period":"2024/2025 – 2025","values":rows,"limitation":"Riferimenti annuali storici, non situazione attuale."}


def collect_market_sources(store,selected,now,state,*,terna=(),clock=utc_now,only=None):
    """Use bounded alternate market windows and current API snapshots only on launch."""
    if selected.origin.archive or selected.origin.kind not in (Kind.LIVE,Kind.HISTORICAL):
        return {}
    # Existing API-generated snapshots only, never arbitrary imported series.
    prior=state.get(CACHE,{})
    live_power=state.get("terna_power_v1",{}).get("power")
    def fresh(value):
        try:return timedelta(0)<=now-datetime.fromisoformat(value["acquired"])<=timedelta(hours=12)
        except (TypeError,ValueError,KeyError):return False
    tasks={
        "Eurostat / ARERA":lambda:market_context(selected if selected.origin.grain=="monthly" else load_monthly(store)[0],clock()),
        "ENTSOG · SRG":lambda:market_context(selected if selected.origin.grain=="daily" else load_daily(store,now=now,months=2)[0],clock()),
        "ACER · GNL":lambda:acer_context(load_lng(store),clock()),
        "Benchmark storici":benchmarks,
    }
    if only is not None:
        tasks={name:fn for name,fn in tasks.items() if name in only}
    cache=dict(prior)
    attempted=dict(prior.get("attempted",{}))
    out={}
    can_call=len(terna)==2 and all(terna)
    def terna_actual():
        p=next((p for p in (live_power,prior.get("power")) if p and fresh(p)),None)
        if p is None:
            if not can_call:raise ValueError("Terna non configurata")
            end=latest_day(now)
            p=load_power(*terna,end-timedelta(days=2),end,now=now)
        return power_context(p,clock()),p
    def terna_forecast():
        b=prior.get("forward")
        if not b or not fresh(b):
            if not can_call:raise ValueError("Terna non configurata")
            day=now.astimezone(ROME).date()
            b,_=load_forward(*terna,day,day+timedelta(days=1),now,clock=clock)
        result=power_outlook({FORWARD:[b]},clock())
        if not result:raise ValueError("Previsione Terna non disponibile")
        return {**result,"source_url":result["url"],"scope":"Italia elettrica","kind":"forecast",
                "unit":"GWh elettrici/giorno","status":"available","period":result["to"]},b
    if can_call or live_power or prior.get("power"):tasks["Terna · elettricità"]=terna_actual
    else:out["Terna · elettricità"]=_missing("Terna · elettricità","Credenziali Terna non configurate.")
    if can_call or prior.get("forward"):tasks["Terna · outlook"]=terna_forecast
    else:out["Terna · outlook"]=_missing("Terna · outlook","Credenziali Terna non configurate.")
    if only is not None:
        tasks={name:fn for name,fn in tasks.items() if name in only}
        out={name:item for name,item in out.items() if name in only}
    for name in ("Terna · elettricità","Terna · outlook"):
        if name not in tasks:continue
        at=attempted.get(name)
        if at and timedelta(0)<=now-at<timedelta(minutes=1):
            snapshot=prior.get("power" if name=="Terna · elettricità" else "forward")
            if not snapshot or not fresh(snapshot):
                tasks.pop(name)
                out[name]=_missing(name,"Aggiornamento appena tentato; riprovare dopo un minuto.")
        elif name in tasks:
            attempted[name]=now
    cache["attempted"]=attempted
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={name:pool.submit(fn) for name,fn in tasks.items()}
        for name,future in futures.items():
            try:
                value=future.result()
                if name in ("Terna · elettricità","Terna · outlook"):
                    value,snapshot=value
                    cache["power" if name=="Terna · elettricità" else "forward"]=snapshot
                out[name]=value
            except (SourceUnavailable,SourceSchemaError) as error:
                # These adapters emit controlled static diagnostics, not raw responses.
                out[name]=_missing(name,str(error))
            except Exception:
                out[name]=_missing(name,"Fonte non disponibile o non validabile; nessuna stima sostitutiva.")
    state[CACHE]=cache
    return {name:out[name] for name in SOURCES if name in out}
