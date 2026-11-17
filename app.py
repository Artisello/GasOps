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

from gasops_app import dashboard

pages = [
    st.Page(dashboard.overview, title="Overview", icon=":material/grid_view:", default=True),
    st.Page(dashboard.market, title="Market & Forecasting", icon=":material/monitoring:", url_path="market"),
    st.Page(dashboard.balancing, title="Balancing & Settlement", icon=":material/balance:", url_path="balancing"),
    st.Page(dashboard.regulatory, title="Regulatory Intelligence", icon=":material/menu_book:", url_path="regulatory"),
    st.Page(dashboard.operations, title="AI Operations Centre", icon=":material/hub:", url_path="operations"),
]
current = st.navigation(pages, position="hidden")
with st.sidebar:
    st.html("""
        <div class="gas-brand">
          <div class="gas-mark"><span></span><span></span><span></span></div>
          <div><strong>GasOps <em>AI</em></strong><small>Gas market operations</small></div>
        </div>
    """)
    for page in pages:
        st.page_link(page)
    dashboard.sidebar()
current.run()
