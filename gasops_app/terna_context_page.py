"""Compact public Terna context view with portable vintages."""
from datetime import timedelta
import json
import pandas as pd
import streamlit as st
from .terna_charts import acquisition_label, timeseries
from .visuals import plot, info
from .italiano import numero
from .data import ROME
from .models import utc_now
from .terna_power import credentials,PORTAL
from .terna_context import STATE,ATTEMPT,SELECT,MAX_BYTES,DOCS,UNITS,acquire,merge,scopes,latest_rows,import_exchange,exchange_payload
from .public_data import SourceUnavailable

LABELS={"capacity":"Capacità disponibile prevista","industry":"Consumi industriali · IMCEI","exchange":"Scambi esteri programmati"}

def panel():
    now=utc_now();today=now.astimezone(ROME).date();state=st.session_state
    kind=st.radio("Indicatore",list(LABELS),format_func=LABELS.__getitem__,horizontal=True,key="terna_context_kind")
    info("Fonte e metodo","Serie con perimetro specifico. I dati previsti o programmati non sono consuntivi.")
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
        if kind=="capacity":st.caption("Massimo 3 giorni, fino a D+2.")
        if kind!="industry":st.caption("Timestamp = inizio intervallo (ipotesi sperimentale).")
        submit=st.form_submit_button("Importa scambi" if kind=="exchange" else "Aggiorna dati",disabled=kind!="exchange" and not bool(client and secret))
    if kind!="exchange" and not (client and secret):st.caption("Credenziali Terna non configurate; ripristina un archivio autorizzato.")
    if submit:
        previous=state.get(ATTEMPT)
        if kind!="industry" and (last<first or (kind=="capacity" and (last-first).days>=3)):
            st.warning("Controlla l’intervallo selezionato.")
        elif kind=="exchange" and f is None:st.warning("Seleziona un file.")
        elif previous and now-previous<timedelta(minutes=1):st.caption("Aggiornamento già richiesto nell’ultimo minuto.")
        else:
            state[ATTEMPT]=now
            try:
                if kind=="exchange":
                    if f.size>2_000_000:raise ValueError("File troppo grande")
                    b=import_exchange(exchange_payload(f.getvalue(),f.name),first,last,now)
                else:
                    with st.spinner("Acquisizione Terna…"):b=acquire(client,secret,kind,first,last,now)
                state[STATE]=merge(state.get(STATE,[]),[b],utc_now())
            except SourceUnavailable as error:st.warning(str(error)+" Archivio precedente invariato.")
            except (ValueError,KeyError,TypeError,OverflowError,IndexError):st.warning("Copertura non validabile o import non valido; archivio precedente invariato.")
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
        st.markdown("[Documentazione Terna]("+DOCS[kind]+") · [Portale dati]("+PORTAL+")")
        return
    scope=st.selectbox("Perimetro",options,format_func=lambda s:" · ".join(s),key="terna_context_scope_"+kind)
    state[SELECT]={**state.get(SELECT,{}),kind:scope}
    rows=latest_rows(batches,kind,scope,utc_now())
    if rows:
        f=pd.DataFrame(rows);r=rows[-1]
        st.metric(LABELS[kind],numero(r["value"],2)+" "+UNITS[kind])
        st.caption("Periodo "+str(r["period"])+" · acquisito "+acquisition_label(r["acquired"])+" · "+("dato mensile pubblicato" if kind=="industry" else "previsto/programmato, non consuntivo"))
        plot(timeseries(f.set_index("period")[["value"]].rename(columns={"value":LABELS[kind]}),UNITS[kind],monthly=kind=="industry",forecast=kind!="industry"),"terna_context_"+kind)
    if kind=="industry":
        index=latest_rows(batches,kind,scope,utc_now(),"imcei")
        if index:
            st.metric("IMCEI · "+index[-1]["period"],numero(index[-1]["value"],2))
            plot(timeseries(pd.DataFrame(index).set_index("period")[["value"]].rename(columns={"value":"IMCEI"}),"Indice",monthly=True),"terna_context_imcei")
        st.caption("Regione, settore e tensione distinti; indice non sommato né interpretato come consumo di gas.")
    elif kind=="capacity":st.caption("Media oraria MW del gruppo pubblicato, impianti ≥100 MW. Non generazione effettiva né capacità totale nazionale.")
    else:st.caption("Import meno export, singolo paese; giorno gas completo. Import manuale datato all’acquisizione, non al giorno di pubblicazione.")

    with st.expander("Fonte e dati"):
        st.markdown("[Documentazione Terna]("+DOCS[kind]+") · [Portale dati]("+PORTAL+")")
        if rows:st.dataframe(pd.DataFrame(rows),hide_index=True,width="stretch")
