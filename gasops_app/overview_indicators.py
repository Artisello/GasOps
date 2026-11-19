"""Independent, dated public indicators; no acquisition until requested."""
from datetime import date,datetime,timedelta
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import streamlit as st

from .data import ROME,period_text
from .italiano import data_it,numero
from .mensile import ARERA_URL,Prices,load_arera
from .models import Kind,utc_now
from .operational_sources import GIE_TERMS,attribution,load_agsi,load_alsi
from .operational_sources_page import configured_key
from .session import database
from .supply_view import finite,inventory_snapshot
from .visuals import kpi_grid

STATE="overview_public_indicators_v1"


def price_snapshot(prices,now):
    if not prices.rows:
        raise ValueError("Prezzo assente.")
    period=max(prices.rows)
    val=finite(prices.rows[period])
    if val is None:
        raise ValueError("Ultimo prezzo non valido.")
    month=pd.Timestamp(period)
    local=now.astimezone(ROME)
    age=(local.year-month.year)*12+local.month-month.month
    return {"value":val,"period":period_text(month,"monthly"),
            "stale":prices.source.refresh_failed or age>2 or age<0,
            "acquired":prices.source.retrieved_at}


def supply_snapshot(result,now,platform):
    if result["scope"]!="IT":
        raise ValueError("Perimetro non italiano.")
    row,changes=inventory_snapshot(result["frame"],platform)
    day=row["gas_day"]
    age=((now.astimezone(ROME)-timedelta(hours=6)).date()-day).days
    field="fill_pct" if platform=="AGSI+" else "sendout_gwh_d"
    value=finite(row[field])
    if value is None:
        raise ValueError("Indicatore assente nell'ultimo giorno disponibile.")
    return {"value":value,"period":data_it(day),"gas_day":day.isoformat(),"stale":result["failed"] or age>2 or age<0,
            "quality_review":bool(row.get("review",False)) if platform=="AGSI+" else False,
            "estimated":str(row.get("status",""))=="E",
            "acquired":result["acquired"],"change":changes.get(field)}


def acquire_indicators(store,key,now,*,refresh=False):
    tasks={"price":lambda:price_snapshot(load_arera(store,refresh=refresh),now)}
    if key:
        tasks["storage"]=lambda:supply_snapshot(load_agsi(store,key,"IT",now=now,refresh=refresh),now,"AGSI+")
        tasks["lng"]=lambda:supply_snapshot(load_alsi(store,key,"IT",now=now,refresh=refresh),now,"ALSI")
    out={}
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs={name:pool.submit(task) for name,task in tasks.items()}
        for name,future in jobs.items():
            try:
                out[name]=future.result()
            except Exception:
                out[name]={"error":True}
    return out


def current_rows(snapshot,now,*,gie_enabled):
    specs=(("price","CMEM,m (ARERA)","€/MWh","ARERA · CMEM,m",2),
           ("storage","Riempimento stoccaggi","%","GIE · AGSI+",1),
           ("lng","Send-out GNL","GWh/giorno","GIE · ALSI",1))
    rows=[]
    for name,label,unit,source,decimals in specs:
        item=snapshot.get(name)
        if name!="price" and not gie_enabled:
            rows.append((label,None,unit,"Chiave GIE non configurata",decimals,""))
            continue
        if not item or item.get("error"):
            rows.append((label,None,unit,source+" · "+("Non disponibile" if item else "Non ancora consultato"),decimals,""))
            continue
        elapsed=now-item["acquired"]
        old=elapsed>timedelta(hours=12 if name=="price" else 24) or elapsed<timedelta(0)
        detail=source+" · "+item["period"]
        if item["stale"] or old:
            detail+=" · Da aggiornare"
        if item.get("quality_review"):
            detail+=" · Valore da verificare"
        if item.get("estimated"):
            detail+=" · Stimato dalla fonte"
        if name=="storage" and item.get("change") is not None:
            detail+=" · "+numero(item["change"],1,signed=True)+" p.p. in 7 gg"
        rows.append((label,item["value"],unit,detail,decimals,""))
    return rows


