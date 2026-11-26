"""Gas-day-first cockpit inside the existing balancing route; no remote fetches."""
from datetime import date, timedelta
from html import escape
import pandas as pd
import streamlit as st

from . import balancing_cockpit as m
from .freshness import label as freshness_label, temporal_evidence
from .gas_data import collect, source_context
from .gas_calendar import closed_gas_day, gas_day_bounds
from .italian_network_page import assets,bundled_interruptions,SELECTED,_open_full
from .italian_network_map import display_name
from .models import utc_now
from .operational_sources import attributed_csv
from .session import database
from .visuals import kpi_grid, plot
from .italiano import data_it
from .workspace import picker


def _tools(user=None,day=None):
    st.session_state.update(balancing_view="Controllo giornaliero",balancing_daily_mode="Settlement e rettifiche",
                            daily_desk_data_mode="Dati importati",daily_desk_section="Giornata" if user and day else "Giornate")
    if user and day:
        st.session_state.update(daily_desk_user=user,daily_desk_month=(day.year,day.month),daily_desk_day=day.isoformat())


def _workflow(steps):
    labels={"Nomination":"Nomina","Renomination":"Rinomina","Allocation":"Allocazione","Reconciliation":"Riconciliazione"}
    items="".join('<li><strong>'+escape(labels.get(label,label))+'</strong><span>'+escape(state)+'</span></li>' for label,state in steps)
    st.html('<style>.igor-cockpit-flow{display:flex;flex-wrap:wrap;gap:8px;list-style:none;padding:0;margin:8px 0}'
            '.igor-cockpit-flow li{flex:1 0 130px;border:1px solid #2d4255;border-radius:10px;padding:10px 12px}'
            '.igor-cockpit-flow strong,.igor-cockpit-flow span{display:block;font-size:13px}'
            '.igor-cockpit-flow span{color:#aab9ca;margin-top:5px}'
            '@media(max-width:1100px){.st-key-cockpit_compare [data-testid="stHorizontalBlock"]{flex-direction:column}'
            '.st-key-cockpit_compare [data-testid="stColumn"]{width:100%!important;flex:1 1 auto!important}}</style>'
            '<ol class="igor-cockpit-flow" aria-label="Dalla nomination al settlement">'+items+'</ol>')


def _export(frame,name,key):
    if frame.empty:return
    try:
        csv=attributed_csv({"frame":frame},per_row_source=True,max_rows=5000)
        st.download_button("Esporta "+name,csv,"igor-"+key+".csv","text/csv",key=key,on_click="ignore")
    except ValueError as exc:st.caption(str(exc))


def _day(default,now,context,*,earliest=None,layout=None):
    day=(layout or st).date_input("Giorno gas",value=default,min_value=earliest or date(2000,1,1),
        max_value=closed_gas_day(now)+timedelta(days=1),format="DD/MM/YYYY",key="cockpit_day_"+context)
    start,stop=gas_day_bounds(day)
    st.caption(f"{data_it(day)} · 06:00–06:00 Europe/Rome · {int((stop-start).total_seconds()/3600)} ore · "+
        ("giornata in corso" if now<stop else "giornata conclusa"))
    return day


