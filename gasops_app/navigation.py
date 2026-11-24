"""Native Streamlit navigation with an independent overview entry."""
import streamlit as st

GROUPS=(
    ("Operatività",(3,4,8)),
    ("Mercato",(1,2)),
    ("Strumenti",(5,6,7)),
)
LABELS={"security-of-supply":"Rete e forniture",
        "balancing":"Bilanciamento e settlement",
        "connections":"Fonti e connessioni","demo":"Esempi guidati"}
HINTS={"":"Azioni quotidiane, situazione del sistema e avvisi.","balancing":"Confronta flussi e nomine, verifica bilanci e rettifiche.",
       "ledger":"Esplora fatture, garanzie e scadenze con esempi dichiarati.",
       "kpi":"Segui attività, scadenze e indicatori operativi.","market":"Leggi i consumi e calcola una previsione quando serve.",
       "security-of-supply":"Esplora la rete, le scorte e i dati già disponibili.",
       "risk":"Confronta uno scenario di stress con la situazione di partenza.",
       "regulatory":"Cerca nei documenti pubblici o nei PDF della tua sessione.",
       "operations":"Genera un report o fai una domanda all’assistente.",
       "connections":"Controlla quali fonti sono configurate e verificate.","demo":"Prova il programma con esempi guidati."}


def sidebar_navigation(pages,current):
    """Use real page links; explicitly mark the current route in CSS."""
    def link(index):
        page=pages[index]
        active=page.url_path==current.url_path
        name="home" if index==0 else f"item_{index}"
        state="active" if active else "idle"
        with st.container(key=f"gas_nav_{name}_{state}"):
            st.page_link(page,**({"label":LABELS[page.url_path]} if page.url_path in LABELS else {}),
                         help=HINTS.get(page.url_path))

    link(0)
    for label,indices in GROUPS:
        st.html(f'<div class="gas-nav-group">{label}</div>')
        for index in indices:
            link(index)
    if len(pages)>9:
        st.html('<div class="gas-nav-group">Esplora</div>')
        for index in range(9,len(pages)):
            link(index)
