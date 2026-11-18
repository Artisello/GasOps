"""Bilanciamento, ricerca normativa e centro operativo AI."""

from datetime import datetime
from html import escape
import json
import logging
import sqlite3

import pandas as pd
from pydantic import ValidationError
import streamlit as st

from .agents import MarketContext, RegulationArguments, regulation_result
from .finance import ScenarioCase, ScenarioInput, SettlementInput, scenario, settle
from .italiano import ESITI, GRAVITA, MODALITA, numero
from .models import AGENT_LABELS, Agent, Kind, Run, utc_now
from .regulatory import MAX_DOCUMENTS, REGISTER, SETTLEMENT_NOTE
from .reports import markdown
from .session import analysis_label, assumptions, database, fixture, launch, library, reasoner, save_assumptions, source_filters
from .visuals import chip, evidence, header, heading, info, kind_tag, kpi, local_time, rows, steps

LOG = logging.getLogger(__name__)
QUESTIONS = (
    "Quali fattori incidono sulla domanda di gas?",
    "Ci sono anomalie nelle ultime osservazioni?",
    "Come è cambiata la domanda rispetto alla settimana precedente?",
    "Cosa succede se la domanda aumenta del 10%?",
    "Qual è l’esposizione finanziaria nella simulazione di regolazione?",
    "Come definisce il Codice di Rete il bilanciamento commerciale?",
    "Quali incongruenze emergono nei documenti normativi?",
    "Prepara un bollettino sul mercato del gas.",
)


def _settlement_panel() -> None:
    state = assumptions()
    inputs = state.settlement
    form, output = st.columns([1, 1.25], gap="medium")
    with form, st.container(border=True, key="panel_settlement_input"):
        heading("Dati del partecipante", kind_tag(Kind.SIMULATION))
        info("Info dati","Volumi e prezzi di esempio modificabili. Per i decimali puoi usare la virgola.")
        with st.form("settlement_form", border=False):
            unit = st.selectbox("Unità di misura", ("kWh", "MWh", "GWh"), index=("kWh", "MWh", "GWh").index(inputs.unit))
            a, b = st.columns(2)
            with a:
                delivered = st.text_input("Energia immessa", str(inputs.delivered) if inputs.delivered is not None else "",
                                          max_chars=25)
                buy = st.text_input("Prezzo d’acquisto (€/MWh)", str(inputs.buy_eur_mwh) if inputs.buy_eur_mwh is not None else "",
                                    max_chars=25)
            with b:
                withdrawn = st.text_input("Energia prelevata", str(inputs.withdrawn) if inputs.withdrawn is not None else "",
                                          max_chars=25)
                sell = st.text_input("Prezzo di vendita (€/MWh)", str(inputs.sell_eur_mwh) if inputs.sell_eur_mwh is not None else "",
                                     max_chars=25)
            submitted = st.form_submit_button("Calcola la regolazione", type="primary", width="stretch")
        if submitted:
            try:
                inputs = SettlementInput(delivered=delivered, withdrawn=withdrawn, unit=unit,
                                         buy_eur_mwh=buy, sell_eur_mwh=sell)
                save_assumptions(state.model_copy(update={"settlement": inputs}))
            except ValidationError as error:
                labels = {"delivered": "energia immessa", "withdrawn": "energia prelevata",
                          "buy_eur_mwh": "prezzo d’acquisto", "sell_eur_mwh": "prezzo di vendita"}
                details = ", ".join(labels.get(issue["loc"][0], "unità di misura") for issue in error.errors())
                st.error(f"Verifica {details}. Il riepilogo mostra l’ultimo calcolo salvato.")
    with output, st.container(border=True, key="panel_settlement_output"):
        heading("Risultato della regolazione")
        result = settle(inputs)
        left, right = st.columns(2)
        with left:
            kpi("Sbilanciamento del partecipante", result.imbalance_mwh, "MWh", "Energia immessa − energia prelevata", 2)
        with right:
            kpi("Flusso di cassa del partecipante", result.cash_flow_eur, "EUR",
                ESITI[result.direction] if result.direction else "Importo da calcolare", 2,
                "rose" if result.direction == "charge" else "teal")
        rows([("Energia immessa", _readout(result.delivered_mwh, "MWh")),
              ("Energia prelevata", _readout(result.withdrawn_mwh, "MWh")),
              ("Operazione applicata", ESITI[result.side] if result.side else "Non disponibile"),
              ("Prezzo applicato", _readout(result.price_eur_mwh, "EUR/MWh"))])
        info("Info calcolo","Flusso di cassa = sbilanciamento × prezzo applicabile. Negativo = addebito; positivo = credito. Importo arrotondato al centesimo.")
        for issue in result.problems:
            st.warning(issue)
        with st.expander("Fonte del calcolo"):
            evidence([SETTLEMENT_NOTE])


