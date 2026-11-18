"""ACER market desk; independent of the selected demand source."""
from datetime import timedelta
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .acer_market import (TERMINAL,CSV_URL,LEGAL,METHODOLOGY,FIELDS,bundled_lng,
                          load_lng,cached_lng,with_spreads,lng_export,parse_lng,MAX_BYTES)
from .models import utc_now
from .data import ROME
from .public_data import SourceUnavailable
from .session import database
from .italiano import numero
from .visuals import TEAL,BLUE,AMBER,_frame,kpi_grid,plot,info
from .terna_charts import day_label,acquisition_label

STATE="acer_lng_result_v1"
ATTEMPT="acer_lng_attempt_v1"
LABELS={"nwe":"Nord-Ovest Europa","south":"Sud Europa","eu":"UE",
        "benchmark":"GNL UE − TTF front-month","south_minus_nwe":"Sud − Nord-Ovest"}


def panel():
    st.subheader("Mercato europeo · ACER")
    mode=st.radio("Analisi",["Benchmark bilanciamento","Prezzi GNL"],horizontal=True,
                  key="acer_mode",label_visibility="collapsed")
    if mode=="Prezzi GNL":
        _lng()
    else:
        from .acer_baf_page import panel as baf_panel
        baf_panel()


def _update(now):
    at=st.session_state.get(ATTEMPT)
    if at and now-at<timedelta(seconds=60):
        st.warning("Una richiesta ogni 60 secondi per sessione.")
        return
    st.session_state[ATTEMPT]=now
    try:
        with st.spinner("Acquisizione ACER…"):
            st.session_state[STATE]=load_lng(database(),refresh=True)
    except SourceUnavailable as error:
        st.warning(str(error)+" Ultima serie valida conservata, se presente.")


def _import_controls():
    with st.form("acer_upload",border=False):
        f=st.file_uploader("CSV storico scaricato dal portale",type=["csv"],key="acer_csv_file")
        st.caption("Max 2 MB · fonte dichiarata, solo sessione.")
        submit=st.form_submit_button("Importa CSV")
    if submit:
        if f is None:
            st.warning("Seleziona un CSV.")
        elif f.size>MAX_BYTES:
            st.error("CSV superiore a 2 MB.")
        else:
            try:
                st.session_state[STATE]=parse_lng(f.getvalue().decode("utf-8-sig"),utc_now(),
                     provenance="CSV dichiarato ACER, importato dall’utente; fonte non verificata indipendentemente")
            except (UnicodeError,ValueError):
                st.error("File non leggibile o intestazioni non riconosciute. Serie precedente invariata.")
            else:
                st.rerun()


def latest_cards(frame,today):
    """Different series can have different last published dates; never impute."""
    cards=[]
    for field,label in (("eu","Prezzo GNL UE"),("benchmark","Differenziale GNL–TTF"),
                        ("south_minus_nwe","Sud − Nord-Ovest")):
        series=frame.loc[frame[field].notna(),["date",field]]
        if series.empty:
            cards.append((label,None,"€/MWh","Dato non disponibile",3,""))
            continue
        r=series.iloc[-1]
        stamp=pd.Timestamp(r["date"]).date()
        detail=day_label(r["date"])
        if not 0<=(today-stamp).days<=4:detail+=" · non recente"
        if len(series)>1:
            before=series.iloc[-2]
            diff=r[field]-before[field]
            detail+=" · "+numero(diff,3,signed=True)+" vs "+day_label(before["date"])
        cards.append((label,r[field],"€/MWh",detail,3,""))
    return cards


def lng_figure(frame,fields):
    fig=go.Figure()
    colors={"eu":TEAL,"nwe":BLUE,"south":AMBER,"benchmark":TEAL,"south_minus_nwe":BLUE}
    for field in fields:
        if not frame[field].notna().any():continue
        # Publication dates, not gas days. Do not create artificial weekend rows.
        fig.add_trace(go.Scatter(x=pd.to_datetime(frame.date),y=frame[field],name=LABELS[field],
            mode="lines+markers",connectgaps=False,line={"color":colors[field],"width":2.2},
            marker={"size":4},hovertemplate="%{y:,.3f} €/MWh<extra>"+LABELS[field]+"</extra>",
            xhoverformat="%d/%m/%Y"))
    _frame(fig,"daily","€/MWh",280)
    fig.update_yaxes(tickformat=",.2f",zeroline=True,zerolinecolor="#637891")
    return fig