def _public(day_layout=None):
    now=utc_now()
    network,_,bundled=assets()
    session=st.session_state
    closed=closed_gas_day(now)
    earliest=date(2000,1,1)
    active=closed+timedelta(days=1)
    requested=session.pop("cockpit_focus_day",None)
    if isinstance(requested,date) and earliest<=requested<=active:
        session["cockpit_day_system"]=requested
    chosen=session.get("cockpit_day_system")
    if not isinstance(chosen,date) or not earliest<=chosen<=active:
        session.pop("cockpit_day_system",None)
        chosen=None
    # The full window is needed only to find the first available default day.
    window={"first":chosen,"last":chosen} if chosen is not None else {}
    context=source_context(network,bundled,session,now,store=database(),interruptions=(bundled_interruptions(),),**window)
    frame=collect(network,bundled,session,now,context=context,**window)
    if chosen is None:
        days=[r.gas_day for r in frame.itertuples() if r.indicator=="Physical Flow" and r.usable and r.gas_day and r.gas_day<=closed]
        chosen=max(days,default=closed)
    day=_day(chosen,now,"system",earliest=earliest,layout=day_layout)
    rows=m.public_reconciliation(network,frame,day)
    position=m.system_position(session,day,now)
    selected=frame.loc[frame.gas_day==day]
    valid=selected.loc[selected.usable.astype(bool)]
    freshness=temporal_evidence(now=now,gas_day=day,current_day=closed,valid=len(valid),expected=len(selected),
        retrieved_at=min(valid.retrieved_at,default=None),cached=bool(len(valid) and valid.cached.eq(True).all()),
        failed=bool(selected.failed.any()),partial=bool(selected.partial.any()))
    kpi_grid([("Posizione di sistema",position["value"],position["unit"],position["status"],1,""),
              ("Punti confrontabili",sum(r["comparable"] for r in rows),"/ "+str(len(rows)),"Direzioni mappate · nomina, rinomina, allocazione e flusso",0,""),
              ("Osservazioni utilizzabili",len(valid),"",freshness_label(freshness),0,"")])
    st.caption(m.ESTIMATED+" · "+position["note"])
    _workflow(m.workflow(rows))
    options=[r["point_direction"] for r in rows if r["available"]]
    by_point={r["point_direction"]:r for r in rows}
    point=None
    if options:
        key="cockpit_point"
        if st.session_state.get(key) not in options:
            st.session_state[key]=next((p for p in options if by_point[p]["infrastructure_id"]==st.session_state.get(SELECTED)),options[0])
        point=st.selectbox("Punto da esaminare",options,key=key,
            format_func=lambda p:display_name(by_point[p]["point"])+" · "+("Ingresso" if by_point[p]["direction"]=="entry" else "Uscita"))
    from .gme_market import private_enabled as gme_enabled
    readouts = ("Riconciliazione","Pubblicazioni","Eventi","Fonti")
    if gme_enabled():
        readouts += ("Prezzi e interventi GME",)
    readout=picker("Consulta",readouts,key="cockpit_readout",
                   labels={"Riconciliazione":"Confronto per punto","Fonti":"Bilancio e fonti"})
    if readout=="Prezzi e interventi GME":
        from .gme_market_page import balancing
        balancing(day)
    elif readout=="Riconciliazione":
        _compare(rows,by_point,point,day)
    elif readout=="Pubblicazioni":
        _publications(frame,point,day,now)
    else:
        from .system_status import build_status
        state=m.inventory_state(context,session,day)
        status=build_status(network,context["snapshots"],state,now,gas_day=day,interruptions=context["interruptions"])
        if readout=="Eventi":
            _events(status,by_point,point)
        else:
            _sources(status,selected,position,day,now,frame.attrs.get("notices",()))


