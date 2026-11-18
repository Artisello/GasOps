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

from gasops_app import dashboard, session, workbench, operations_page, risk_page

pages = [
    st.Page(dashboard.overview, title="Panoramica", icon=":material/grid_view:", default=True),
    st.Page(dashboard.market, title="Mercato e previsioni", icon=":material/monitoring:", url_path="market"),
    st.Page(workbench.balancing, title="Bilanciamento", icon=":material/balance:", url_path="balancing"),
    st.Page(operations_page.operations_ledger, title="Registro operativo", icon=":material/receipt_long:", url_path="ledger"),
    st.Page(risk_page.risk_page, title="Rischio probabilistico", icon=":material/query_stats:", url_path="risk"),
    st.Page(workbench.regulatory, title="Analisi normativa", icon=":material/menu_book:", url_path="regulatory"),
    st.Page(workbench.operations, title="Centro operativo AI", icon=":material/hub:", url_path="operations"),
]
current = st.navigation(pages, position="hidden")
with st.sidebar:
    st.html("""
        <div class="gas-brand">
          <div class="gas-mark"><span></span><span></span><span></span></div>
          <div><strong>GasOps <em>AI</em></strong><small>Mercato del gas</small></div>
        </div>
    """)
    for page in pages:
        st.page_link(page)
    session.sidebar()
current.run()
