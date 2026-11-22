"""Native Streamlit navigation with an independent overview entry."""
import streamlit as st

GROUPS=(
    ("Operatività",(3,4,8)),
    ("Mercato",(1,2)),
    ("Strumenti",(5,6,7)),
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
    if len(pages)>9:
        st.html('<div class="gas-nav-group">Esplora</div>')
        for index in range(9,len(pages)):
            link(index)
