"""On-demand ENTSOG network desk within the existing supply page."""
from datetime import timedelta
import pandas as pd
import streamlit as st

from .entsog import _last_completed, SOURCE
from .entsog_network import (PRESETS,PRESET_REFERENCE,MANUAL,TERMS,CATALOG,INDICATORS,NAMES,
                             check_point,load_network,daily_metrics,export_csv)
from .models import utc_now
from .public_data import SourceUnavailable, SourceSchemaError
from .terna_charts import timeseries, day_label, acquisition_label
from .visuals import kpi_grid, plot, info
from .session import database
from .italian_network import load_network_assets, verified_bindings, point_direction_labels, direction_name
from .italian_network_map import display_name
from .direction_ui import arrow_text, direction_header

STATE="entsog_network_result_v1"
ATTEMPT="entsog_network_attempt_v1"


def panel():
    st.subheader("Interconnessioni gas")
    st.caption("ENTSOG · singolo operatore, punto e direzione · GWh/giorno gas")
    def sources():
        with st.expander("Fonti e condizioni"):
            st.markdown(f"[Portale ENTSOG]({SOURCE}) · [Manuale API]({MANUAL}) · [Condizioni d'uso]({TERMS})")
            st.markdown(f"[Catalogo ufficiale operatori/punti/direzioni (CSV)]({CATALOG}) · [Riferimento mapping candidati]({PRESET_REFERENCE})")
            st.caption("Le direzioni italiane censite sono distinte per punto e operatore; verifica le etichette ENTSOG restituite. Per altri punti italiani/europei copia la chiave completa dal catalogo. Non sommare i lati opposti di una stessa interconnessione.")
    last=_last_completed(utc_now())
    # Keep legacy keys usable, but present all verified Italian directions.
    network=load_network_assets()
    bindings=verified_bindings(network)
    types=point_direction_labels(network)
    lookup={i.id:i for i in network.infrastructure}
    catalog={b.point_direction:b for b in bindings}
    presets=dict(PRESETS)
    labels={}
    for b in bindings:
        existing=next((k for k,v in presets.items() if v==b.point_direction),None)
        key=existing or b.point_direction
        presets[key]=b.point_direction
        labels[key]=display_name(lookup[b.infrastructure_id].name)+" · "+arrow_text(types[b.point_direction])+(
            " · "+arrow_text(b.direction) if types[b.point_direction]=="Bidirezionale" else "")
    selected=st.selectbox("Interconnessione e direzione",[*presets,"Altro punto ENTSOG"],key="network_point",
        format_func=lambda k:labels.get(k,k))
    with st.form("network_query",border=False):
        custom=st.text_input("Codice operatore-punto-direzione",placeholder="IT-TSO-0001ITP-00093entry") if selected=="Altro punto ENTSOG" else ""
        c1,c2=st.columns(2)
        from_day=c1.date_input("Da giorno gas",value=last-timedelta(days=6),max_value=last)
        to_day=c2.date_input("A giorno gas",value=last,max_value=last)
        clicked=st.form_submit_button("Carica dati",type="primary",width="stretch")
    if clicked:
        point=presets.get(selected,custom.strip())
        now=utc_now()
        previous=st.session_state.get(ATTEMPT)
        if previous is not None and now-previous<timedelta(seconds=60):
            st.warning("Una richiesta per minuto per sessione.")
        else:
            try:
                check_point(point)
                if not 0<=(to_day-from_day).days<31:raise SourceSchemaError("Seleziona da 1 a 31 giorni gas.")
                st.session_state[ATTEMPT]=now
                with st.spinner("Acquisizione ENTSOG…"):
                    result=load_network(database(),point,from_day,to_day,now=now)
                st.session_state[STATE]=result
                from .entsog_vintages import capture,merge,STATE as ARCHIVE,SELECT
                st.session_state[SELECT]=point
                try:st.session_state[ARCHIVE]=merge(st.session_state.get(ARCHIVE,[]),[capture(result,utc_now())],utc_now())
                except ValueError:st.caption("Estrazione disponibile; archivio non aggiornato.")
            except (SourceSchemaError,SourceUnavailable) as exc:
                st.warning(str(exc))
                if STATE in st.session_state:
                    st.caption("Mostro l'ultima estrazione riuscita, non la richiesta fallita.")
    from .entsog_vintages_page import panel as archive_panel
    result=st.session_state.get(STATE)
    if result is None:
        st.info("Seleziona un’interconnessione e carica i dati.")
        archive_panel()
        sources()
        return
    if len(result.labels)==1:
        operator,point_label=result.labels[0]
        st.markdown("**"+(point_label or result.point)+"**")
        st.caption(operator+" · "+result.point)
    else:st.markdown("**"+result.point+"**")
    if result.point in catalog:
        st.html(direction_header(types[result.point],catalog[result.point].direction))
    else:
        st.caption("Tipologia non verificata nel catalogo italiano · Dati: "+direction_name("exit" if result.point.endswith("exit") else "entry" if result.point.endswith("entry") else None))
    st.caption(f"{day_label(result.first)} – {day_label(result.last)} · acquisizione {acquisition_label(result.acquired.isoformat())}"+(" · cache" if result.cached else ""))
    if not result.labels or len(result.labels)!=1:
        st.warning("Etichetta punto non disponibile o non univoca: verifica il catalogo.")
    if result.failed or utc_now()-result.acquired>timedelta(hours=12):
        st.warning("Aggiornamento non riuscito o estrazione di oltre 12 ore: ultima copia valida.")
    if result.metadata_warning:
        st.warning("Copertura non certificata. Sono visualizzate soltanto le osservazioni validate.")
    if getattr(result,"diagnostic",()):
        with st.expander("Diagnostica acquisizione"):
            for note in result.diagnostic:st.text(note)
    if any(r["timestamp_assumed"] for r in result.rows):
        st.caption("Alcuni timestamp senza offset ricondotti alle 06:00 italiane; verifica il report.")
    daily=pd.DataFrame(daily_metrics(result))
    numcols=[c for c in daily if c!="gas_day"]
    daily[numcols]=daily[numcols].apply(pd.to_numeric,errors="coerce")
    valid=sum(r["quality"]=="valido" for r in result.rows)
    flow=daily.dropna(subset=["Physical Flow"])
    latest=flow.iloc[-1] if not flow.empty else None
    day=day_label(latest["gas_day"]) if latest is not None else "Non disponibile"
    utilization=None if latest is None or pd.isna(latest["technical_utilization_pct"]) else float(latest["technical_utilization_pct"])
    kpi_grid([("Flusso fisico",None if latest is None else float(latest["Physical Flow"]),"GWh/g",day,1,""),
              ("Flusso / capacità tecnica",utilization,"%",day,1,""),
              ("Valori disponibili",valid,"/ "+str(len(result.rows)),"Griglia richiesta",0,"")])
    st.caption("Valori disponibili rispetto alla griglia richiesta; alcuni indicatori possono essere non pubblicati/non applicabili.")
    display=daily.rename(columns=NAMES)
    for title,indicators in (("Flussi e programmi",INDICATORS[:4]),("Capacità firm",INDICATORS[4:])):
        st.subheader(title)
        visible=[NAMES[x] for x in indicators if daily[x].notna().any()]
        if visible:
            plot(timeseries(display.set_index("gas_day")[visible],"GWh/giorno gas"),"network_"+indicators[0])
        else:
            st.info("Nessun valore disponibile in questo gruppo.")
    st.subheader("Scostamenti operativi")
    deltas={"flow_minus_nomination":"Flusso − nomina","flow_minus_renomination":"Flusso − rinomina",
            "allocation_minus_flow":"Allocazione − flusso"}
    comparable=[k for k in deltas if daily[k].notna().any()]
    if comparable:
        plot(timeseries(daily.rename(columns=deltas).set_index("gas_day")[[deltas[k] for k in comparable]],"GWh/giorno gas"),"network_deltas")
    else:
        st.info("Non ci sono coppie confrontabili.")
    st.caption("Differenze tra dati giornalieri pubblicati, non errori di previsione ex ante, DS individuali o penali.")
    with st.expander("Utilizzo capacità, qualità e download"):
        st.dataframe(daily.rename(columns={**NAMES,**deltas,"technical_utilization_pct":"Flusso / tecnica (%)",
                                           "booked_technical_pct":"Prenotata / tecnica (%)"}),hide_index=True,width="stretch")
        st.caption("Rapporti non limitati al 100%; valori negativi o denominatore non positivo non producono rapporti. Non sono una misura di congestione commerciale.")
        st.dataframe(list(result.rows),hide_index=True,width="stretch")
        st.download_button("Scarica CSV con fonte",export_csv(result),"igor-entsog-network.csv","text/csv")
        st.caption(result.credit+" · elaborazioni I.G.O.R.; nessuna somma tra direzioni, nessuna imputazione.")

    archive_panel()
    sources()
