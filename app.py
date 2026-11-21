"""Streamlit entry point for the I.G.O.R. desktop dashboard."""

from pathlib import Path
import os

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


def application(demo=True):
    """One reachable application tree, with ready examples in the default view."""
    from gasops_app import dashboard, session, workbench, operations_page, risk_page, operational_sources_page, bso_kpi_page
    from gasops_app.navigation import sidebar_navigation
    from gasops_app import demo_application

    pages = [
        st.Page(demo_application.home if demo else dashboard.overview, title="Panoramica", icon=":material/home:", default=True),
        st.Page(dashboard.market, title="Mercato e previsioni", icon=":material/monitoring:", url_path="market"),
        st.Page(operational_sources_page.operational_context, title="Security of Supply", icon=":material/shield:", url_path="security-of-supply"),
        st.Page(workbench.balancing, title="Bilanciamento", icon=":material/balance:", url_path="balancing"),
        st.Page(operations_page.operations_ledger, title="Fatture e garanzie", icon=":material/receipt_long:", url_path="ledger"),
        st.Page(demo_application.risk if demo else risk_page.risk_page, title="Simulazione rischi", icon=":material/query_stats:", url_path="risk"),
        st.Page(demo_application.regulatory if demo else workbench.regulatory, title="Norme e documenti", icon=":material/menu_book:", url_path="regulatory"),
        st.Page(workbench.operations, title="Assistente AI", icon=":material/hub:", url_path="operations"),
        st.Page(bso_kpi_page.page, title="KPI operativi", icon=":material/monitoring:", url_path="kpi"),
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
          <div class="gas-mark"><span></span><span></span><span></span></div>
          <div><strong>I.G.O.R.</strong><small>Intelligent Gas Operations &amp; Risk</small></div>
        </div>
        """)
        sidebar_navigation(pages, current)
        if not demo:
            st.html('<div class="gas-nav-group gas-nav-settings">Analisi</div>')
            session.sidebar()
        else:
            st.caption("Demo esplorabile · fonti pubbliche ed esempi dichiarati")
        st.html('<div class="gas-byline"><strong>Prototipo per Snam · creato da Igor</strong><small>Progetto indipendente, non ufficiale.</small></div>')
    if demo:
        demo_application.prepare(current.url_path)
    current.run()


application(demo=os.environ.get("GASOPS_APP_MODE", "demo").strip().lower() != "workbench")
