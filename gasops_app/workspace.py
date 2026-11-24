"""Task-oriented entry points. Navigation never changes imported evidence."""
from html import escape

import streamlit as st

from .visuals import chip

INTENT = "bso_workspace_intent"
INTENTS = {
    "balancing": ("balancing", {"balancing_view": "Cockpit", "cockpit_context":"SYSTEM VIEW"}),
    "settlement": ("balancing", {"balancing_view": "Controllo giornaliero",
                                  "balancing_daily_mode": "Settlement e rettifiche",
                                  "daily_desk_data_mode": "Dati importati", "daily_desk_section": "Giornate"}),
    "settlement_example": ("balancing", {"balancing_view": "Controllo giornaliero",
                                          "balancing_daily_mode": "Settlement e rettifiche",
                                          "daily_desk_data_mode": "Esempio guidato", "daily_desk_section": "Giornate"}),
    "operations": ("kpi", {"bso_view": "Registro operativo", "bso_mode": "Dati importati",
                            "bso_register_section": "Scadenze", "bso_task_filter": "Priorità"}),
}
TASKS = (
    ("balancing", "Bilanciamento", "Flussi, nomine e pubblicazioni del giorno gas.", ":material/balance:"),
    ("settlement", "Settlement", "Bilanci mensili, rettifiche e importi da verificare.", ":material/receipt_long:"),
    ("operations", "Operazioni gas", "Attività aperte e scadenze dei prossimi giorni.", ":material/event_available:"),
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
        if intent == "balancing":
            from .system_status_page import SELECTED_DAY
            day = st.session_state.get(SELECTED_DAY)
            if day is not None:
                st.session_state["cockpit_focus_day"] = day


def open_workspace(intent):
    target, _ = INTENTS[intent]
    st.session_state[INTENT] = intent
    if target == "balancing":
        from .workbench import balancing
        page = st.Page(balancing, title="Bilanciamento", icon=":material/balance:", url_path="balancing")
    else:
        from .bso_kpi_page import page as kpis
        page = st.Page(kpis, title="Operazioni gas", icon=":material/monitoring:", url_path="kpi")
    st.switch_page(page)


def _availability(key):
    names = {"balancing": ("jarvis_public_snapshot_v1", "versions"),
             "settlement": ("settlement_desk_csv_v1", "rows"),
             "operations": ("bso_tasks_v1", "tasks")}
    state, field = names[key]
    saved = st.session_state.get(state)
    count = len(saved.get(field, ())) if saved else 0
    if key == "balancing":
        return ("Dati pubblici e stime importate" if count else "Dati pubblici", "historical")
    if count:
        noun = ("attività importata" if count == 1 else "attività importate") if key == "operations" else (
            "versione importata" if count == 1 else "versioni importate")
        return f"{count} {noun}", "ok"
    return "CSV o esempio", ""


def render(*, show_example=True):
    with st.container(key="bso_workspaces"):
        for col, task in zip(st.columns(3, gap="small"), TASKS, strict=True):
            key, title, description, icon = task
            status, tone = _availability(key)
            with col, st.container(border=True, key="bso_launch_" + key):
                st.button(title, key="workspace_open_" + key, icon=icon, width="stretch",
                          on_click=open_workspace, args=(key,))
                st.html(f'<div class="gas-task"><p>{escape(description)}</p>{chip(status, tone)}</div>')
    if show_example:
        getting_started()


def getting_started():
    st.button("Prova un esempio di settlement", key="workspace_example",
              icon=":material/play_arrow:", on_click=open_workspace, args=("settlement_example",))
    with st.expander("Quale strumento usare?"):
        from .bso_reference import render_terms
        st.markdown("**Sistema gas** per le stime aggregate della rete. **Bilanci e rettifiche** per il saldo del partecipante. "
                    "**Fatture e garanzie** per confronti documentali e credito. **Operazioni gas** per attività e scadenze.")
        st.caption("Le stime del sistema e i bilanci individuali hanno perimetri diversi: non sono intercambiabili.")
        st.markdown("**SAS**: sbilanciamento atteso del sistema. **DS**: sbilanciamento del partecipante. "
                    "**MWh e GWh** misurano energia: 1 GWh = 1.000 MWh.")
        st.markdown("Dal menu trovi anche previsioni, stoccaggi, scenari di rischio, ricerca nei documenti e assistente.")
        render_terms("home", "bso_home_term")
        st.caption("Esporta i file della sessione per conservarli.")


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
