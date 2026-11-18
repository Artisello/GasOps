"""Session data quality, separate from the scheduled monitor and provider status."""
from datetime import date,datetime,timedelta
from math import isfinite
from decimal import Decimal as D
import pandas as pd
from .data import ROME
from .models import Kind
from .quality import inspect
from .bso_kpis import closed_gas_day
from .entsog import SOURCE as ENTSOG_SOURCE

# Diagnostic presentation windows, not supplier SLAs.
DAYS=14
TOL=D("0.000001")


def finite(x):
    try:return x is not None and isfinite(float(x))
    except (ValueError,TypeError,OverflowError):return False


def stamp(x):
    if isinstance(x,str):x=datetime.fromisoformat(x)
    if not isinstance(x,datetime) or x.tzinfo is None:raise ValueError("Timestamp senza offset.")
    return x


def dates(end,n=DAYS):
    return [end-timedelta(days=i) for i in range(n-1,-1,-1)]


def months(end,n=6):
    out=[]
    d=end.replace(day=1)
    for _ in range(n):
        out.append(d)
        d=(d-timedelta(days=1)).replace(day=1)
    return out[::-1]


def row(label,scope,kind,values,expected,now,*,acquired=None,failed=False,review=False,
        age_limit=None,forecast=False,note="",attempt=None,period_limit=None,latest_override=None):
    valid={d:v for d,v in values.items() if finite(v) and (period_limit is None or d<=period_limit)}
    latest=latest_override if latest_override is not None else max(valid,default=None)
    count=sum(d in valid for d in expected)
    expected_count=len(expected)
    age=(now.astimezone(ROME).date()-latest).days if latest else None
    at=stamp(acquired) if acquired is not None else None
    last_attempt=None
    if attempt:
        last_attempt=stamp(attempt["at"])
        if last_attempt>now:review=True
        if (at is None or last_attempt>=at) and attempt["status"]=="Da aggiornare":failed=True
        if (at is None or last_attempt>=at) and attempt["status"]=="Da verificare":review=True
    if at and at>now:status="Timestamp futuro"
    elif failed:status="Aggiornamento fallito · ultimo dato" if latest else "Aggiornamento fallito"
    elif not latest or not count:status="Non disponibile nel periodo"
    elif age_limit is not None and (now-at>age_limit if forecast and at else age>age_limit.days if not forecast else True):
        status="Da aggiornare"
    elif count<expected_count or review:status="Da verificare"
    else:status="Copertura verificata"
    return {"source":label,"scope":scope,"kind":kind,"status":status,"latest":latest.isoformat() if latest else None,
            "valid":count,"expected":expected_count,"acquired":at.isoformat() if at else None,
            "attempt":last_attempt.isoformat() if last_attempt else None,"note":note}


def _values(frame,field):
    # Reject ambiguous duplicates; dates normalized only from parsed data.
    grouped={}
    for idx,x in frame[field].items():
        d=pd.Timestamp(idx).date()
        if finite(x):grouped.setdefault(d,set()).add(float(x))
    return {d:next(iter(v)) for d,v in grouped.items() if len(v)==1}


