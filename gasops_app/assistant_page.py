"""Session-scoped analytical assistant. No new provider or document permissions."""
from datetime import datetime
import json
import logging

import streamlit as st

from .italiano import ESITI, GRAVITA, TIPI, numero
from .market import demand_trend_question, demand_readout
from .assistant_sources import source_rows, COMMANDS, resolve_followup, wants_day_comparison, day_comparison
from .models import Agent, AGENT_LABELS, Kind, Run, utc_now
from .reports import markdown
from . import session
from zoneinfo import ZoneInfo
from .session import launch, assistant_reasoner
from .visuals import evidence, info, local_time, steps, ai_readout, header
from .workflow import DAILY_BRIEFING

LOG=logging.getLogger(__name__)
HISTORY="assistant_history_v1"
REVIEWS="assistant_reviews_v1"
SELECTED="assistant_selected_v1"
CONTEXT="assistant_context_v1"
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
    st.session_state["assistant_gme_readouts_v1"]={k:v for k,v in st.session_state.get("assistant_gme_readouts_v1",{}).items() if k in allowed}
    st.session_state[SELECTED]=report.id


def _clear():
    # Only this assistant's session history, not reports kept elsewhere.
    st.session_state.pop(HISTORY,None)
    st.session_state.pop(REVIEWS,None)
    st.session_state.pop(SELECTED,None)
    st.session_state.pop(CONTEXT,None)
    st.session_state.pop("assistant_gme_readouts_v1",None)


def _previous_turn():
    # Historical selection and local reports do not become conversation context.
    identifier=st.session_state.get(CONTEXT)
    return next((r for r in st.session_state.get(HISTORY,[]) if r.id==identifier),None)


def _user_question(report):
    return report.assumptions.get("assistant_user_question") or report.question


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
    by_status={"available":"Disponibile","partial":"Parziale","stale":"Non recente","unavailable":"Non disponibile"}
    cited=sum(row["cited"] for row in selected)
    title=f"Fonti pertinenti · {len(selected)}"
    if report.mode=="LLM-assisted":
        title+=f" · {cited} citate"
    with st.expander(title,expanded=bool(report.assumptions.get("source_lookup")) and not report.interpretation):
        for row in selected:
            status=by_status.get(row["status"],row["status"])
            detail=[str(row["source"]),row["scope"],row["period"],status,"Citata" if row["cited"] else None]
            if row["acquired"]:
                try:
                    detail.append("Acquisita "+local_time(datetime.fromisoformat(row["acquired"])))
                except (ValueError,TypeError):
                    pass
            if row["url"]:
                detail.append("[Fonte ufficiale]("+row["url"]+")")
            st.caption(" · ".join(str(part) for part in detail if part))
            st.text(row["evidence"])
            if row["limitation"]:
                st.caption(row["limitation"])


def _document_report(report,*,fresh=False):
    result=report.results[Agent.REGULATORY]
    claims=report.assumptions.get("document_claims",[])
    if claims:
        st.caption("AI locale · riscontri nei PDF")
        for claim in claims:
            st.text(claim["text"])
            cite=claim["citation"]
            st.caption(cite["document"]+" · PDF p. "+str(cite["page"]))
    else:
        st.caption("Ricerca nei PDF · estratti locali")
        st.text(result.summary)
    for warning in report.warnings:
        st.caption(warning)
    if result.evidence:
        with st.expander("Estratti dei PDF",expanded=not claims):
            evidence(result.evidence)
    _source_evidence_panel(report)
    if gme:=report.assumptions.get("gme_request"):
        from .gme_market_page import assistant_prices
        assistant_prices(gme,report.started_at,report_id=report.id,refresh=fresh)
    st.caption(str(report.assumptions.get("document_count",0))+" PDF consultabili · edizione e applicabilità da verificare")


