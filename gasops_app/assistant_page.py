"""Session-scoped analytical assistant. No new provider or document permissions."""
import json
import logging

import streamlit as st

from .italiano import ESITI, GRAVITA, TIPI, numero
from .market import demand_trend_question, demand_readout
from .assistant_sources import source_rows
from .models import Agent, AGENT_LABELS, Run, utc_now
from .reports import markdown
from . import session
from .session import analysis_label, launch, market_scope, reasoner, source_filters, ai_activation_panel
from .visuals import evidence, info, local_time, steps, ai_readout, header
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


def _source_evidence_panel(report):
    rows=source_rows(report)
    if not rows:return
    # Show the relevant numerical evidence without relying on prose generation.
    # Other acquired sources remain in the existing details expander.
    selected=[row for row in rows if row["required"] or row["cited"]]
    if not selected:return
    by_status={"available":"Disponibile","stale":"Non recente","unavailable":"Non disponibile"}
    cited=sum(row["cited"] for row in selected)
    title=f"Fonti pertinenti · {len(selected)}"
    if report.mode=="LLM-assisted":
        title+=f" · {cited} citate dall’AI"
    with st.expander(title,expanded=True):
        for row in selected:
            status=by_status.get(row["status"],row["status"])
            period=str(row["period"] or "")[:10]
            st.caption(" · ".join(x for x in (row["source"],period,status,"Citata" if row["cited"] else "") if x))
            st.text(row["evidence"])


def _report(report:Run,selection):
    inferred=report.mode=="LLM-assisted" and bool(report.interpretation)
    mode=("AI · "+(report.model or "modello selezionato") if inferred else
          "Calcoli locali · AI non disponibile" if report.mode=="Deterministic fallback" else "Calcoli locali · senza risposta AI")
    st.caption(mode+" · "+local_time(report.finished_at))
    period=report.assumptions.get("source_period") or report.source.latest_period or "non indicato"
    if report.assumptions.get("scope_unavailable"):
        st.info(report.summary)
        return
    st.text(f"{report.source.name} · {TIPI[report.source.kind]} · periodo {period}")
    if report.assumptions.get("requested_country")=="DE":
        st.caption("Perimetro della domanda: Germania · selezione automatica per questa analisi. Prezzo THE e dati di bilanciamento effettivi non integrati.")
    if (not report.assumptions.get("requested_country") and (not selection.bundle or report.input_sha256!=selection.bundle.fingerprint)) or report.assumptions.get("model")!=selection.model:
        st.warning("Questo risultato usa dati o un modello previsionale diversi dalla selezione corrente. Esegui una nuova analisi per aggiornarlo.")
    for warning in report.warnings:
        st.warning(warning)
    if report.source.refresh_failed:
        st.warning("La fonte non è stata aggiornata correttamente.")
    if inferred:
        st.markdown("**Risposta AI**")
        ai_readout(report)
    else:
        if report.mode!="Deterministic" and not report.warnings:
            st.warning("Nessuna risposta AI generata; risultati locali.")
        st.markdown("**Report di calcolo (senza AI)**")
        if not report.results:
            st.text(report.summary or "Nessun risultato disponibile.")
    _source_evidence_panel(report)
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
        if not inferred:
            st.markdown("**Dati e calcoli**")
            highlights=[a for a in available if a!=Agent.QUALITY] or available
            for agent in highlights[:2]:
                result=report.results[agent]
                st.caption(AGENT_LABELS[agent]+" · "+ESITI[result.status])
                concise=demand_readout(result.values,report.source.grain) if agent==Agent.MARKET and demand_trend_question(report.question) else None
                st.text(concise or result.summary)
            if report.assumptions.get("requested_country")=="DE":
                storage=(report.assumptions.get("public_operational_context") or {}).get("AGSI+ Germania",{})
                if storage.get("status")=="available":
                    values=storage.get("values",{})
                    if values.get("fill_pct") is not None:
                        st.text("Stoccaggi Germania: "+numero(values["fill_pct"],1)+"% · "+str(storage.get("gas_day","data non indicata"))+" · GIE AGSI+")
                elif storage:
                    st.caption("Stoccaggi Germania non disponibili o non recenti.")
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
                for row in source_rows(report):
                    st.caption(str(row["source"])+" · "+str(row["status"])+" · "+str(row["period"] or "data non indicata")+" · "+("citata dall’AI" if row["cited"] else "non citata dall’AI"))
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


def _visible_history(local=False):
    history=st.session_state.get(HISTORY,[])
    return [r for r in history if not(local and r.mode=="LLM-assisted" and r.interpretation)]


