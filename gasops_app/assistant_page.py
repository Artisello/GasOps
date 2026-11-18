"""Session-scoped analytical assistant. No new provider or document permissions."""
import json
import logging

import streamlit as st

from .italiano import ESITI, GRAVITA, TIPI
from .models import Agent, AGENT_LABELS, Run, utc_now
from .reports import markdown
from .session import analysis_label, launch, market_scope, reasoner, source_filters
from .visuals import evidence, info, local_time, steps
from .workflow import DAILY_BRIEFING

LOG=logging.getLogger(__name__)
HISTORY="assistant_history_v1"
REVIEWS="assistant_reviews_v1"
SELECTED="assistant_selected_v1"
HISTORY_LIMIT=12
STARTERS=(
    ("Consumi","Come è cambiata la domanda di gas nell’ultimo periodo?"),
    ("Previsioni","Qual è la prossima previsione della domanda di gas?"),
    ("Stress +10%","Simula uno scenario in cui la domanda aumenta del 10%."),
)


def _remember(report):
    history=[r for r in st.session_state.get(HISTORY,[]) if r.id!=report.id]
    history=[report,*history][:HISTORY_LIMIT]
    st.session_state[HISTORY]=history
    allowed={r.id for r in history}
    st.session_state[REVIEWS]={k:v for k,v in st.session_state.get(REVIEWS,{}).items() if k in allowed}
    st.session_state[SELECTED]=report.id


def _clear():
    # Only this assistant's session history, not reports kept elsewhere.
    st.session_state.pop(HISTORY,None)
    st.session_state.pop(REVIEWS,None)
    st.session_state.pop(SELECTED,None)


def _review(report):
    notes=st.session_state.get(REVIEWS,{})
    reviewed=notes.get(report.id,{})
    queue=sorted((f for f in report.findings if f.severity!="info"),
                 key=lambda f:(f.id in reviewed,f.severity!="high"))
    if not queue:
        return reviewed
    pending=sum(f.id not in reviewed for f in queue)
    with st.expander(f"Rilievi da verificare · {pending} aperti"):
        labels={f.id:f"{'Preso in carico' if f.id in reviewed else GRAVITA[f.severity]} · {f.title}" for f in queue}
        chosen=st.selectbox("Rilievo",list(labels),format_func=labels.__getitem__,key="assistant_finding_"+report.id)
        item=next(f for f in queue if f.id==chosen)
        st.text(item.detail)
        if item.citations:
            evidence(item.citations)
        if chosen in reviewed:
            st.caption("Preso in carico nella sessione; non significa verificato o risolto.")
        elif st.button("Prendi in carico",key="assistant_ack_"+report.id+"_"+chosen,
                       icon=":material/check:"):
            reviewed[chosen]=utc_now().isoformat()
            notes[report.id]=reviewed
            st.session_state[REVIEWS]=notes
            st.rerun()
    return reviewed


def _report(report:Run,selection):
    inferred=report.mode=="LLM-assisted" and bool(report.interpretation)
    mode=("AI · "+(report.model or "modello selezionato") if inferred else
          "Calcoli locali · AI non disponibile" if report.mode=="Deterministic fallback" else "Calcoli locali · senza risposta AI")
    st.caption(mode+" · "+local_time(report.finished_at))
    period=report.assumptions.get("source_period") or report.source.latest_period or "non indicato"
    st.text(f"{report.source.name} · {TIPI[report.source.kind]} · periodo {period}")
    if not selection.bundle or report.input_sha256!=selection.bundle.fingerprint or report.assumptions.get("model")!=selection.model:
        st.warning("Questo risultato usa dati o un modello previsionale diversi dalla selezione corrente. Esegui una nuova analisi per aggiornarlo.")
    for warning in report.warnings:
        st.warning(warning)
    if report.source.refresh_failed:
        st.warning("La fonte non è stata aggiornata correttamente.")
    if inferred:
        st.markdown("**Risposta AI**")
        st.text(report.interpretation)
        if report.interpretation_sources:
            st.caption("Basata su: "+", ".join(AGENT_LABELS[a] for a in report.interpretation_sources)+". Interpretazione da verificare.")
    else:
        st.markdown("**Risultato dell’analisi**")
        if not report.results:
            st.text(report.summary or "Nessun risultato disponibile.")
    if Agent.REGULATORY in report.results:
        st.caption("Normativa: materiali di studio, non PDF caricati.")
        info("Fonti normative","I riscontri normativi del supervisore usano materiali predisposti. Interroga i PDF del tuo archivio in Norme e documenti.")
    if Agent.SETTLEMENT in report.results:
        st.caption("Settlement simulato · calcolatore semplice")
    # Deterministic evidence comes first for fallback. Avoid repeating run.summary.
    priority=(Agent.SCENARIO,Agent.FORECAST,Agent.MARKET,Agent.SETTLEMENT,Agent.REGULATORY,Agent.QUALITY)
    available=[a for a in priority if a in report.results]
    if report.question==DAILY_BRIEFING:
        available=[a for a in (Agent.MARKET,Agent.FORECAST,Agent.QUALITY,Agent.SCENARIO,Agent.SETTLEMENT,Agent.REGULATORY) if a in report.results]
    if available:
        st.markdown("**Dati e calcoli**")
        highlights=[a for a in available if a!=Agent.QUALITY] or available
        for agent in highlights[:2]:
            result=report.results[agent]
            st.caption(AGENT_LABELS[agent]+" · "+ESITI[result.status])
            st.text(result.summary)
        critical=[f for f in report.findings if f.severity=="high"]
        if critical:
            st.warning("Rilievi ad alta priorità: "+str(len(critical))+". Apri Rilievi da verificare.")
        with st.expander("Fonti e risultati degli agenti"):
            for agent in available:
                item=report.results[agent]
                st.markdown("**"+AGENT_LABELS[agent]+" · "+ESITI[item.status]+"**")
                st.text(item.summary)
                evidence(item.evidence)
                if item.values:
                    with st.popover("Dati di dettaglio · "+AGENT_LABELS[agent],icon=":material/info:"):
                        st.json(item.values,expanded=False)
            public=report.assumptions.get("public_operational_context") or {}
            if public:
                st.markdown("**Fonti operative aggiuntive**")
                for name,source in public.items():
                    st.text(str(name)+" · "+str(source.get("status","non indicato"))+" · "+str(source.get("gas_day") or source.get("acquired") or "data non indicata"))
                st.json(public,expanded=False)
    reviewed=_review(report)
    with st.expander("Traccia tecnica e ipotesi"):
        st.html(steps(report,grid=True))
        st.caption("Controlli di coerenza eseguiti" if report.validated_at else "Controlli di coerenza non conclusi")
        st.text("SHA-256 · "+report.input_sha256)
        st.json(report.assumptions,expanded=False)
        st.text("ID analisi · "+report.id)
    with st.popover("Scarica analisi",icon=":material/download:"):
        suffix=report.id[:10]
        st.download_button("Rapporto Markdown",markdown(report,reviewed),f"igor-{suffix}.md",
                           "text/markdown",key="assistant_md_"+report.id)
        st.download_button("Dati JSON",json.dumps({**report.model_dump(mode="json"),"acknowledged_findings":reviewed},ensure_ascii=False,indent=2),
                           f"igor-{suffix}.json","application/json",key="assistant_json_"+report.id)


