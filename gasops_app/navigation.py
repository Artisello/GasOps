"""Native Streamlit navigation with an independent overview entry."""
import streamlit as st

GROUPS=(
    ("Mercato",(1,2)),
    ("Operazioni",(3,4)),
    ("Analisi e strumenti",(5,6,7)),
)


def sidebar_navigation(pages,current):
    """Use real page links; explicitly mark the current route in CSS."""
    def link(index):
        page=pages[index]
        active=page.url_path==current.url_path
        name="home" if index==0 else f"item_{index}"
        state="active" if active else "idle"
        with st.container(key=f"gas_nav_{name}_{state}"):
            st.page_link(page)

    link(0)
    for label,indices in GROUPS:
        st.html(f'<div class="gas-nav-group">{label}</div>')
        for index in indices:
            link(index)
