"""Ready entry points without removing any of the application's feature routes."""
import streamlit as st



def prepare(route):
    from . import session
    state=st.session_state
    if "selected_source" not in state:
        state["selected_source"]=session.ARCHIVE
    if "execution_mode" not in state:
        state["execution_mode"]="Deterministic"
    if route=="balancing":
        state.setdefault("balancing_view","Cockpit")
        register=state.get("settlement_desk_csv_v1",{})
        imported=register.get("authorized") is True and register.get("origin")=="user_upload" and bool(register.get("rows"))
        state.setdefault("daily_desk_data_mode","Dati importati" if imported else "Esempio guidato")
    elif route=="security-of-supply" and "operational_platform" not in state:
        state["operational_platform"]="MAP"
    elif route=="kpi":
        state.setdefault("bso_view","Registro operativo")
        tasks=state.get("bso_tasks_v1",{}).get("tasks")
        state.setdefault("bso_mode","Dati importati" if tasks else "Demo")
    elif route=="operations":
        _prepare_assistant()


def _prepare_assistant():
    """Prepare controls only. Reports and AI calls require an explicit action."""
    from .assistant_page import HISTORY
    if st.session_state.get("demo_assistant_prepared_v1"):return
    st.session_state["demo_assistant_prepared_v1"]=True
    if st.session_state.get(HISTORY):return
    st.session_state.setdefault(HISTORY,[])
    st.session_state.setdefault("assistant_view","Report locali")


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
