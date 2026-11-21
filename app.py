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
    initial_sidebar_state="collapsed",
)
load_dotenv(ROOT / ".env", override=False)
st.html(ROOT / "gasops_app" / "theme.css")


def workbench_app():
    """Developer workbench, enabled by server configuration only."""
    from gasops_app import dashboard, session, workbench, operations_page, risk_page, operational_sources_page, bso_kpi_page
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
        st.Page(bso_kpi_page.page, title="KPI operativi", icon=":material/monitoring:", url_path="kpi"),
    ]
    current = st.navigation(pages, position="hidden")
    with st.sidebar:
        st.html("""
        <div class="gas-brand">
          <div class="gas-mark"><span></span><span></span><span></span></div>
          <div><strong>I.G.O.R.</strong><small>Intelligent Gas Operations &amp; Risk</small></div>
        </div>
        """)
        sidebar_navigation(pages, current)
        st.html('<div class="gas-nav-group gas-nav-settings">Analisi</div>')
        session.sidebar()
        st.html('<div class="gas-byline"><strong>Prototipo per Snam · creato da Igor</strong><small>Progetto indipendente, non ufficiale.</small></div>')
    current.run()


if os.environ.get("GASOPS_APP_MODE", "demo").strip().lower() == "workbench":
    workbench_app()
else:
    from gasops_app.presentation import page
    # No operational routes or configuration controls are registered in demo mode.
    st.navigation([st.Page(page, title="I.G.O.R. · Demo BSO", default=True)], position="hidden").run()
