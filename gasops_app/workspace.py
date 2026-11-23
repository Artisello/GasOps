"""Task-oriented entry points. Navigation never changes imported evidence."""
from html import escape

import streamlit as st

from .gas_calendar import closed_gas_day
from .italiano import data_it
from .models import utc_now
from .visuals import chip

INTENT = "bso_workspace_intent"
INTENTS = {
    "balancing": ("balancing", {"balancing_view": "Cockpit", "cockpit_context":"SYSTEM VIEW"}),
    "settlement": ("balancing", {"balancing_view": "Controllo giornaliero",
                                  "balancing_daily_mode": "Settlement e rettifiche",
                                  "daily_desk_data_mode": "Dati importati"}),
    "settlement_example": ("balancing", {"balancing_view": "Controllo giornaliero",
                                          "balancing_daily_mode": "Settlement e rettifiche",
                                          "daily_desk_data_mode": "Esempio guidato"}),
    "operations": ("kpi", {"bso_view": "Registro operativo", "bso_mode": "Dati importati",
                            "bso_register_section": "Scadenze"}),
}
TASKS = (
    ("balancing", "Bilanciamento", "Sistema gas", "Segui le stime del sistema e confronta le pubblicazioni.",
     "Osservazioni pubbliche già disponibili", "Giorno gas, confronti per punto e revisioni", "Apri il sistema gas"),
    ("settlement", "Settlement", "Bilanci e rettifiche", "Controlla le giornate del mese e individua gli importi da verificare.",
     "Bilanci e prezzi di sbilanciamento in CSV", "Eccezioni, rettifiche e controllo esportabile", "Controlla i bilanci"),
    ("operations", "Operations", "Attività e scadenze", "Trova le attività in ritardo e quelle in scadenza.",
     "Registro attività con date e completamenti", "Agenda delle priorità e indicatori di puntualità", "Apri le attività"),
)


def picker(label, options, *, key, labels=None, index=0):
    """One native, keyboard-accessible navigation style; values stay stable."""
    with st.container(key="workspace_nav_"+key):
        return st.radio(label,options,key=key,index=index,horizontal=True,label_visibility="collapsed",
                        format_func=(lambda value:labels.get(value,value)) if labels else str)


def apply_intent(page):
    """Consume only a request for this page, before its widgets are created."""
    intent = st.session_state.get(INTENT)
    if not isinstance(intent, str) or intent not in INTENTS:
        st.session_state.pop(INTENT, None)
        return
    target, values = INTENTS[intent]
    if target == page:
        st.session_state.pop(INTENT, None)
        st.session_state.update(values)


def open_workspace(intent):
    target, _ = INTENTS[intent]
    st.session_state[INTENT] = intent
    if target == "balancing":
        from .workbench import balancing
        page = st.Page(balancing, title="Bilanciamento", icon=":material/balance:", url_path="balancing")
    else:
        from .bso_kpi_page import page as kpis
        page = st.Page(kpis, title="KPI operativi", icon=":material/monitoring:", url_path="kpi")
    st.switch_page(page)


def _availability(key):
    names = {"balancing": ("jarvis_public_snapshot_v1", "versions"),
             "settlement": ("settlement_desk_csv_v1", "rows"),
             "operations": ("bso_tasks_v1", "tasks")}
    state, field = names[key]
    saved = st.session_state.get(state)
    count = len(saved.get(field, ())) if saved else 0
    noun = ("attività importata" if count == 1 else "attività importate") if key == "operations" else (
        "versione importata" if count == 1 else "versioni importate")
    return (f"{count} {noun}", "historical") if count else ("Dati da caricare", "")


def render():
    day = closed_gas_day(utc_now())
    st.html('<div class="gas-desk-context"><span>Ultimo giorno gas concluso '
            f'<strong>{escape(data_it(day))}</strong></span>'
            '<span>Dati pubblici e file della sessione</span></div>')
    with st.container(key="bso_workspaces"):
        for col, task in zip(st.columns(3, gap="medium"), TASKS, strict=True):
            key, title, label, description, needs, result, action = task
            status, tone = _availability(key)
            with col, st.container(border=True, key="bso_launch_" + key):
                st.html(f'<article class="gas-task"><span class="gas-task-label">{escape(label)}</span>'
                        f'<h2>{escape(title)}</h2><p>{escape(description)}</p>'
                        f'<dl><dt>Ti serve</dt><dd>{escape(needs)}</dd>'
                        f'<dt>Ottieni</dt><dd>{escape(result)}</dd></dl>'
                        f'{chip(status, tone)}</article>')
                if st.button(action, key="workspace_open_" + key, icon=":material/arrow_forward:", width="stretch"):
                    open_workspace(key)
    with st.container(border=True, key="bso_example"):
        text, action = st.columns([2.4, 1], vertical_alignment="center")
        with text:
            st.markdown("**Scopri il flusso con un esempio guidato**")
            st.caption("30 giorni di bilancio, una rettifica da esaminare e un controllo da esportare. Dati sintetici, separati dai tuoi file.")
        with action:
            if st.button("Prova il settlement", key="workspace_example", type="primary",
                         icon=":material/play_arrow:", width="stretch"):
                open_workspace("settlement_example")
    with st.expander("Quale strumento usare?"):
        from .bso_reference import render_terms
        st.markdown("**Sistema gas** per le stime aggregate della rete. **Bilanci e rettifiche** per il saldo del partecipante. "
                    "**Fatture e garanzie** per confronti documentali e credito. **KPI operativi** per attività e scadenze.")
        st.caption("Le stime del sistema e i bilanci individuali hanno perimetri diversi: non sono intercambiabili.")
        st.markdown("**SAS**: sbilanciamento atteso del sistema. **DS**: sbilanciamento del partecipante. "
                    "**MWh e GWh** misurano energia: 1 GWh = 1.000 MWh.")
        st.markdown("Dal menu trovi anche previsioni, stoccaggi, scenari di rischio, ricerca nei documenti e assistente.")
        render_terms("home", "bso_home_term")
    st.caption("I file importati restano nella sessione: esportali per conservarli. Nessun invio a portali operativi.")


def guide(key):
    instructions = {
        "system": ("Importa le pubblicazioni Jarvis nel modello CSV indicato.",
                   "Scegli il giorno gas e confronta SAS, prelievi e versioni.",
                   "Verifica la data della pubblicazione ed esporta lo storico."),
        "settlement": ("Importa bilanci e prezzi, oppure scegli l’esempio guidato.",
                       "Leggi le eccezioni e confronta le rettifiche della giornata.",
                       "Esporta il controllo e il registro completo per la verifica."),
        "operations": ("Importa il registro delle attività, oppure seleziona Demo.",
                       "Scegli area e mese: parti dalle attività scadute e prossime.",
                       "Esporta l’agenda; il calendario pubblico Snam resta un riferimento separato."),
    }
    with st.expander("Come usare questa vista"):
        from .bso_reference import render_terms
        for number, text in enumerate(instructions[key], 1):
            st.markdown(f"**{number}.** {text}")
        render_terms(key, "bso_guide_term_" + key)