def _period_report(report):
    from .assistant_sources import source_evidence, safe_source_url
    periods=report.assumptions["assistant_periods"]
    monthly=report.assumptions["assistant_period_grain"]=="mese"
    def label(period):
        return period[:7] if monthly else period
    st.caption("Confronto "+("mensile" if monthly else "giornaliero")+" · "+label(periods[0])+" → "+label(periods[1]))
    rows=report.assumptions["assistant_comparison"]
    if rows:
        st.dataframe([{"Indicatore":row["metric"],
                       label(periods[0]):numero(row["before"],2)+" "+row["unit"],
                       label(periods[1]):numero(row["after"],2)+" "+row["unit"],
                       "Differenza":("+" if row["delta"]>0 else "")+numero(row["delta"],2)+" "+row["delta_unit"],
                       "Variazione %":numero(row["delta_pct"],2)+"%" if row["delta_pct"] is not None else "—",
                       "Fonte":row["source"]} for row in rows],hide_index=True,width="stretch")
        st.caption("Calcolo locale · variazione sul primo periodo; p.p. = punti percentuali.")
    else:
        st.info("Nessuna coppia di osservazioni confrontabili per i periodi richiesti.")
    snapshots=report.assumptions["assistant_period_evidence"]
    with st.expander("Fonti e copertura",expanded=not rows):
        for period,snapshot in zip(periods,snapshots):
            st.markdown("**"+label(period)+"**")
            for key,item in snapshot.items():
                detail=[str(item.get("source",key)),str(item.get("scope","")),
                        str(item.get("gas_day") or item.get("period") or ""),
                        str(item.get("status","non disponibile"))]
                url=safe_source_url(item.get("source_url") or item.get("url"))
                st.caption(" · ".join(part for part in detail if part)+(" · [Fonte ufficiale]("+url+")" if url else ""))
                st.text(source_evidence(key,item))
                if item.get("quality_review"):
                    st.caption("Controllo qualità richiesto; escluso dal confronto.")
                if item.get("kind")=="estimated":
                    st.caption("Stima; esclusa dal confronto.")
                if item.get("limitation"):
                    st.caption(item["limitation"])


def _query_report(report):
    payload=report.assumptions.get("assistant_query_evidence")
    if not payload:
        st.info(report.summary)
        return
    plan=payload["plan"]
    labels={"mean":"Media aritmetica","sum":"Totale","min":"Minimo","max":"Massimo",
            "change":"Variazione primo–ultimo","std":"Deviazione standard campionaria",
            "correlation":"Correlazione di Pearson"}
    op=plan["operation"]
    label=labels[op]
    monthly=plan["grain"]=="month"
    first,last=(plan[k][:7] if monthly else plan[k] for k in ("from","to"))
    st.caption("Calcolo locale · "+label+" · "+first+" – "+last)
    if op=="correlation":
        for item in payload["correlations"]:
            st.metric("Correlazione (r)",numero(item["pearson"],3))
            st.caption(str(item["n"])+" coppie · associazione, non causalità")
        if not payload["correlations"]:
            st.info("Correlazione non calcolabile: servono almeno 14 coppie complete e due serie non costanti.")
    for row in payload["rows"]:
        if row["value"] is not None:
            value=numero(row["value"],2)+" "+row["unit"]
            st.metric(row["metric"],value)
            if op=="change" and row.get("change_pct") is not None:
                st.caption("Variazione relativa: "+numero(row["change_pct"],2)+"%")
        elif row.get("reason"):
            st.info(row["metric"]+" · "+row["reason"])
        st.caption(row["source"]+" · "+row["scope"]+" · "+str(row["n"])+"/"+str(row["expected"])+" osservazioni")
    with st.expander("Fonti e metodo"):
        for row in payload["rows"]:
            st.caption(row["metric"]+" · "+row["status"])
            if row["url"]:
                st.markdown("[Fonte ufficiale]("+row["url"]+")")
            if op=="change" and row.get("first_value") is not None:
                st.text("Primo: "+numero(row["first_value"],2)+" · ultimo: "+numero(row["last_value"],2))
        st.caption("Nessuna imputazione; le medie sono aritmetiche, non ponderate. I prelievi SRG non sono il totale nazionale.")
        st.json(payload,expanded=False)
    st.download_button("Scarica analisi JSON",json.dumps(payload,ensure_ascii=False,indent=2),
        "igor-query-"+report.id[:10]+".json","application/json",key="query_export_"+report.id)