def _history():
    history=st.session_state.get(HISTORY,[])
    if not history:
        return
    entries={r.id:r for r in history}
    if st.session_state.get(SELECTED) not in entries:
        st.session_state[SELECTED]=history[0].id
    with st.expander(f"Storico della sessione · {len(history)}"):
        st.selectbox("Consulta un’analisi",list(entries),key=SELECTED,
                     format_func=lambda k:local_time(entries[k].started_at)+" · "+entries[k].question[:80])
        st.caption("Solo in questa sessione. Scarica le analisi per conservarle.")
        st.button("Svuota storico dell’assistente",key="assistant_clear",on_click=_clear)


def assistant_page():
    st.title("Assistente AI")
    view=st.radio("Modalità assistente",["Assistente operativo","Analista dati"],horizontal=True,key="assistant_view")
    if view=="Analista dati":
        from .data_analyst_page import panel
        panel()
        return
    selection=source_filters("ops",lookback=False)
    area,scope=market_scope(selection.name)
    st.caption(area+" · "+scope)
    model=reasoner()
    st.caption(model.config.model if model else "Calcoli locali")
    if model and not model.config.local:
        st.caption("Solo dati pubblici · domande inviate al provider AI.")
    st.markdown("[Interroga i PDF](/regulatory)")
    info("Come funziona","Scegli una fonte e fai una domanda autonoma. Non è una ricerca web e non ha memoria conversazionale. Ogni nuova domanda esegue un’analisi indipendente.",
         "Le scorciatoie usano gli strumenti locali e, se attivo, un solo tentativo AI di sintesi. Le domande libere possono usare fino a tre chiamate. Le fonti supplementari si configurano nella barra laterale. Lo storico dell’assistente rimane nella sessione.")
    disabled=selection.bundle is None
    controls=st.columns([1,1,1,1.4])
    shortcut=None
    for col,(label,question) in zip(controls[:3],STARTERS):
        if col.button(label,key="assistant_starter_"+label,width="stretch",disabled=disabled,help=question):
            shortcut=question
    full=controls[3].button(analysis_label(),key="assistant_briefing",type="secondary",width="stretch",disabled=disabled)
    question=st.chat_input("Chiedi qualcosa sul mercato del gas…",key="assistant_question",max_chars=600,disabled=disabled)
    requested=DAILY_BRIEFING if full else shortcut or (question.strip() if question else "")
    answer_slot=st.container()
    history_slot=st.container()
    if requested:
        with answer_slot:
            with st.chat_message("user"):
                st.text(requested)
            with st.chat_message("assistant"):
                try:
                    report=launch(selection,requested,full=full,persist=False,planned_only=bool(full or shortcut),compact=True)
                except Exception as error:
                    LOG.warning("Assistant workflow failed (%s)",type(error).__name__)
                    report=None
                    st.error("Analisi non riuscita. Verifica le fonti o riprova in modalità senza AI.")
                if report:
                    _remember(report)
                    _report(report,selection)
                else:
                    st.caption("Nessun nuovo risultato salvato; puoi consultare le analisi precedenti nello storico.")
    else:
        history=st.session_state.get(HISTORY,[])
        chosen=st.session_state.get(SELECTED)
        report=next((r for r in history if r.id==chosen),history[0] if history else None)
        with answer_slot:
            if report:
                with st.chat_message("user"):
                    st.text(report.question)
                with st.chat_message("assistant"):
                    _report(report,selection)
            elif not disabled:
                st.caption("Scrivi una domanda o scegli una scorciatoia. Il risultato apparirà qui.")
            else:
                st.info("Seleziona una fonte disponibile per iniziare.")
    with history_slot:
        _history()