def _compare(rows,by_point,point,day):
    if not rows:
        st.caption("Nessun punto con associazione verificata.")
        return
    with st.container(key="cockpit_compare"):
        table,detail=st.columns([2,1.1],gap="medium")
        with table:
            st.markdown("**Dalla nomina al flusso fisico**")
            names={"point":"Punto","direction":"Direzione","Nomination":"Nomina","Renomination":"Rinomina",
                "Allocation":"Allocazione","Physical Flow":"Flusso fisico","delta_renomination_nomination":"Δ rinomina",
                "delta_allocation_renomination":"Δ allocazione","delta_physical_allocation":"Δ flusso","state":"Stato"}
            display=pd.DataFrame(rows)[list(names)].rename(columns=names)
            number_columns=[names[k] for k in (*m.INDICATORS,"delta_renomination_nomination","delta_allocation_renomination","delta_physical_allocation")]
            for c in number_columns:display[c]=pd.to_numeric(display[c],errors="coerce")
            display["Punto"]=display.Punto.map(display_name)
            display["Direzione"]=display.Direzione.map({"entry":"Ingresso","exit":"Uscita"})
            st.dataframe(display,hide_index=True,width="stretch",height=345,
                column_config={"Punto":st.column_config.TextColumn(width="medium"),"Direzione":st.column_config.TextColumn(width="small"),
                    **{c:st.column_config.NumberColumn(format="%.1f",width="small") for c in number_columns}})
            st.caption("GWh/d · stesso punto, direzione e giorno gas. Ogni Δ confronta due passaggi consecutivi. Il CSV include fonti e versioni.")
        with detail:
            if point:
                from .balancing_charts import point_indicators
                plot(point_indicators(by_point[point]),key="cockpit_point_chart")
                st.caption(display_name(by_point[point]["point"])+" · "+by_point[point]["state"])
                st.button("Apri punto sulla mappa",key="cockpit_map",on_click=_open_full,
                    args=(by_point[point]["infrastructure_id"],day,day,by_point[point]["direction"]))
        _export(pd.DataFrame(rows),"riconciliazione con provenienza","cockpit_reconciliation")


def _publications(frame,point,day,now):
    from .entsog_vintages import audit_rows, STATE as VINTAGES
    with st.container():
        st.caption("Pubblicazione e acquisizione sono distinte. Una sola versione non costituisce una revisione.")
        try:audit=audit_rows(frame,day,now,batches=st.session_state.get(VINTAGES,()))
        except ValueError:
            audit=audit_rows(frame,day,now)
            st.caption("Archivio vintage non valido escluso; osservazioni correnti conservate.")
        audit=[r for r in audit if point is None or r["point_direction"]==point]
        if audit:
            st.dataframe(pd.DataFrame(audit),hide_index=True,width="stretch")
            _export(pd.DataFrame(audit),"audit del punto","cockpit_audit")
        else:st.caption("Nessuna pubblicazione o acquisizione disponibile nel giorno selezionato.")
        jarvis=m.jarvis_audit(st.session_state,day,now)
        if jarvis:
            st.markdown("**Pubblicazioni aggregate Jarvis · fonte dichiarata**")
            st.dataframe(pd.DataFrame(jarvis),hide_index=True,width="stretch")
            _export(pd.DataFrame(jarvis),"audit Jarvis","cockpit_jarvis_audit")
        versions=st.session_state.get("jarvis_public_snapshot_v1",{}).get("versions")
        if isinstance(versions,pd.DataFrame) and (versions.gas_day==day).any():
            from .linepack_page import panel as linepack_panel
            linepack_panel(versions,day,now,"cockpit")
        native=st.session_state.get("jarvis_native_v1",{}).get("frame")
        if isinstance(native,pd.DataFrame):
            native=native.loc[native.gas_day==day.isoformat()]
            if not native.empty:
                with st.expander("Pubblicazioni native Jarvis · righe originali"):
                    st.caption("File, foglio, riga e SHA originali. Unità non confermate escluse dai calcoli; timestamp non inventati.")
                    st.dataframe(native.head(2000),hide_index=True,width="stretch")


def _events(status,by_point,point):
    with st.container():
        current=[e for e in status.active_events if point is None or e.get("infrastructure_id")==by_point[point]["infrastructure_id"]]
        if current:
            st.dataframe(pd.DataFrame(current),hide_index=True,width="stretch")
        else:st.caption("Nessun evento documentato associato al punto nella copia disponibile. Copertura degli avvisi parziale.")
        st.caption("Nessuna azione operativa documentata. I risultati I.G.O.R. non attestano interventi eseguiti.")


