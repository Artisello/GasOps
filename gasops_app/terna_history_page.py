"""Portable history controls, no shared app persistence."""
import streamlit as st
from .models import utc_now
from .terna_history import STATE,MAX_BYTES,export,parse,merge,summary


def panel():
    archive=st.session_state.get(STATE,[])
    st.markdown("**Archivio storico Terna**")
    st.caption("Ogni nuova acquisizione autorizzata aggiunge giorni e versioni alla sessione. Esporta il JSON per conservarlo e reimportarlo.")
    with st.expander("Ripristina / esporta archivio",expanded=False):
        with st.form("terna_history_import"):
            f=st.file_uploader("Archivio normalizzato I.G.O.R. (JSON)",type=["json"],key="terna_hist_file")
            consent=st.checkbox("Confermo dati autorizzati e timestamp dichiarati corretti.")
            submit=st.form_submit_button("Unisci archivio")
        if submit:
            try:
                if f is None or not consent or f.size>MAX_BYTES:raise ValueError("Input mancante")
                archive=merge(archive,parse(f.getvalue(),utc_now()))
                st.session_state[STATE]=archive
                st.success("Archivio unito.")
            except (ValueError,TypeError,KeyError,OverflowError):
                st.error("Archivio non valido o limite raggiunto; dati precedenti conservati.")
        if archive:
            st.download_button("Scarica storico Terna",export(archive),"igor-terna-history.json","application/json",key="terna_hist_export")
            clear=st.checkbox("Ho salvato lo storico e confermo la rimozione.",key="terna_hist_clear_confirm")
            if st.button("Svuota storico di sessione",disabled=not clear,key="terna_hist_clear"):
                st.session_state.pop(STATE,None)
                st.rerun()
    if archive:
        st.caption(f"{len(archive)} acquisizioni · versioni conservate · timestamp non autenticati per import JSON")
        st.dataframe(summary(archive),hide_index=True,width="stretch")
        st.markdown("[Confronto con Snam](/market)")
    else:
        st.caption("Nessun giorno archiviato. Seleziona finestre storiche nella sezione Giorni gas.")
