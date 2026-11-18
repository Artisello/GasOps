"""Explicit authorized Terna forward-data acquisition and portable snapshots."""
from datetime import timedelta
import json
import pandas as pd
import streamlit as st
from .data import ROME
from .models import utc_now
from .terna_power import credentials,CATALOG
from .terna_forward import STATE,ATTEMPT,MAX_BYTES,DOCS,acquire,merge,outlook
from .public_data import SourceUnavailable


def panel():
    now=utc_now()
    today=now.astimezone(ROME).date()
    st.caption("Carico ed eolico previsti · MSD1 · Italia, sette zone · giorno gas 06–06")
    st.markdown("[Load Forecast]("+DOCS["load"]+") · [Wind Production Forecast]("+DOCS["wind"]+")")
    try:client,secret=credentials(st.secrets)
    except (ValueError,KeyError,FileNotFoundError):client,secret=credentials()
    with st.form("terna_forward_acquire"):
        a,b=st.columns(2)
        first=a.date_input("Dal giorno gas",value=today,min_value=today-timedelta(days=365),max_value=today+timedelta(days=2))
        last=b.date_input("Al giorno gas",value=today+timedelta(days=1),min_value=today-timedelta(days=365),max_value=today+timedelta(days=2))
        st.caption("Timestamp = inizio intervallo (ipotesi sperimentale).")
        clicked=st.form_submit_button("Aggiorna previsioni Terna",disabled=not bool(client and secret))
    if not client or not secret:st.caption("Configura le credenziali Terna sul server; puoi comunque ripristinare un archivio.")
    if clicked:
        previous=st.session_state.get(ATTEMPT)
        if previous and now-previous<timedelta(minutes=1):st.caption("Riprova dopo 60 secondi.")
        else:
            st.session_state[ATTEMPT]=now
            try:
                with st.spinner("Terna · acquisizione delle previsioni…"):
                    batch,notes=acquire(client,secret,first,last,now)
                    st.session_state[STATE]=merge(st.session_state.get(STATE,[]),[batch],utc_now())
                if notes:st.caption(" · ".join(notes))
            except (SourceUnavailable,ValueError,TypeError,KeyError):
                st.caption("Fonte non disponibile o copertura insufficiente; archivio precedente invariato.")
    with st.expander("Archivio versionato"):
        f=st.file_uploader("Ripristina JSON dello storico previsionale",type=["json"],key="terna_forward_file")
        st.caption("JSON pubblico · timestamp dichiarati, non autenticati.")
        if st.button("Unisci archivio",disabled=f is None,key="terna_forward_import"):
            try:
                if f.size>MAX_BYTES:raise ValueError("Archivio eccessivo")
                obj=json.loads(f.getvalue())
                if obj["version"]!=1:raise ValueError("Versione")
                st.session_state[STATE]=merge(st.session_state.get(STATE,[]),obj["batches"],now)
            except (ValueError,TypeError,KeyError,OverflowError):st.caption("Archivio non valido; dati precedenti conservati.")
        batches=st.session_state.get(STATE,[])
        if batches:
            st.caption(f"{len(batches)} acquisizioni · timestamp importati non autenticati.")
            st.download_button("Esporta storico JSON",json.dumps({"version":1,"batches":batches},allow_nan=False),"igor-terna-forward.json","application/json",key="terna_forward_export")
    result=outlook(st.session_state,utc_now())
    if result:
        st.caption("Acquisito "+result["acquired"]+" · previsioni, non misure")
        f=pd.DataFrame(result["points"]).set_index("day")
        f=f.rename(columns={"load":"Carico previsto","wind":"Eolico previsto","load_minus_wind_gwh":"Carico meno eolico"})
        st.line_chart(f,y_label="GWh elettrici/giorno gas")
        st.dataframe(f, width="stretch")
    elif batches:
        st.caption("Nessuna previsione recente completa per singola metrica. Consulta le acquisizioni storiche nell’archivio.")
        with st.expander("Ultima acquisizione"):
            st.dataframe(batches[-1]["rows"],hide_index=True,width="stretch")
    else:st.caption("Acquisisci le previsioni per alimentare l’archivio e il modello Snam.")
    st.caption("Carico meno eolico = proxy parziale; non domanda di gas né residual load completo. Nessuna imputazione di zone mancanti.")