def _readout(number, unit: str) -> str:
    return "Non disponibile" if number is None else f"{numero(number, 2)} {unit}"


def _scenario_panel() -> None:
    state = assumptions()
    changes = state.stress
    data = st.session_state.get("active_bundle") or fixture()
    facts = MarketContext(data, state.model, utc_now()).facts
    if facts.get("supply_gwh") is None:
        data = fixture()
        facts = MarketContext(data, state.model, utc_now()).facts
    saved_key = f"scenario_case_{data.fingerprint}"
    saved = st.session_state.get(saved_key)
    case = ScenarioCase.model_validate(saved or facts)
    form, output = st.columns([1, 1.25], gap="medium")
    with form, st.container(border=True, key="panel_scenario_input"):
        heading("Ipotesi dello scenario aggregato", kind_tag(Kind.SIMULATION))
        grain = "GWh/mese" if data.origin.grain == "monthly" else "GWh/giorno"
        st.caption(f"Base iniziale · {data.origin.name} · {facts['label']} · {grain}.")
        if data.origin.grain == "monthly":
            st.caption("L’offerta di base è la disponibilità contabile mensile pubblicata da Eurostat.")
        with st.form(f"scenario_form_{data.fingerprint[:12]}", border=False):
            a, b = st.columns(2)
            with a:
                demand = st.number_input("Domanda di base (GWh)", min_value=0.0, value=float(case.demand_gwh), step=10.0)
                storage = st.number_input("Contributo dello stoccaggio (GWh)", min_value=0.0,
                                          value=float(case.storage_gwh) if case.storage_gwh is not None else None)
                demand_pct = st.number_input("Variazione domanda (%)", -100.0, 300.0, float(changes.demand_pct))
                storage_pct = st.number_input("Variazione stoccaggio (%)", -100.0, 300.0, float(changes.storage_pct))
            with b:
                supply = st.number_input("Offerta totale di base (GWh)", min_value=0.0, value=float(case.supply_gwh), step=10.0)
                price = st.number_input("Prezzo di riferimento (€/MWh)",
                                        value=float(case.price_eur_mwh) if case.price_eur_mwh is not None else None)
                supply_pct = st.number_input("Variazione offerta escluso stoccaggio (%)", -100.0, 300.0, float(changes.supply_pct))
                price_delta = st.number_input("Variazione prezzo (€/MWh)", -1000.0, 1000.0, float(changes.price_delta_eur_mwh))
            submitted = st.form_submit_button("Confronta lo scenario", type="primary", width="stretch")
        if submitted:
            try:
                candidate = ScenarioCase(demand_gwh=demand, supply_gwh=supply, storage_gwh=storage, price_eur_mwh=price)
                updated = ScenarioInput(demand_pct=demand_pct, supply_pct=supply_pct, storage_pct=storage_pct,
                                        price_delta_eur_mwh=price_delta)
                scenario(candidate, updated)
                case, changes = candidate, updated
                st.session_state[saved_key] = case.model_dump(mode="json")
                save_assumptions(state.model_copy(update={"stress": changes}))
            except ValueError as error:
                st.error(str(error))
    with output, st.container(border=True, key="panel_scenario_output"):
        heading("Base e scenario")
        base = scenario(case, ScenarioInput(demand_pct=0))
        stress = scenario(case, changes)
        table = pd.DataFrame([
            {"Indicatore": label, "Base": _readout(getattr(base, field), unit),
             "Scenario": _readout(getattr(stress, field), unit)}
            for label, field, unit in (
                ("Domanda", "demand_gwh", "GWh"), ("Offerta totale", "supply_gwh", "GWh"),
                ("Parte da stoccaggio", "storage_gwh", "GWh"), ("Copertura", "coverage_pct", "%"),
                ("Saldo semplificato", "imbalance_gwh", "GWh"), ("Valore indicativo del saldo", "gap_value_eur", "EUR"),
            )
        ])
        st.dataframe(table, hide_index=True, width="stretch")
        if stress.gap_value_eur is not None:
            kpi("Variazione del valore del saldo", stress.gap_value_eur - base.gap_value_eur, "EUR", "Scenario − base", 0)
        info("Info scenario","Lo stoccaggio è già incluso nell’offerta. Il valore indicativo moltiplica il saldo in MWh per il prezzo di riferimento in €/MWh.","Il Centro operativo usa gli scostamenti salvati e la base della fonte selezionata.")


