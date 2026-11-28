"""Display progress and refresh the page when shared evidence becomes available."""
import streamlit as st

from .freshness import timestamp
from .operational_acquisition import NAMES, journal
from .visuals import local_time


def watch(store, job, connections, *, on_done=None):
    if job is None:
        return

    @st.fragment(run_every=4)
    def progress():
        if job.done() and job.exception():
            st.caption("Aggiornamento interrotto · ultime copie valide, se disponibili.")
        elif job.done():
            if on_done:
                on_done(job.result())
            st.rerun()
        elif journal(store).get("connections",{}) != connections:
            st.rerun()
        else:
            st.caption("Fonti in aggiornamento…")

    progress()


def connection_status(connections, *, gie):
    for source,label in NAMES.items():
        status = connections.get(source)
        if source in ("agsi","alsi") and not gie:
            detail = "Chiave API assente"
        elif not status:
            detail = "In attesa di verifica"
        else:
            good, expected = status["valid"], status["expected"]
            connection = ("Risposta verificata" if good==expected and not status.get("partial") else
                          "Risposta parziale" if good else "Aggiornamento non riuscito")
            detail = f"{connection} · {good}/{expected} richieste · {local_time(timestamp(status['at']))}"
        st.caption(label+" · "+detail)