def _sources(status,selected,position,day,now,notices):
    from .source_health import gas_health
    from .source_health_page import render_rows
    with st.container():
        st.subheader("Componenti del bilancio giornaliero")
        st.dataframe([
            {"Componente":c.label,"Valore":float(c.measure.value) if c.measure.value is not None else None,"Unità":c.measure.unit,
             "Copertura":f"{c.measure.coverage.valid}/{c.measure.coverage.expected}","Fonte":c.measure.source,
             "Stato":{"stale":"Da aggiornare","partial":"Parziale","fresh":"Recente","unavailable":"Non disponibile"}[c.measure.freshness]}
            for c in status.components],hide_index=True,width="stretch",
            column_config={"Valore":st.column_config.NumberColumn(format="%.1f",width="small")})
        health=gas_health(selected,day,day,now)
        render_rows(health,key="cockpit_health",kpis=False)
        if position["evidence"]:st.dataframe(pd.DataFrame(position["evidence"]),hide_index=True,width="stretch")
        st.caption("Gli import Jarvis sono dichiarati, non attestazioni indipendenti di autenticità. Nessuna fonte attuale abilita un saldo ufficiale Snam.")
        st.caption("Vintage portabili: timestamp di acquisizione dichiarati, non pubblicazioni originali. Non sovrascrivono la riconciliazione corrente.")
        for note in notices:st.caption(note)


def _portfolio(day_layout=None):
    now=utc_now()
    saved=m.authorized_portfolio(st.session_state)
    if saved is None:
        _day(st.session_state.get("cockpit_day_system",closed_gas_day(now)),now,"portfolio",layout=day_layout)
        st.metric("Posizione portafoglio","Non calcolabile")
        st.caption("Nessun bilancio importato con autorizzazione d’uso registrata. I dati pubblici e gli esempi non alimentano questa vista.")
        _workflow(m.workflow([],{}))
        st.button("Apri importazioni e controlli",on_click=_tools,key="cockpit_import")
        return
    users=sorted({r.user for r in saved["rows"]})
    user=st.selectbox("Portafoglio / shipper · ID fittizio",users,key="cockpit_shipper")
    days=[r.day for r in saved["rows"] if r.user==user]
    default=min(max(days),closed_gas_day(now))
    day=_day(default,now,"portfolio",layout=day_layout)
    result=m.portfolio_day(st.session_state,user,day,now)
    kpi_grid([("Posizione portafoglio",result["value"],"MWh",result["status"],2,""),
              ("Importo calcolato",result["cash"],"€","Solo giornata utilizzabile · non fattura",2,""),
              ("Versioni importate",len(result["versions"]),"","Solo shipper e giorno selezionati",0,"")])
    _workflow(m.workflow([],result))
    if result["control"]:
        st.caption(" · ".join(result["control"]["issues"]) or "Controlli del motore esistente superati; nessuna dichiarazione di settlement eseguito.")
    if result["reconciliation"]:
        st.markdown("**Riconciliazione DS / importo comunicato**")
        st.dataframe([result["reconciliation"]],hide_index=True,width="stretch")
    else:st.caption("Estratto indipendente autorizzato assente: riconciliazione non disponibile.")
    if result["evidence"]:
        st.markdown("**Versioni e provenienza**")
        st.dataframe(pd.DataFrame(result["evidence"]),hide_index=True,width="stretch")
        _export(pd.DataFrame(result["evidence"]),"audit del portafoglio","cockpit_portfolio_audit")
    st.caption("Il registro importato non contiene nomination, renomination o misure fisiche per punto: questi passaggi restano non disponibili.")
    st.button("Apri il giorno nel settlement",on_click=_tools,args=(user,day),key="cockpit_settlement")


def panel():
    for key in ("cockpit_day_system","cockpit_day_portfolio"):
        if key in st.session_state:
            st.session_state[key]=st.session_state[key]
    selection,day=st.columns([2,1],vertical_alignment="bottom")
    with selection:
        context=picker("Contesto",("SYSTEM VIEW","PORTFOLIO / SHIPPER VIEW"),key="cockpit_context",
                       labels={"SYSTEM VIEW":"Sistema gas","PORTFOLIO / SHIPPER VIEW":"Portafoglio importato"})
    if context=="SYSTEM VIEW":_public(day)
    else:_portfolio(day)