def balancing() -> None:
    header("Bilanciamento e regolazione", f'{kind_tag(Kind.SIMULATION)} <span>Regolazione del partecipante e scenari aggregati</span>')
    participant, aggregate = st.tabs(["Regolazione del partecipante", "Scenari aggregati"])
    with participant:
        _settlement_panel()
    with aggregate:
        _scenario_panel()


def _sync_uploads() -> None:
    files = st.session_state.get("reg_upload") or []
    st.session_state["pdf_uploads"] = tuple((item.name, item.getvalue()) for item in files[:MAX_DOCUMENTS])


def _reg_register() -> None:
    filters = {"all": "Tutti i rilievi", **GRAVITA}
    severity = st.selectbox("Gravità", tuple(filters), format_func=filters.__getitem__, key="reg_severity")
    cases = [entry for entry in REGISTER if severity == "all" or entry.finding.severity == severity]
    st.dataframe(
        [{"Rilievo": case.finding.title, "Gravità": GRAVITA[case.finding.severity],
          "Classificazione": case.finding.category, "Verifica dell’edizione": case.review} for case in cases],
        hide_index=True, width="stretch", height=40 + 36 * len(cases),
    )
    title = st.selectbox("Esamina il rilievo", [case.finding.title for case in cases], key="reg_finding")
    case = next(entry for entry in cases if entry.finding.title == title)
    with st.container(border=True, key="panel_reg_finding"):
        heading(case.finding.title, chip(GRAVITA[case.finding.severity].upper(), case.finding.severity))
        st.write(case.finding.detail)
        st.caption(case.review)
        evidence(case.finding.citations)


def _reg_query(docs) -> None:
    kind = st.radio("Modalità di ricerca", ["Fai una domanda", "Cerca nei documenti"], horizontal=True)
    available = ["Tutti i materiali indicizzati", *docs.documents]
    with st.form("reg_ask_form"):
        document = st.selectbox("Documento", available, disabled=kind == "Fai una domanda")
        query = st.text_input("Domanda o parole da cercare", placeholder="Come definisce il Codice di Rete il bilanciamento commerciale?",
                              max_chars=600)
        submitted = st.form_submit_button("Interroga l’analista" if kind == "Fai una domanda" else "Trova i riferimenti", type="primary")
    if submitted and not query.strip():
        st.warning("Inserisci una domanda o un termine di ricerca.")
    if submitted and query.strip():
        if kind == "Cerca nei documenti":
            found = docs.search(query, document=None if document == available[0] else document)
            st.session_state["reg_answer"] = (query, None, [hit.citation for hit in found], None, None)
        else:
            result = regulation_result(docs, RegulationArguments(query=query))
            interpretation, warning = None, None
            model = reasoner()
            if model and model.config.local and result.evidence:
                try:
                    interpretation, _ = model.interpret(query, {Agent.REGULATORY: result})
                except Exception as error:
                    LOG.warning("Regulatory interpretation unavailable (%s)", type(error).__name__)
                    warning = "Modello non disponibile. Puoi consultare i riferimenti qui sotto."
            st.session_state["reg_answer"] = (query, result.summary, result.evidence, interpretation, warning)
    answer = st.session_state.get("reg_answer")
    if answer:
        objective, summary, citations, narrative, warning = answer
        with st.container(border=True, key="panel_reg_answer"):
            heading("Riscontri nei documenti", chip(f"{len(citations)} RIFERIMENTI"))
            st.text(objective)
            if summary:
                st.text(summary)
            if warning:
                st.warning(warning)
            if narrative:
                st.caption("Interpretazione del modello sulle edizioni citate, da rivedere")
                st.text(narrative)
            if citations:
                evidence(citations)
            else:
                st.info("Nessun passaggio pertinente. Prova una frase del documento o carica un’edizione con testo ricercabile.")


