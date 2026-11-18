"""ACER market desk; independent of the selected demand source."""
from datetime import timedelta
import pandas as pd
import streamlit as st

from .acer_market import (TERMINAL,CSV_URL,LEGAL,METHODOLOGY,BALANCING,REPORT_2025,REPORT_2026,CHEST,
                          FIELDS,bundled_lng,load_lng,with_spreads,balancing_rows,lng_export,parse_lng,MAX_BYTES)
from .models import utc_now
from .public_data import SourceUnavailable
from .session import database

STATE="acer_lng_result_v1"
ATTEMPT="acer_lng_attempt_v1"
LABELS={"nwe":"Nord-Ovest Europa","south":"Sud Europa","eu":"UE",
        "benchmark":"GNL UE − TTF front-month (pubblicato)","south_minus_nwe":"Sud − Nord-Ovest"}


def panel():
    st.subheader("Mercato europeo · ACER")
    mode=st.radio("Analisi",["Prezzi GNL","Benchmark bilanciamento"],horizontal=True,key="acer_mode")
    if mode=="Prezzi GNL":
        _lng()
    else:
        _balancing()


def _lng():
    st.caption("Prezzi spot DES GNL · EUR/MWh · date di pubblicazione, non giorno gas.")
    with st.expander("Fonti e aggiornamento",expanded=STATE not in st.session_state):
        st.markdown(f"[ACER TERMINAL]({TERMINAL}) · [CSV storico ufficiale]({CSV_URL}) · [Metodologia]({METHODOLOGY}) · [Condizioni]({LEGAL})")
        st.caption("Il benchmark ACER è uno spread rispetto al future TTF front-month, non il prezzo TTF né il prezzo di sbilanciamento.")
        update=st.button("Aggiorna da ACER",key="acer_update",type="primary",icon=":material/refresh:")
        if update:
            now=utc_now()
            if ATTEMPT in st.session_state and now-st.session_state[ATTEMPT]<timedelta(seconds=60):
                st.warning("Una richiesta ogni 60 secondi per sessione.")
            else:
                st.session_state[ATTEMPT]=now
                try:
                    with st.spinner("Controllo CSV ACER…"):
                        st.session_state[STATE]=load_lng(database(),refresh=True)
                except SourceUnavailable as exc:
                    st.caption("Aggiornamento ACER non disponibile; ultimo dato valido conservato, se presente.")
        with st.form("acer_upload"):
            f=st.file_uploader("Oppure importa il CSV storico scaricato dal portale",type=["csv"])
            st.caption("CSV pubblico · solo sessione.")
            submit=st.form_submit_button("Importa CSV")
        if submit:
            if f is None:
                st.warning("Seleziona un CSV.")
            elif f.size>MAX_BYTES:
                st.error("CSV superiore a 2 MB.")
            else:
                try:
                    st.session_state[STATE]=parse_lng(f.getvalue().decode("utf-8-sig"),utc_now(),
                         provenance="CSV dichiarato ACER, importato dall'utente; fonte non verificata indipendentemente")
                except (UnicodeError,ValueError):
                    st.error("File non leggibile o intestazioni non riconosciute. Serie precedente invariata.")
    result=st.session_state.get(STATE)
    if result is None:
        if not st.checkbox("Consulta estratto storico incluso",key="acer_historical_only"):
            st.caption("Scarica il CSV aggiornato nelle fonti qui sopra, oppure consulta l’estratto storico.")
            return
        result=bundled_lng()
    st.caption("Fonte: ACER · "+result.provenance+" · "+("cache · " if result.cached else "")+f"{result.rows[0]['date']} – {result.rows[-1]['date']}")
    if result.failed:
        st.warning("Aggiornamento non riuscito: ultima cache valida.")
    if result is not None and utc_now().date()-pd.Timestamp(result.rows[-1]["date"]).date()>timedelta(days=4):
        st.warning("Storico non recente, non quotazioni odierne.")
    frame=pd.DataFrame(with_spreads(result.rows))
    cols=[*FIELDS,"south_minus_nwe"]
    frame[cols]=frame[cols].apply(pd.to_numeric,errors="coerce")
    n=st.selectbox("Ultime pubblicazioni",["30","90","365","Tutte"],key="acer_window")
    visible=frame if n=="Tutte" else frame.tail(int(n))
    latest=visible.iloc[-1]
    fields=[k for k in ("eu","benchmark","south_minus_nwe") if pd.notna(latest[k])]
    if fields:
        for col,field in zip(st.columns(len(fields)),fields,strict=True):
            col.metric(LABELS[field],f"{latest[field]:.3f} €/MWh")
    st.caption("Data dei tre indicatori: "+latest["date"]+" · campi mancanti non sostituiti.")
    labels=visible.rename(columns=LABELS)
    st.markdown("**Prezzi GNL**")
    st.line_chart(labels,x="date",y=[LABELS[k] for k in ("eu","nwe","south")],y_label="EUR/MWh")
    st.markdown("**Differenziali**")
    st.bar_chart(labels,x="date",y=[LABELS["benchmark"],LABELS["south_minus_nwe"]],y_label="EUR/MWh",stack=False)
    st.caption("Il Sud − Nord-Ovest è calcolato da I.G.O.R.; il benchmark UE − TTF è il valore pubblicato. Nessuna ricostruzione del TTF.")
    with st.expander("Dati e download"):
        st.dataframe(labels,hide_index=True,width="stretch")
        st.download_button("Esporta con fonte",lng_export(result),"igor-acer-lng.csv","text/csv")
        st.caption("Fonte ACER, consultazione novembre 2026 per l'estratto incluso. Le serie possono essere revisionate.")


def _balancing():
    from .acer_baf_page import panel as baf_panel
    baf_panel()
