"""Streamlit entry point for the I.G.O.R. desktop dashboard."""

from pathlib import Path
from importlib import import_module

import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent

st.set_page_config(
    page_title="I.G.O.R.",
    page_icon=":material/monitoring:",
    layout="wide",
    initial_sidebar_state="auto",
)
load_dotenv(ROOT / ".env", override=False)
st.html(ROOT / "gasops_app" / "theme.css")


def demo_home():
    # Keep this callback in the rerun entry point. A running Cloud process may
    # still hold the earlier presentation module without its newer home alias.
    from gasops_app.presentation import _overview

    with st.container(key="demo_content"):
        _overview(None)


def application(demo=True):
    """One reachable application tree, with ready examples in the default view."""
    from gasops_app.access import guard_application
    guard_application()
    from gasops_app.navigation import sidebar_navigation
    from gasops_app import demo_application

    def lazy(module, function):
        def render():
            getattr(import_module("gasops_app." + module), function)()
        return render

    pages = [
        st.Page(demo_home if demo else lazy("dashboard", "overview"), title="Panoramica", icon=":material/home:", default=True),
        st.Page(lazy("dashboard", "market"), title="Mercato e previsioni", icon=":material/monitoring:", url_path="market"),
        st.Page(lazy("operational_sources_page", "operational_context"), title="Security of Supply", icon=":material/shield:", url_path="security-of-supply"),
        st.Page(lazy("workbench", "balancing"), title="Bilanciamento", icon=":material/balance:", url_path="balancing"),
        st.Page(lazy("operations_page", "operations_ledger"), title="Fatture e garanzie", icon=":material/receipt_long:", url_path="ledger"),
        st.Page(demo_application.risk if demo else lazy("risk_page", "risk_page"), title="Simulazione rischi", icon=":material/query_stats:", url_path="risk"),
        st.Page(demo_application.regulatory if demo else lazy("workbench", "regulatory"), title="Norme e documenti", icon=":material/menu_book:", url_path="regulatory"),
        st.Page(lazy("workbench", "operations"), title="Assistente AI", icon=":material/hub:", url_path="operations"),
        st.Page(lazy("bso_kpi_page", "page"), title="Operazioni gas", icon=":material/monitoring:", url_path="kpi"),
    ]
    if demo:
        pages.extend([
            st.Page(demo_application.connections, title="Fonti e API", icon=":material/cable:", url_path="connections"),
            st.Page(demo_application.examples, title="Esempi BSO", icon=":material/auto_awesome:", url_path="demo"),
        ])
    current = st.navigation(pages, position="hidden")
    with st.sidebar:
        st.html("""
        <div class="gas-brand">
          <div class="gas-mark" aria-hidden="true"><span></span><span></span><span></span></div>
          <div><strong>I.G.O.R.</strong><small>Intelligent Gas Operations &amp; Risk</small></div>
        </div>
        """)
        sidebar_navigation(pages, current)
        if not demo:
            from gasops_app import session
            st.html('<div class="gas-nav-group gas-nav-settings">Analisi</div>')
            session.sidebar()
        else:
            st.caption("Fonti pubbliche · esempi separati")
        st.html('<div class="gas-byline"><strong>Prototipo per Snam · creato da Igor</strong><small>Progetto indipendente, non ufficiale.</small></div>')
    if demo:
        demo_application.prepare(current.url_path)
    elif current.url_path=="kpi":
        st.session_state.setdefault("bso_view","Registro operativo")
    current.run()


from gasops_app.access import demo_layout
application(demo=demo_layout())