def reuse_indicators(snapshot,context,visited,now):
    """Reuse validated public data from existing pages without network calls."""
    merged=dict(snapshot)
    if "price" not in merged and context is not None and context.bundle.origin.grain=="monthly":
        companion=next((f for f in context.bundle.origin.companions if "price_eur_mwh" in f.fields),None)
        values=context.inspection.usable["price_eur_mwh"].dropna()
        if companion and not values.empty:
            period=values.index[-1].date().isoformat()
            try:
                item=price_snapshot(Prices({period:values.iloc[-1]},companion),now)
                item["stale"]=item["stale"] or bool(getattr(context.bundle.origin,"refresh_failed",False))
                merged["price"]=item
            except (ValueError,TypeError):
                merged["price"]={"error":True}
    for name,platform in (("storage","AGSI+"),("lng","ALSI")):
        if name in merged:
            continue
        saved=visited.get(platform+"_IT",{})
        if saved.get("result") is not None:
            try:
                item=supply_snapshot(saved["result"],now,platform)
                item["stale"]=item["stale"] or bool(saved.get("error"))
                merged[name]=item
            except (ValueError,KeyError,TypeError):
                merged[name]={"error":True}
    return merged


def reuse_briefing(snapshot,run,now):
    """Read dated Italian public observations already acquired for the report,
    without refreshing timestamps or replacing newer independent snapshots.
    """
    merged=dict(snapshot)
    if run is None or run.source.archive or run.source.kind==Kind.SYNTHETIC:
        return merged
    public=run.assumptions.get("public_operational_context") or {}
    for name,platform,field in (("storage","AGSI+","fill_pct"),("lng","ALSI","sendout_gwh_d")):
        item=public.get(platform,{})
        if item.get("scope")!="IT" or item.get("status") not in ("available","stale"):continue
        try:
            day=date.fromisoformat(item["gas_day"])
            acquired=datetime.fromisoformat(item["acquired"])
            if acquired.tzinfo is None or acquired>now:continue
            age=((now.astimezone(ROME)-timedelta(hours=6)).date()-day).days
            if age<0:continue
            values=item.get("values",{}) if item["status"]=="available" else item.get("last_observed_values",{})
            value=finite(values.get(field))
            if value is None:continue
            old=merged.get(name,{})
            if old.get("acquired") is not None and old["acquired"]>=acquired:continue
            # A new observation may be acquired later but still be an older gas day.
            if old.get("gas_day") and day<date.fromisoformat(old["gas_day"]):continue
            merged[name]={"value":value,"period":data_it(day),"gas_day":day.isoformat(),"acquired":acquired,
                          "stale":item["status"]!="available" or age>2,
                          "quality_review":bool(item.get("quality_review")),
                          "estimated":item.get("source_status")=="E"}
        except (ValueError,TypeError,KeyError,OverflowError):
            continue
    return merged


def panel(context=None, *, briefing=None):
    with st.container(border=True,key="panel_overview_indicators"):
        left,right=st.columns([2,1],vertical_alignment="center")
        with left:
            st.subheader("Prezzo e forniture")
            st.caption("Italia · periodi distinti")
        key=configured_key()
        now=utc_now()
        previous=st.session_state.get(STATE,{})
        with right:
            clicked=st.button("Aggiorna indicatori",key="overview_public_refresh",icon=":material/refresh:",width="stretch")
        if clicked:
            last=previous.get("attempted")
            if last and now-last<timedelta(seconds=60):
                st.info("Attendi 60 secondi prima di riprovare.")
            else:
                with st.spinner("Consultazione di ARERA e, se configurato, GIE…"):
                    values=acquire_indicators(database(),key,now,refresh=bool(last))
                retained=dict(previous.get("values",{}))
                for name,item in values.items():
                    if item.get("error") and name in retained and not retained[name].get("error"):
                        retained[name]={**retained[name],"stale":True}
                    else:retained[name]=item
                previous={"attempted":now,"values":retained}
                st.session_state[STATE]=previous
        snapshots=reuse_indicators(previous.get("values",{}),context,st.session_state,now)
        snapshots=reuse_briefing(snapshots,briefing,now)
        cards=current_rows(snapshots,now,gie_enabled=bool(key))
        kpi_grid(cards)
        links=["[ARERA · CMEM,m]("+ARERA_URL+")"]
        for platform in ("AGSI+","ALSI"):
            source=attribution(platform)
            links.append("["+source["source"]+"]("+source["source_url"]+")")
        links.append("[Condizioni GIE]("+GIE_TERMS+")")
        with st.expander("Fonti e significato degli indicatori"):
            st.markdown(" · ".join(links))
            st.caption("CMEM,m: riferimento mensile, non spot. Riempimento: giacenza fisica, non capacità commerciale. Send-out: gas da GNL immesso in rete.")