def _bundle(state,key,now,field,label,scope):
    from .live_sources import BUNDLES,STATUS
    bundle=state.get(BUNDLES,{}).get(key)
    daily=key=="daily"
    end=closed_gas_day(now) if daily else now.astimezone(ROME).date().replace(day=1)-timedelta(days=1)
    attempt=state.get(STATUS,{}).get("sources",{}).get(key)
    limit=end if daily else end.replace(day=1)
    default=dates(end) if daily else months(end)
    if bundle is None or bundle.origin.archive or bundle.origin.kind not in (Kind.LIVE,Kind.HISTORICAL) or bundle.origin.grain!=key:
        return row(label,scope,"Osservato",{},default,now,attempt=attempt,period_limit=limit)
    o=bundle.origin
    if field not in o.fields:
        return row(label,scope,"Osservato",{},default,now,attempt=attempt,period_limit=limit)
    provider=next((p for p in o.companions if field in p.fields),o)
    checked=inspect(bundle,now)
    values={d:v for d,v in _values(checked.usable,field).items() if d<=limit}
    latest=max(values,default=None)
    # For monthly data, assess six periods ending at the latest received month,
    # and independently assess freshness against today's date.
    expected=default if daily or latest is None else months(latest)
    review=any(f.severity=="high" for f in checked.findings)
    flags=bundle.rows.get("source_flag")
    if flags is not None and daily:
        recent=bundle.rows.loc[bundle.rows.period.isin([d.isoformat() for d in expected]),"source_flag"]
        review=review or recent.astype(str).str.contains("metadati_totale_discordante|versioni_in_conflitto").any()
    return row(label,scope,"Osservato",values,expected,now,acquired=provider.retrieved_at,
               failed=provider.refresh_failed,review=review,age_limit=timedelta(days=3 if daily else 93),
               attempt=attempt,period_limit=limit,note="Finestra 14 giorni gas; metadati base verificati" if daily else "Ultimi 6 mesi disponibili; freschezza separata")


def _weather(state,now,kind):
    from .weather_source import STATE,enabled
    from .live_sources import STATUS
    forecast=kind=="forecast"
    today=now.astimezone(ROME).date()
    expected=dates(today+timedelta(days=7),7) if forecast else dates(today-timedelta(days=7))
    label="Open-Meteo · outlook" if forecast else "Open-Meteo · ERA5"
    item=state.get(STATE,{}).get(kind)
    if not enabled(state):
        return {**row(label,"Milano/Roma/Napoli","Previsione" if forecast else "Storico",{},expected,now),"status":"Disattivato"}
    if item is None:
        return row(label,"Milano/Roma/Napoli","Previsione" if forecast else "Storico",{},expected,now,
                   attempt=state.get(STATUS,{}).get("sources",{}).get("weather"))
    f=item["frame"]
    clean=f.loc[f["temperature_c"].map(finite)&f["hdd"].map(finite)]
    vals=_values(clean,"hdd")
    return row(label,"Milano/Roma/Napoli","Previsione" if forecast else "Storico",vals,expected,now,
               acquired=item["acquired"],failed=item["failed"],forecast=forecast,
               age_limit=timedelta(hours=12) if forecast else timedelta(days=10),note="Temperatura e HDD entrambi presenti",
               period_limit=expected[-1])


def _inventory(state,now,platform,field,name):
    from .live_sources import STATUS
    attempt=state.get(STATUS,{}).get("sources",{}).get("agsi" if platform=="AGSI+" else "alsi")
    saved=state.get(platform+"_IT",{})
    r=saved.get("result")
    end=now.astimezone(ROME).date()-timedelta(days=1)
    expected=dates(end)
    vals={}
    review=False
    if r:
        f=r["frame"]
        if r["scope"]!="IT":raise ValueError("Perimetro inatteso.")
        vals=_values(f.set_index("gas_day"),field)
        if "review" in f:review=bool(f.loc[f.gas_day.isin(expected),"review"].any())
    return row(name,"Italia","Osservato",vals,expected,now,acquired=r["acquired"] if r else None,
               failed=bool(saved.get("error") or (r and r["failed"])),review=review,
               age_limit=timedelta(days=3),attempt=attempt,period_limit=end,note="14 date pubblicabili; perimetro IT")


def _terna(state,now,metric):
    from .live_sources import STATUS
    attempt=state.get(STATUS,{}).get("sources",{}).get("terna")
    item=state.get("terna_power_v1",{}).get("power")
    end=closed_gas_day(now); expected=dates(end)
    vals={}
    if item:
        for r in item["rows"]:
            if r["metric"]==metric and r["expected_slots"]>0 and r["valid_slots"]==r["expected_slots"] and finite(r["gwh"]):
                d=date.fromisoformat(r["gas_day"])
                if d in vals and vals[d]!=r["gwh"]:raise ValueError("Serie Terna discordante.")
                vals[d]=r["gwh"]
    return row("Terna · "+("generazione termica" if metric=="Thermal" else "fabbisogno"),"Italia · elettricità","Osservato",
               vals,expected,now,acquired=item["acquired"] if item else None,
               review=bool(item and item.get("warning") and metric=="load"),age_limit=timedelta(days=3),
               attempt=attempt,period_limit=end,note="Solo giorni con tutti gli intervalli; aggregazione gas-day sperimentale")