def _history(local=False):
    history=_visible_history(local)
    total=len(st.session_state.get(HISTORY,[]))
    if not total:
        return None
    entries={r.id:r for r in history}
    if history and st.session_state.get(SELECTED) not in entries:
        st.session_state[SELECTED]=history[0].id
    with st.expander(f"Storico della sessione · {len(history)}"+(f" / {total}" if local and total!=len(history) else "")):
        if history:
            def label(k):
                item=entries[k]
                mode="AI" if item.mode=="LLM-assisted" and item.interpretation else "Locale"
                return local_time(item.started_at)+" · "+mode+" · "+item.question[:80]
            st.selectbox("Consulta un’analisi",list(entries),key=SELECTED,format_func=label)
        else:
            st.caption("Nessun risultato locale. Le risposte AI sono consultabili in Assistente operativo.")
        st.caption("Solo in questa sessione. Scarica le analisi per conservarle.")
        st.button("Svuota storico dell’assistente",key="assistant_clear",on_click=_clear,
                  help="Rimuove tutti i risultati dell’assistente, anche quelli AI. Non elimina i bollettini della Panoramica.")
    return entries.get(st.session_state.get(SELECTED))


def ai_configured() -> bool:
    """Read local configuration without requiring a newly added session symbol.

    Streamlit can retain already imported modules across a source update.
    Configuration checks must not activate a model or call a provider.
    """
    try:
        return session._configuration() is not None
    except ValueError:
        return False


def assistant_page():
    from .workspace import picker
    header("Assistente AI","")
    modes=["Assistente operativo","Analista dati","Report locali"]
    from .gme_market import api_configured as gme_configured
    if gme_configured():
        modes.append("Indicatori GME")
    default=0 if reasoner() or ai_configured() else 2
    view=picker("Modalità assistente",modes,index=default,key="assistant_view",
                labels={"Assistente operativo":"Chiedi all’AI","Analista dati":"Esplora i dati","Report locali":"Report senza AI"})
    if view=="Indicatori GME":
        from .gme_market_page import assistant
        assistant()
        return
    if view=="Analista dati":
        from .data_analyst_page import panel
        panel()
        return
    local=view=="Report locali"
    model=None if local else reasoner()
    if not local and model is None:
        ai_activation_panel(prefix="assistant")
        st.chat_input("Attiva l’AI per scrivere una domanda",key="assistant_question",max_chars=600,disabled=True)
        st.caption("Report locali e Analista dati restano disponibili.")
        return
    selection=source_filters("ops",lookback=False)
    area,scope=market_scope(selection.name)
    mode_label="Calcoli locali" if local else "AI · "+model.config.model
    st.caption(area+" · "+scope+" · "+mode_label)
    if model and not model.config.local:
        st.caption("Provider esterno · solo dati pubblici.")
    if local:
        info("Come funziona","Report deterministici con parametri e controlli predefiniti. Nessuna chat o interpretazione AI.")
    else:
        info("Come funziona","Ogni domanda avvia un'analisi indipendente. Il programma seleziona le fonti pertinenti; il modello interpreta le evidenze e deve citarle. Se non riesce, vengono mostrati solo calcoli di riserva, non una risposta AI.",
             "Le scorciatoie utilizzano un tentativo AI di sintesi; le domande libere fino a tre chiamate. Lo storico rimane nella sessione.")
    disabled=selection.bundle is None
    st.caption("Per interrogare documenti specifici: [Cerca nei PDF](/regulatory).")
    controls=st.columns([1,1,1,1.4])
    shortcut=None
    for col,(label,question) in zip(controls[:3],STARTERS):
        if col.button(label,key="assistant_starter_"+label,width="stretch",disabled=disabled,help=question):
            shortcut=question
    full=controls[3].button("Genera bollettino locale" if local else "Genera bollettino AI",key="assistant_briefing",type="secondary",width="stretch",disabled=disabled)
    question=None if local else st.chat_input("Chiedi qualcosa sul mercato del gas…",key="assistant_question",max_chars=600,disabled=disabled)
    requested=DAILY_BRIEFING if full else shortcut or (question.strip() if question else "")
    history_slot=st.container()
    answer_slot=st.container()
    def render(report):
        if local:
            if report.mode=="LLM-assisted" and report.interpretation:
                st.info("Questa analisi precedente contiene una risposta AI. Consultala in Assistente operativo con AI attiva.")
                return
            st.text(report.question)
            _report(report,selection)
        else:
            with st.chat_message("user"):
                st.text(report.question)
            with st.chat_message("assistant"):
                _report(report,selection)
    generated=None
    attempted=bool(requested)
    if requested:
        with answer_slot:
            try:
                generated=launch(selection,requested,full=full,persist=False,planned_only=bool(local or full or shortcut),compact=True,
                                 ai_policy="off" if local else "required")
            except Exception as error:
                LOG.warning("Assistant workflow failed (%s)",type(error).__name__)
            if generated:
                _remember(generated)
            else:
                st.error("Analisi non riuscita. Verifica il modello o le fonti; nessuna risposta AI generata." if not local else "Report locale non disponibile. Verifica le fonti.")
    with history_slot:
        previous=_history(local)
    with answer_slot:
        report=generated or previous
        if report:
            if not generated:
                st.caption("Ultimo risultato conservato · la nuova analisi non è riuscita." if attempted else
                           "Risultato precedente · modalità effettiva indicata nel report")
            render(report)
        elif not attempted:
            if not disabled:
                st.caption("Scegli un report. Il risultato apparirà qui." if local else "Scrivi una domanda o scegli una scorciatoia. Il risultato apparirà qui.")
            else:
                st.info("Seleziona una fonte disponibile per iniziare.")