def _report(report:Run,selection,*,fresh=False):
    if report.assumptions.get("assistant_data_query"):
        _query_report(report)
        return
    if report.assumptions.get("assistant_period_comparison"):
        _period_report(report)
        return
    if report.assumptions.get("assistant_document_lookup"):
        _document_report(report,fresh=fresh)
        return
    inferred=report.mode=="LLM-assisted" and bool(report.interpretation)
    mode=("Dati verificati · risposta diretta" if report.assumptions.get("assistant_fast_lookup") else
          "AI · "+(report.model or "modello selezionato") if inferred else
          "Calcoli locali · AI non disponibile" if report.mode=="Deterministic fallback" else "Calcoli locali · senza risposta AI")
    st.caption(mode+" · "+local_time(report.finished_at))
    if report.assumptions.get("assistant_user_question"):
        st.caption("Quesito interpretato: "+report.question)
    period=report.assumptions.get("source_period") or report.source.latest_period or "non indicato"
    if report.assumptions.get("scope_unavailable"):
        st.info(report.summary)
        return
    lookup=bool(report.assumptions.get("source_lookup"))
    if lookup:
        if requested_day:=report.assumptions.get("requested_day"):
            st.caption("Data richiesta · "+requested_day)
        if not report.assumptions.get("public_operational_context") and not report.assumptions.get("gme_request"):
            st.info(report.summary)
    else:
        st.text(f"{report.source.name} · {TIPI[report.source.kind]} · periodo {period}")
        if report.assumptions.get("requested_country")=="DE":
            st.caption("Perimetro Germania · bilancio mensile Eurostat.")
        if selection is not None and ((not report.assumptions.get("requested_country") and (not selection.bundle or
                report.input_sha256!=selection.bundle.fingerprint)) or report.assumptions.get("model")!=selection.model):
            st.warning("Questo risultato usa dati o un modello previsionale diversi dalla selezione corrente. Esegui una nuova analisi per aggiornarlo.")
    for warning in report.warnings:
        st.warning(warning)
    if report.source.refresh_failed:
        st.warning("La fonte non è stata aggiornata correttamente.")
    if inferred:
        ai_readout(report,compact=True)
    elif not lookup:
        if report.mode!="Deterministic" and not report.warnings:
            st.warning("Nessuna risposta AI generata; risultati locali.")
        st.markdown("**Report di calcolo (senza AI)**")
        if not report.results:
            st.text(report.summary or "Nessun risultato disponibile.")
    if "assistant_comparison" in report.assumptions:
        rows=report.assumptions["assistant_comparison"]
        if rows:
            st.markdown("**Confronto tra giorni**")
            st.caption("Variazione: giorno più recente − giorno meno recente. p.p. = punti percentuali.")
            st.dataframe([{"Indicatore":row["metric"],"Fonte":row["source"],"Area":row["scope"],
                           "Prima":row["before_day"]+" · "+numero(row["before"],2)+" "+row["unit"],
                           "Dopo":row["after_day"]+" · "+numero(row["after"],2)+" "+row["unit"],
                           "Variazione":("+" if row["delta"]>0 else "")+numero(row["delta"],2)+" "+row["delta_unit"]}
                          for row in rows],hide_index=True,width="stretch")
        else:
            st.info("Confronto non disponibile: mancano due osservazioni giornaliere confrontabili.")
    _source_evidence_panel(report)
    if gme:=report.assumptions.get("gme_request"):
        from .gme_market_page import assistant_prices
        assistant_prices(gme,report.started_at,report_id=report.id,refresh=fresh)
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
                return local_time(item.started_at)+" · "+mode+" · "+_user_question(item)[:80]
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
    modes=("Assistente operativo","Analista dati","Report locali")
    # Migrate retired GME navigation without changing the execution-mode consent.
    if st.session_state.get("assistant_view") not in (*modes,None):
        st.session_state["assistant_view"]="Assistente operativo"
    view=picker("Modalità assistente",modes,index=0,key="assistant_view",
                labels={"Assistente operativo":"Chiedi all’AI","Analista dati":"Esplora dati","Report locali":"Report"})
    if view=="Analista dati":
        from .data_analyst_page import panel
        panel()
        return
    local=view=="Report locali"
    model=None if local else assistant_reasoner()
    if not local and model is None:
        st.info("AI non configurata. I report locali restano disponibili.")
        st.chat_input("Fai una domanda sul mercato del gas",key="assistant_question",max_chars=600,disabled=True)
        previous=_history()
        if previous:
            with st.chat_message("user"):
                st.text(_user_question(previous))
            with st.chat_message("assistant"):
                _report(previous,None)
        return

    # No dataset or model picker: all questions use automatic evidence routing.
    selection=None
    if local:
        st.caption("Calcoli locali · fonti automatiche")
    elif not model.config.local:
        st.caption("AI attiva · fonti automatiche · provider esterno: solo dati pubblici")
    else:
        st.caption("AI attiva · fonti automatiche")

    history_slot=st.container()
    answer_slot=st.container(key="assistant_answer")
    controls=st.columns([1,1,1,1.3],gap="small")
    shortcut=None
    for col,(label,question) in zip(controls[:3],STARTERS):
        if col.button(label,key="assistant_starter_"+label,width="stretch",help=question):
            shortcut=question
    full=controls[3].button("Bollettino",key="assistant_briefing",width="stretch",
                            help="Genera bollettino locale" if local else "Genera bollettino AI")
    if not local:
        with st.popover("Info · comandi",icon=":material/info:"):
            st.caption("Scrivi una domanda libera: I.G.O.R. sceglie le fonti pertinenti. Puoi anche confrontare due giorni o due mesi espliciti.")
            st.caption("Non inserire dati riservati con un provider remoto. Gli estratti dei PDF rimangono locali senza consenso esplicito.")
            for command,example in COMMANDS.items():
                st.markdown("**"+command+"** · "+example)
            st.caption("Esempi: /scorte 20/11/2026 · /mase 2025 · Media dei prelievi SRG negli ultimi 30 giorni · Totale delle importazioni negli ultimi 12 mesi.")
    question=None if local else st.chat_input("Chiedi qualcosa sul gas…",key="assistant_question",max_chars=600)
    requested=DAILY_BRIEFING if full else shortcut or (question.strip() if question else "")
    previous_turn=_previous_turn()
    resolved,issue=(resolve_followup(requested,previous_turn,today=utc_now().astimezone(ZoneInfo("Europe/Rome")).date())
                    if requested and not (local or full or shortcut) else (requested,None))

    def render(report,*,fresh=False):
        if local:
            st.text(report.question)
            _report(report,selection,fresh=fresh)
        else:
            with st.chat_message("user"):
                st.text(_user_question(report))
            with st.chat_message("assistant"):
                _report(report,selection,fresh=fresh)

    def generate():
        try:
            return launch(selection,resolved,full=full,persist=False,
                          planned_only=bool(local or full or shortcut),compact=True,
                          ai_policy="off" if local else "automatic")
        except Exception as error:
            LOG.warning("Assistant workflow failed (%s)",type(error).__name__)
            return None

    generated=None
    attempted=bool(requested)
    if attempted:
        with answer_slot:
            if local:
                generated=generate()
                if generated:
                    _remember(generated)
                    render(generated,fresh=True)
                else:
                    st.error("Report non disponibile. Verifica le fonti.")
            else:
                with st.chat_message("user"):
                    st.text(requested)
                with st.chat_message("assistant"):
                    if issue:
                        st.info(issue)
                    else:
                        # Failed requests must not silently reuse the earlier turn.
                        st.session_state.pop(CONTEXT,None)
                        generated=generate()
                        if generated:
                            if resolved!=requested:
                                generated.assumptions["assistant_user_question"]=requested
                                if wants_day_comparison(requested):
                                    generated.assumptions["assistant_comparison"]=day_comparison(previous_turn,generated)
                            _remember(generated)
                            st.session_state[CONTEXT]=generated.id
                            _report(generated,selection,fresh=True)
                        else:
                            st.error("Analisi non disponibile. Verifica le fonti o specifica la domanda.")
    with history_slot:
        previous=_history(local)
    if not generated and previous and not issue:
        with answer_slot:
            if attempted:
                st.divider()
                st.caption("Ultimo risultato conservato · non è la risposta alla nuova richiesta.")
            render(previous)