def _acer(state,now):
    from .live_sources import STATUS
    r=state.get("acer_lng_result_v1")
    vals={}
    expected=[]
    if r:
        for v in r.rows[-14:]:
            d=date.fromisoformat(v["date"]);expected.append(d)
            if all(finite(v.get(k)) for k in ("nwe","south","eu","benchmark")):vals[d]=v["eu"]
    return row("ACER · LNG","Europa","Osservato",vals,expected,now,
               acquired=r.acquired if r else None,failed=r.failed if r else False,
               age_limit=timedelta(days=4),attempt=state.get(STATUS,{}).get("sources",{}).get("acer"),
               period_limit=now.astimezone(ROME).date(),note="Ultime 14 righe ricevute, non calendario atteso della fonte")


def session_health(state,now):
    # The availability of a source is not its configured/connected status.
    adapters=[
        ("Eurostat · consumo","Italia",lambda:_bundle(state,"monthly",now,"demand_gwh","Eurostat · consumo","Italia")),
        ("ARERA · PSV","Italia",lambda:_bundle(state,"monthly",now,"price_eur_mwh","ARERA · PSV","Italia")),
        ("ENTSOG · prelievi","SRG",lambda:_bundle(state,"daily",now,"demand_gwh","ENTSOG · prelievi","SRG · tre aggregati")),
        ("GIE · AGSI+","Italia",lambda:_inventory(state,now,"AGSI+","stock_twh","GIE · AGSI+")),
        ("GIE · ALSI","Italia",lambda:_inventory(state,now,"ALSI","sendout_gwh_d","GIE · ALSI")),
        ("Terna · generazione termica","Italia",lambda:_terna(state,now,"Thermal")),
        ("Terna · fabbisogno","Italia",lambda:_terna(state,now,"load")),
        ("ACER · LNG","Europa",lambda:_acer(state,now)),
        ("Open-Meteo · ERA5","Proxy Italia",lambda:_weather(state,now,"era5")),
        ("Open-Meteo · outlook","Proxy Italia",lambda:_weather(state,now,"forecast"))]
    rows=[]
    for name,scope,fn in adapters:
        try:rows.append(fn())
        except (ValueError,KeyError,AttributeError,TypeError,OverflowError,ArithmeticError,IndexError):
            rows.append({**row(name,scope,"Non verificato",{},[],now),"status":"Schema da verificare",
                         "note":"Formato sessione non riconosciuto; nessun valore presunto"})
    return rows


def compare_srg(state,now):
    """Same publisher, same mapping, not independent source corroboration."""
    from .live_sources import BUNDLES
    b=state.get(BUNDLES,{}).get("daily")
    gas=state.get("terna_power_v1",{}).get("gas")
    if (b is None or not gas or b.origin.url!=ENTSOG_SOURCE or b.origin.archive
            or b.origin.grain!="daily" or "power_gwh" not in b.origin.fields):return []
    if b.origin.retrieved_at>now or stamp(gas["acquired"])>now:return []
    f=inspect(b,now).usable
    left=_values(f,"power_gwh")
    right=gas["gas"]
    end=closed_gas_day(now)
    out=[]
    for d,x in sorted(left.items()):
        if d>end or d.isoformat() not in right or not finite(right[d.isoformat()]):continue
        a,c=D(str(x)),D(str(right[d.isoformat()]))
        delta=c-a
        out.append({"day":d.isoformat(),"market_gwh":a,"power_context_gwh":c,"delta_gwh":delta,
                    "status":"Discordante" if abs(delta)>TOL else "Coincide",
                    "market_acquired":b.origin.retrieved_at.isoformat(),"context_acquired":gas["acquired"],
                    "market_sha":b.fingerprint,"review":bool(b.origin.refresh_failed or gas.get("failed") or gas.get("metadata_warning"))})
    return out[-90:]
