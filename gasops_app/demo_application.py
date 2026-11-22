"""Ready entry points without removing any of the application's feature routes."""
import streamlit as st

from . import session


def prepare(route):
    state=st.session_state
    if "selected_source" not in state:
        state["selected_source"]=session.ARCHIVE
    if "execution_mode" not in state:
        try:config=session._configuration()
        except ValueError:config=None
        state["execution_mode"]=config.model if config else "Deterministic"
    if route=="balancing":
        state.setdefault("balancing_view","Controllo giornaliero")
        state.setdefault("daily_desk_data_mode","Esempio guidato")
        state.setdefault("daily_desk_filter","Rettifiche")
    elif route=="security-of-supply" and "operational_platform" not in state:
        from .operational_sources_page import configured_key
        try:key=configured_key()
        except (ValueError,KeyError,FileNotFoundError):key=None
        state["operational_platform"]="AGSI+" if key else "MASE"
    elif route=="kpi":
        state.setdefault("bso_view","Registro operativo")
        state.setdefault("bso_mode","Demo")
    elif route=="operations":
        _prepare_assistant()


def _prepare_assistant():
    """Only public JRC inputs; never include visitor PDFs or imported records."""
    from .assistant_page import HISTORY,SELECTED
    if st.session_state.get("demo_assistant_prepared_v1"):return
    st.session_state["demo_assistant_prepared_v1"]=True
    if st.session_state.get(HISTORY):return
    from .agents import Assumptions,MarketContext
    from .models import utc_now
    from .regulatory import Library
    from .workflow import run_workflow
    model=session.reasoner()
    bundle=session.archive()
    question="Come è cambiata la domanda di gas e qual è la previsione sui dati storici JRC?"
    with st.spinner("Preparazione dell’analisi pubblica…"):
        report=run_workflow(MarketContext(bundle,session.assumptions().model,utc_now()),
                            Library(include_notes=False),Assumptions(),question,
                            reasoner=model,planned_only=True)
    st.session_state[HISTORY]=[report]
    st.session_state[SELECTED]=report.id
    st.session_state.setdefault("assistant_view","Assistente operativo" if model else "Report locali")


def risk():
    from .risk_page import risk_page
    risk_page(auto_demo=True)


def regulatory():
    from .document_page import document_page
    document_page(ready_example=True)


def examples():
    from .presentation import page
    page()


def connections():
    from .connections_page import page
    page()
