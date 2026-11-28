"""Native Streamlit navigation with an independent overview entry."""
import streamlit as st

GROUPS=(
    ("Operatività",("security-of-supply","balancing","ledger","kpi")),
    ("Analisi",("market","risk")),
    ("Strumenti",("regulatory","operations","connections","demo")),
)
LABELS={"security-of-supply":"Rete e forniture",
        "balancing":"Bilanciamento",
        "connections":"Fonti e API","demo":"Esempi guidati","kpi":"Attività e indicatori"}
HINTS={"":"Mappa della rete, flussi e avvisi.","balancing":"Confronta quantità programmate e misurate; verifica i saldi.",
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
        name="home" if page.url_path=="" else f"item_{index}"
        state="active" if active else "idle"
        with st.container(key=f"gas_nav_{name}_{state}"):
            st.page_link(page,**({"label":LABELS[page.url_path]} if page.url_path in LABELS else {}),
                         help=HINTS.get(page.url_path))

    by_route = {page.url_path:index for index,page in enumerate(pages)}
    if "" in by_route:
        link(by_route[""])
    shown = {""}
    for label,routes in GROUPS:
        available = [route for route in routes if route in by_route]
        if not available:
            continue
        st.html(f'<div class="gas-nav-group">{label}</div>')
        for route in available:
            link(by_route[route])
            shown.add(route)
    # New routes remain discoverable until explicitly assigned a group.
    remaining = [route for route in by_route if route not in shown]
    if remaining:
        st.html('<div class="gas-nav-group">Altre funzioni</div>')
        for route in remaining:
            link(by_route[route])
