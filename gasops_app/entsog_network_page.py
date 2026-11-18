"""On-demand ENTSOG network desk within the existing supply page."""
from datetime import timedelta
import pandas as pd
import streamlit as st

from .entsog import _last_completed, SOURCE
from .entsog_network import (PRESETS,PRESET_REFERENCE,MANUAL,TERMS,CATALOG,INDICATORS,NAMES,
                             check_point,load_network,daily_metrics,export_csv)
from .models import utc_now
from .public_data import SourceUnavailable
from .session import database

STATE="entsog_network_result_v1"
ATTEMPT="entsog_network_attempt_v1"


def panel():
    st.subheader("Interconnessioni gas")
    st.caption("ENTSOG · singolo operatore, punto e direzione · GWh/giorno gas")
    with st.expander("Fonti e condizioni"):
        st.markdown(f"[Portale ENTSOG]({SOURCE}) · [Manuale API]({MANUAL}) · [Condizioni d'uso]({TERMS})")
        st.markdown(f"[Catalogo ufficiale operatori/punti/direzioni (CSV)]({CATALOG}) · [Riferimento mapping candidati]({PRESET_REFERENCE})")
        st.caption("Le due preimpostazioni sono candidate da verificare con le etichette ENTSOG restituite. Per altri punti italiani/europei copia il codice ITP dal catalogo. Non sommare i lati opposti di una stessa interconnessione.")
    last=_last_completed(utc_now())
    with st.form("network_query"):
        selected=st.selectbox("Punto",[*PRESETS,"Altro punto ENTSOG"])
        custom=st.text_input("Chiave personalizzata (solo per Altro punto)",placeholder="IT-TSO-0001ITP-00093entry")
        c1,c2=st.columns(2)
        from_day=c1.date_input("Da giorno gas",value=last-timedelta(days=6),max_value=last)
        to_day=c2.date_input("A giorno gas",value=last,max_value=last)
        consent=st.checkbox("Ho letto le condizioni ENTSOG; richiedo un'estrazione limitata.")
        clicked=st.form_submit_button("Carica dati",type="primary")
    if clicked:
        point=PRESETS.get(selected,custom.strip())
        now=utc_now()
        previous=st.session_state.get(ATTEMPT)
        if not consent:
            st.warning("Conferma le condizioni di utilizzo.")
        elif previous is not None and now-previous<timedelta(seconds=60):
            st.warning("Una richiesta per minuto per sessione.")
        else:
            try:
                check_point(point)
                st.session_state[ATTEMPT]=now
                with st.spinner("Acquisizione ENTSOG…"):
                    result=load_network(database(),point,from_day,to_day,now=now)
                st.session_state[STATE]=result
            except (ValueError,SourceUnavailable) as exc:
                st.error(str(exc) if isinstance(exc,SourceUnavailable) else "Punto o periodo non valido (massimo 31 giorni conclusi).")
                if STATE in st.session_state:
                    st.caption("Mostro l'ultima estrazione riuscita, non la richiesta fallita.")
    result=st.session_state.get(STATE)
    if result is None:
        st.info("Seleziona un'interconnessione e carica i dati. Nessun dato simulato.")
        return
    st.markdown("**"+result.point+"**")
    for operator,point_label in result.labels:
        st.text(f"{operator} · {point_label}")
    st.caption(f"{result.first} – {result.last} · {result.credit}"+(" · cache" if result.cached else ""))
    if not result.labels or len(result.labels)!=1:
        st.warning("Etichetta punto non disponibile o non univoca: verifica il catalogo.")
    if result.failed or utc_now()-result.acquired>timedelta(hours=12):
        st.warning("Aggiornamento non riuscito o estrazione di oltre 12 ore: ultima copia valida.")
    if result.metadata_warning:
        st.warning("Conteggi fonte assenti o discordanti: completezza delle pubblicazioni non certificata.")
    if any(r["timestamp_assumed"] for r in result.rows):
        st.caption("Alcuni timestamp senza offset ricondotti alle 06:00 italiane; verifica il report.")
    daily=pd.DataFrame(daily_metrics(result))
    numcols=[c for c in daily if c!="gas_day"]
    daily[numcols]=daily[numcols].apply(pd.to_numeric,errors="coerce")
    valid=sum(r["quality"]=="valido" for r in result.rows)
    flow=daily.dropna(subset=["Physical Flow"])
    latest=flow.iloc[-1] if not flow.empty else None
    cols=st.columns(3)
    cols[0].metric("Flusso ultimo giorno valido","—" if latest is None else f'{latest["Physical Flow"]:.1f} GWh/d')
    cols[1].metric("Utilizzo tecnico stesso giorno","—" if latest is None or pd.isna(latest["technical_utilization_pct"]) else f'{latest["technical_utilization_pct"]:.1f}%')
    cols[2].metric("Valori disponibili",f"{valid}/{len(result.rows)}")
    if latest is not None:
        st.caption("Giorno del flusso: "+latest["gas_day"])
    st.caption("Valori disponibili rispetto alla griglia richiesta; alcuni indicatori possono essere non pubblicati/non applicabili.")
    display=daily.rename(columns=NAMES)
    for title,indicators in (("Flussi e programmi",INDICATORS[:4]),("Capacità firm",INDICATORS[4:])):
        st.subheader(title)
        visible=[NAMES[x] for x in indicators if daily[x].notna().any()]
        if visible:
            st.line_chart(display,x="gas_day",y=visible,y_label="GWh/d")
        else:
            st.info("Nessun valore disponibile in questo gruppo.")
    st.subheader("Scostamenti operativi")
    deltas={"flow_minus_nomination":"Flusso − nomina","flow_minus_renomination":"Flusso − rinomina",
            "allocation_minus_flow":"Allocazione − flusso"}
    comparable=[k for k in deltas if daily[k].notna().any()]
    if comparable:
        st.bar_chart(daily.rename(columns=deltas),x="gas_day",y=[deltas[k] for k in comparable],y_label="GWh/d")
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
