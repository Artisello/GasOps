"""Compact public Terna context view with portable vintages."""
from datetime import timedelta
import json
import pandas as pd
import streamlit as st
from .data import ROME
from .models import utc_now
from .terna_power import credentials,PORTAL
from .terna_context import STATE,ATTEMPT,SELECT,MAX_BYTES,DOCS,UNITS,acquire,merge,scopes,latest_rows,import_exchange,exchange_payload
from .public_data import SourceUnavailable

LABELS={"capacity":"Capacità disponibile prevista","industry":"Consumi industriali · IMCEI","exchange":"Scambi esteri programmati"}

def panel():
    now=utc_now();today=now.astimezone(ROME).date();state=st.session_state
    kind=st.radio("Indicatore",list(LABELS),format_func=LABELS.__getitem__,horizontal=True,key="terna_context_kind")
    st.markdown("[Documentazione Terna]("+DOCS[kind]+") · [Portale dati]("+PORTAL+")")
    try:client,secret=credentials(st.secrets)
    except (ValueError,KeyError,FileNotFoundError):client,secret=credentials()
    with st.form("terna_context_request_"+kind):
        if kind=="industry":
            last=first=st.date_input("Mese di riferimento",value=(today.replace(day=1)-timedelta(days=1)).replace(day=1),max_value=today.replace(day=1)-timedelta(days=1)).replace(day=1)
        else:
            a,b=st.columns(2)
            first=a.date_input("Dal giorno gas",value=today,max_value=today+timedelta(days=2))
            last=b.date_input("Al giorno gas",value=today+timedelta(days=1),max_value=today+timedelta(days=2))
        f=st.file_uploader("JSON documentato o CSV con intestazioni normalizzate",type=["json","csv"]) if kind=="exchange" else None
        st.caption("Dati pubblici · timestamp orari = inizio intervallo (ipotesi sperimentale).")
        submit=st.form_submit_button("Importa scambi" if kind=="exchange" else "Aggiorna dati",disabled=not (f if kind=="exchange" else client and secret))
    if kind!="exchange" and not (client and secret):st.caption("Credenziali Terna non configurate; ripristina un archivio autorizzato.")
    if submit:
        previous=state.get(ATTEMPT)
        if previous and now-previous<timedelta(minutes=1):st.caption("Aggiornamento già richiesto nell’ultimo minuto.")
        else:
            state[ATTEMPT]=now
            try:
                if kind=="exchange":
                    if f.size>2_000_000:raise ValueError("File troppo grande")
                    b=import_exchange(exchange_payload(f.getvalue(),f.name),first,last,now)
                else:
                    with st.spinner("Acquisizione Terna…"):b=acquire(client,secret,kind,first,last,now)
                state[STATE]=merge(state.get(STATE,[]),[b],utc_now())
            except (ValueError,SourceUnavailable,KeyError,TypeError,OverflowError,IndexError):st.caption("Copertura non disponibile o import non valido; archivio precedente invariato.")
    with st.expander("Archivio versionato"):
        f=st.file_uploader("Ripristina archivio I.G.O.R.",type=["json"],key="terna_context_archive")
        st.caption("JSON pubblico · timestamp dichiarati, non autenticati.")
        if st.button("Unisci archivio",disabled=f is None,key="terna_context_import"):
            try:
                if f.size>MAX_BYTES:raise ValueError("Limite")
                obj=json.loads(f.getvalue())
                if obj["version"]!=1:raise ValueError("Versione")
                state[STATE]=merge(state.get(STATE,[]),obj["batches"],now)
            except (ValueError,KeyError,TypeError,OverflowError):st.caption("Archivio non valido; dati precedenti conservati.")
        batches=state.get(STATE,[])
        if batches:
            st.caption(f"{len(batches)} acquisizioni · timestamp importati dichiarati, non autenticati.")
            st.download_button("Esporta JSON",json.dumps({"version":1,"batches":batches},allow_nan=False),"igor-terna-context.json","application/json")
    options=scopes(batches,kind)
    if not options:
        st.caption("Acquisisci una pubblicazione per esplorare le serie disponibili.")
        return
    scope=st.selectbox("Perimetro",options,format_func=lambda s:" · ".join(s),key="terna_context_scope_"+kind)
    state[SELECT]={**state.get(SELECT,{}),kind:scope}
    rows=latest_rows(batches,kind,scope,utc_now())
    if rows:
        f=pd.DataFrame(rows);r=rows[-1]
        st.metric(LABELS[kind]+" · "+r["period"],f'{r["value"]:,.2f} {UNITS[kind]}')
        st.caption("Acquisito "+r["acquired"]+" · "+("dato mensile pubblicato" if kind=="industry" else "previsto/programmato, non consuntivo"))
        st.line_chart(f,x="period",y="value",y_label=UNITS[kind])
    if kind=="industry":
        index=latest_rows(batches,kind,scope,utc_now(),"imcei")
        if index:
            st.metric("IMCEI · "+index[-1]["period"],f'{index[-1]["value"]:,.2f}')
            st.line_chart(pd.DataFrame(index),x="period",y="value",y_label="Indice IMCEI")
        st.caption("Regione, settore e tensione distinti; indice non sommato né interpretato come consumo di gas.")
    elif kind=="capacity":st.caption("Media oraria MW del gruppo pubblicato, impianti ≥100 MW. Non generazione effettiva né capacità totale nazionale.")
    else:st.caption("Import meno export, singolo paese; giorno gas completo. Import manuale datato all’acquisizione, non al giorno di pubblicazione.")
