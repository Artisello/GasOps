"""Streamlit entry point for the GasOps AI desktop dashboard."""

from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent

st.set_page_config(
    page_title="GasOps AI",
    page_icon=":material/monitoring:",
    layout="wide",
    initial_sidebar_state="auto",
)
load_dotenv(ROOT / ".env", override=False)
st.html(ROOT / "gasops_app" / "theme.css")

from gasops_app import dashboard, session, workbench, operations_page, risk_page, operational_sources_page
from gasops_app.navigation import sidebar_navigation

pages = [
    st.Page(dashboard.overview, title="Panoramica", icon=":material/home:", default=True),
    st.Page(dashboard.market, title="Mercato e previsioni", icon=":material/monitoring:", url_path="market"),
    st.Page(operational_sources_page.operational_context, title="Stoccaggi e forniture", icon=":material/shield:", url_path="security-of-supply"),
    st.Page(workbench.balancing, title="Bilanciamento", icon=":material/balance:", url_path="balancing"),
    st.Page(operations_page.operations_ledger, title="Fatture e garanzie", icon=":material/receipt_long:", url_path="ledger"),
    st.Page(risk_page.risk_page, title="Simulazione rischi", icon=":material/query_stats:", url_path="risk"),
    st.Page(workbench.regulatory, title="Norme e documenti", icon=":material/menu_book:", url_path="regulatory"),
    st.Page(workbench.operations, title="Assistente AI", icon=":material/hub:", url_path="operations"),
]
current = st.navigation(pages, position="hidden")
with st.sidebar:
    st.html("""
        <div class="gas-brand">
          <div class="gas-mark"><span></span><span></span><span></span></div>
          <div><strong>GasOps <em>AI</em></strong><small>Mercato del gas</small></div>
        </div>
    """)
    sidebar_navigation(pages, current)
    st.html('<div class="gas-nav-group gas-nav-settings">Impostazioni AI</div>')
    session.sidebar()
    st.html('<div class="gas-byline"><strong>Prototipo per SNAM creato da Igor</strong><small>Progetto indipendente, non ufficiale.</small></div>')
current.run()
