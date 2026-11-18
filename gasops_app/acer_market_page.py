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
    with st.expander("Fonti e aggiornamento"):
        st.markdown(f"[ACER TERMINAL]({TERMINAL}) · [CSV storico ufficiale]({CSV_URL}) · [Metodologia]({METHODOLOGY}) · [Condizioni]({LEGAL})")
        st.caption("Il benchmark ACER è uno spread rispetto al future TTF front-month, non il prezzo TTF né il prezzo di sbilanciamento.")
        with st.form("acer_update"):
            consent=st.checkbox("Ho verificato i termini di utilizzo per questo estratto.")
            update=st.form_submit_button("Scarica CSV da ACER")
        if update:
            now=utc_now()
            if not consent:
                st.warning("Conferma i termini della fonte.")
            elif ATTEMPT in st.session_state and now-st.session_state[ATTEMPT]<timedelta(seconds=60):
                st.warning("Una richiesta ogni 60 secondi per sessione.")
            else:
                st.session_state[ATTEMPT]=now
                try:
                    with st.spinner("Controllo CSV ACER…"):
                        st.session_state[STATE]=load_lng(database(),refresh=True)
                except SourceUnavailable as exc:
                    st.error(str(exc))
                    st.caption("Mantengo l'ultima serie disponibile; nessun dato simulato.")
        with st.form("acer_upload"):
            f=st.file_uploader("Oppure importa il CSV storico scaricato dal portale",type=["csv"])
            authorized=st.checkbox("Confermo che il file è pubblico e utilizzabile.")
            submit=st.form_submit_button("Importa CSV")
        if submit:
            if f is None or not authorized:
                st.warning("Seleziona il CSV e conferma l'autorizzazione.")
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
    cards=st.columns(3)
    for col,field in zip(cards,("eu","benchmark","south_minus_nwe"),strict=True):
        val=latest[field]
        col.metric(LABELS[field],"—" if pd.isna(val) else f"{val:.3f} €/MWh")
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
