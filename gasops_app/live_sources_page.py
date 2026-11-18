"""Single explicit refresh surface for BSO and data analyst."""
import streamlit as st
from .models import utc_now
from .session import database
from .operational_sources_page import configured_key
from .terna_power import credentials
from .live_sources import refresh,STATUS,LABELS
from .weather_source import enabled


def controls(prefix):
    state=st.session_state
    now=utc_now()
    with st.expander("Aggiorna fonti reali",expanded=not bool(state.get(STATUS)) and not bool(state.get("live_public_bundles_v1"))):
        st.caption("Seleziona le fonti autorizzate. I risultati alimentano anche l’Analista dati nella stessa sessione.")
        try:
            gie=configured_key()
        except (ValueError,KeyError,FileNotFoundError):
            gie=None
        try:
            client,secret=credentials(st.secrets)
        except (ValueError,KeyError,FileNotFoundError):
            client,secret=credentials()
        options=["monthly","daily","acer"]+(["weather"] if enabled(state) else [])
        if gie:options+=["agsi","alsi"]
        if client and secret:options+=["terna"]
        selected=st.multiselect("Fonti",options,default=["monthly"]+(["terna"] if "terna" in options else [])+(["weather"] if "weather" in options else []),format_func=LABELS.__getitem__,key=prefix+"_live_sources")
        consent=st.checkbox("Confermo uso autorizzato e termini delle fonti selezionate; per Terna accetto l’assunzione sperimentale di inizio intervallo 06–06.",key=prefix+"_live_consent")
        if st.button("Aggiorna selezione",type="primary",key=prefix+"_live_refresh",disabled=not selected or not consent):
            with st.spinner("Aggiornamento delle fonti selezionate…"):
                ok=refresh(state,database(),now,selected,gie=gie,terna=(client,secret) if client and secret else None)
            if not ok:st.caption("Aggiornamento già richiesto nell’ultimo minuto.")
        saved=state.get(STATUS,{})
        if saved.get("sources"):
            st.dataframe([{"Fonte":LABELS[k], "Stato":v["status"],"Ultimo tentativo":v["at"],"Nota":v["note"] or "Nessun rilievo"}
                          for k,v in saved["sources"].items()],hide_index=True,width="stretch")
        st.markdown("[Jarvis · importa pubblicazioni originali](/security-of-supply) · [Serie Terna e ACER](/market)")
        st.caption("Nessuna sostituzione con dati simulati. Una fonte temporaneamente indisponibile non blocca le altre.")