def _reg_explorer(docs) -> None:
    if not docs.documents:
        st.info("Carica un PDF con testo ricercabile per aprire le pagine originali. Il registro contiene le note sulle edizioni esaminate.")
        return
    selected = st.selectbox("Documento PDF", list(docs.documents), key="reg_doc")
    document = docs.documents[selected]
    # The document itself provides the page numbers, including covers and contents.
    page = st.number_input("Pagina PDF", min_value=1, max_value=document.pages, step=1, value=1,
                           key=f"reg_page_{document.digest[:10]}")
    st.download_button("Scarica il PDF locale", document.data, file_name=document.name, mime="application/pdf",
                       icon=":material/download:")
    if st.button("Apri la pagina", type="primary", key="reg_open_page"):
        st.session_state["opened_pdf"] = (document.digest, int(page))
    if st.session_state.get("opened_pdf") == (document.digest, int(page)):
        st.image(document.render(int(page)), caption=f"{selected} · PDF p. {page}", width=690)
    with st.expander("Impronta dell’edizione"):
        st.code(document.digest, language=None)


def regulatory() -> None:
    header("Analisi normativa", '<span>Edizioni esaminate · applicabilità attuale da verificare</span>')
    left, right = st.columns([1.65, 1], gap="medium")
    with left:
        st.file_uploader("Aggiungi PDF con testo ricercabile", type=["pdf"], accept_multiple_files=True, key="reg_upload",
                         on_change=_sync_uploads)
    docs = library()
    with right, st.container(border=True, key="panel_reg_library"):
        heading("Archivio documenti", chip(f"{len(docs.documents)} PDFS"))
        if docs.documents:
            rows((title, f"{pdf.pages} pagine") for title, pdf in docs.documents.items())
        else:
            st.caption("Le note sulle edizioni esaminate sono disponibili offline.")
        for warning in docs.errors:
            st.warning(warning)
    register, ask, explorer = st.tabs(["Registro delle anomalie", "Ricerca e domande", "Consulta le pagine"])
    with register:
        _reg_register()
    with ask:
        _reg_query(docs)
    with explorer:
        _reg_explorer(docs)


def _example_question() -> None:
    chosen = st.session_state.get("ops_example")
    if chosen in QUESTIONS:
        st.session_state["ops_question"] = chosen


def _review_queue(report: Run, reviewed: dict[str, str]) -> None:
    queue = sorted(
        (finding for finding in report.findings if finding.severity != "info"),
        key=lambda f: (f.id in reviewed, f.severity != "high"),
    )
    heading("Coda di revisione", chip(f"{sum(f.id not in reviewed for f in queue)} APERTI", "review"))
    if not queue:
        st.caption("Nessun rilievo da rivedere in questa esecuzione.")
        return
    labels = {f.id: f"{'In carico' if f.id in reviewed else GRAVITA[f.severity]} · {f.title}" for f in queue}
    key = st.selectbox("Rilievo", list(labels), format_func=labels.__getitem__, key=f"review_item_{report.id}")
    finding = next(f for f in queue if f.id == key)
    st.caption(finding.category)
    st.text(finding.detail)
    evidence(finding.citations)
    if finding.id in reviewed:
        st.caption(f"Preso in carico il {local_time(datetime.fromisoformat(reviewed[finding.id]))}")
    elif st.button("Prendi in carico", key=f"review_{report.id}_{finding.id}", icon=":material/check:"):
        try:
            database().acknowledge(report.id, finding.id)
            st.rerun()
        except sqlite3.Error:
            LOG.exception("Unable to acknowledge finding")
            st.error("Impossibile salvare il rilievo nello storico locale.")