def _lng():
    now=utc_now()
    today=now.astimezone(ROME).date()
    st.caption("Prezzi spot DES GNL · Europa · date di pubblicazione, non giorno gas")
    a,b=st.columns([3,2],vertical_alignment="center")
    with a:
        info("Indicatori e metodo","Il benchmark ACER è lo spread pubblicato GNL UE − future TTF front-month, non prezzo TTF né prezzo di sbilanciamento. Sud − Nord-Ovest è calcolato sulle due quotazioni della stessa data.")
    if b.button("Aggiorna da ACER",key="acer_update",type="primary",icon=":material/refresh:",width="stretch"):
        _update(now)
    result=st.session_state.get(STATE)
    historical=result is None
    if result is None:
        result=cached_lng(database(),now)
        historical=result is None
    if result is None:
        try:result=bundled_lng()
        except (ValueError,OSError):result=None
    if result is None:
        st.info("Nessuna serie disponibile. Aggiorna da ACER oppure importa il CSV.")
    else:
        last=result.rows[-1]["date"]
        st.caption("ACER · "+day_label(result.rows[0]["date"])+" – "+day_label(last)+" · "+result.provenance)
        if historical:
            st.warning("Estratto storico incluso · non quotazioni correnti. Aggiorna per consultare la serie ufficiale.")
        elif result.failed:
            st.warning("Aggiornamento non riuscito: ultima cache valida.")
        elif today-pd.Timestamp(last).date()>timedelta(days=4):
            st.warning("Serie non recente; non quotazioni odierne.")
        if not historical:
            st.caption("Acquisizione "+acquisition_label(result.acquired.isoformat())+(" · cache" if result.cached else ""))
        frame=pd.DataFrame(with_spreads(result.rows))
        cols=[*FIELDS,"south_minus_nwe"]
        frame[cols]=frame[cols].apply(pd.to_numeric,errors="coerce")
        kpi_grid(latest_cards(frame,today))
        n=st.radio("Pubblicazioni",["30","90","365","Tutte"],horizontal=True,key="acer_window",
                   format_func=lambda x:"Tutte" if x=="Tutte" else "Ultime "+x)
        visible=frame if n=="Tutte" else frame.tail(int(n))
        st.markdown("**Prezzi GNL · €/MWh**")
        if visible[["eu","nwe","south"]].notna().any().any():
            plot(lng_figure(visible,["eu","nwe","south"]),"acer_lng_prices")
        else:st.caption("Nessuna quotazione nel periodo selezionato.")
        st.markdown("**Differenziali · €/MWh**")
        if visible[["benchmark","south_minus_nwe"]].notna().any().any():
            plot(lng_figure(visible,["benchmark","south_minus_nwe"]),"acer_lng_spreads")
        else:st.caption("Nessun differenziale nel periodo selezionato.")
        with st.expander("Dati e download"):
            st.dataframe(visible.rename(columns={"date":"Pubblicazione",**LABELS}),hide_index=True,width="stretch")
            st.download_button("Esporta serie con fonte",lng_export(result),"igor-acer-lng.csv","text/csv",key="acer_export")
    with st.expander("Import manuale"):
        _import_controls()
    with st.expander("Fonti e metodologia"):
        st.markdown(f"[ACER TERMINAL]({TERMINAL}) · [CSV storico ufficiale]({CSV_URL}) · [Metodologia]({METHODOLOGY}) · [Condizioni]({LEGAL})")
        st.caption("Serie revisionabili; valori mancanti non sostituiti. Ultima quotazione disponibile per singolo indicatore. Variazione assoluta rispetto alla precedente pubblicazione disponibile, non variazione giornaliera garantita.")