def _report_panel(report: Run) -> None:
    reviewed = database().reviewed(report.id)
    main, side = st.columns([1.9, 1], gap="medium")
    with main, st.container(border=True, key="panel_ops_summary"):
        heading("Sintesi operativa", chip(MODALITA[report.mode], "ok" if report.mode == "LLM-assisted" else ""))
        rows([("Fonte dati", report.source.name), ("Fine analisi", local_time(report.finished_at)), ("ID analisi", report.id[:12])])
        if report.model:
            st.caption("Modello selezionato: "+report.model)
        for warning in report.warnings:
            st.warning(warning)
        if report.assumptions.get("public_operational_context"):
            with st.expander("Fonti operative del briefing"):
                st.json(report.assumptions["public_operational_context"],expanded=False)
        if report.interpretation:
            st.markdown("**Interpretazione AI · da verificare**")
            st.text(report.interpretation)
            st.caption("Strumenti consultati · " + ", ".join(AGENT_LABELS[agent] for agent in report.interpretation_sources))
        else:
            st.caption("Nessuna interpretazione AI generata: risultati dei calcoli locali.")
        for agent in Agent:
            if agent in report.results:
                result = report.results[agent]
                st.markdown(f"**{AGENT_LABELS[agent]}**")
                st.text(result.summary)
        a, b = st.columns(2)
        suffix = report.id[:10]
        with a:
            payload = {**report.model_dump(mode="json"), "acknowledged_findings": reviewed}
            st.download_button("Scarica JSON", json.dumps(payload, ensure_ascii=False, indent=2),
                               f"gasops-{suffix}.json", mime="application/json", icon=":material/download:", width="stretch")
        with b:
            st.download_button("Scarica Markdown", markdown(report, reviewed), f"gasops-{suffix}.md",
                               mime="text/markdown", icon=":material/download:", width="stretch")
    with side, st.container(border=True, key="panel_ops_review"):
        _review_queue(report, reviewed)

    with st.container(border=True, key="panel_ops_trace"):
        conflict = any(item.category == "Validazione indipendente" for item in report.findings)
        verification = chip("CONFLITTO RILEVATO", "high") if conflict else chip("VALIDAZIONE COMPLETATA", "ok")
        heading("Esecuzione degli agenti e riscontri", verification if report.validated_at else "")
        with st.expander("Dati di ingresso e impronta del dataset"):
            st.code(report.input_sha256, language=None)
            st.json(report.assumptions, expanded=False)
        for agent in Agent:
            if agent not in report.results:
                continue
            item = report.results[agent]
            step = report.steps[agent]
            with st.expander(f"{AGENT_LABELS[agent]} · {ESITI[step.status]}"):
                if step.started_at and step.finished_at:
                    elapsed = (step.finished_at - step.started_at).total_seconds()
                    st.caption(f"{local_time(step.started_at)} · {numero(elapsed * 1000, 0)} ms")
                st.text(item.summary)
                evidence(item.evidence)
                if item.values:
                    st.json(item.values, expanded=False)
                for finding in item.findings:
                    st.caption(f"{GRAVITA[finding.severity].upper()} · {finding.title}. {finding.detail}")


def operations() -> None:
    top, controls = st.container(), st.container()
    with controls:
        selection = source_filters("ops", lookback=False)
    with top:
        started = header("Centro operativo AI", selection.meta, analysis_label(), disabled=selection.bundle is None)
    st.caption("Bollettino completo o domanda mirata · risultati qui sotto.")
    with st.container(border=True, key="panel_ops_query"):
        heading("Interroga l’analista")
        st.caption("Usa solo domande e dati pubblici o sintetici; non inserire informazioni riservate.")
        st.selectbox("Domanda di esempio", ["Scegli un esempio", *QUESTIONS], key="ops_example", on_change=_example_question)
        with st.form("ops_question_form", border=False):
            question = st.text_area("Richiesta di analisi", height=84, key="ops_question", max_chars=600,
                                    placeholder="Prepara un bollettino sul mercato del gas.")
            asked = st.form_submit_button("Invia la domanda", type="primary", disabled=selection.bundle is None)
    report = None
    if started:
        report = launch(selection, full=True)
    elif asked and question.strip():
        report = launch(selection, question)
    elif asked:
        st.warning("Inserisci una richiesta di analisi.")
    if report:
        st.session_state["ops_history"] = report.id

    history = database().recent()
    current = st.session_state.get("last_run")
    if current and all(item.id != current.id for item in history):
        history.insert(0, current)
    selected = None
    if history:
        entries = {run.id: run for run in history}
        chosen = st.selectbox(
            "Storico delle analisi", list(entries), key="ops_history",
            format_func=lambda item: f"{local_time(entries[item].started_at)} · {entries[item].question[:65]}",
        )
        selected = entries[chosen]
        _report_panel(selected)
    with st.expander("Flusso del supervisore",icon=":material/info:"):
        st.html('<div class="gas-flow-track"><span>Qualità</span><b>→</b><span>Agenti</span><b>→</b><span>Validazione</span><b>→</b><span>Report</span></div>')
        st.html(steps(selected,grid=True))
