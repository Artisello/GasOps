"""Settlement, regulatory research and AI Operations Centre pages."""

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
from .models import AGENT_LABELS, Agent, Kind, Run, utc_now
from .regulatory import MAX_DOCUMENTS, REGISTER, SETTLEMENT_NOTE
from .reports import markdown
from .session import assumptions, database, fixture, launch, library, reasoner, save_assumptions, source_filters
from .visuals import STATUS, chip, evidence, header, heading, kind_tag, kpi, local_time, rows, steps

LOG = logging.getLogger(__name__)
QUESTIONS = (
    "What are the main factors affecting gas demand?",
    "Are there anomalies in the latest observations?",
    "How has demand changed compared with last week?",
    "What happens if demand increases by 10%?",
    "What is the estimated financial exposure under this settlement scenario?",
    "How does the Network Code define commercial balancing?",
    "What potential inconsistencies exist in the regulatory documents?",
    "Generate a daily gas market operations briefing.",
)


def _settlement_panel() -> None:
    state = assumptions()
    inputs = state.settlement
    form, output = st.columns([1, 1.25], gap="medium")
    with form, st.container(border=True, key="panel_settlement_input"):
        heading("Participant inputs", kind_tag(Kind.SIMULATION))
        with st.form("settlement_form", border=False):
            unit = st.selectbox("Volume unit", ("kWh", "MWh", "GWh"), index=("kWh", "MWh", "GWh").index(inputs.unit))
            a, b = st.columns(2)
            with a:
                delivered = st.text_input("Delivered energy", str(inputs.delivered) if inputs.delivered is not None else "",
                                          max_chars=25)
                buy = st.text_input("Buy price (EUR/MWh)", str(inputs.buy_eur_mwh) if inputs.buy_eur_mwh is not None else "",
                                    max_chars=25)
            with b:
                withdrawn = st.text_input("Withdrawn energy", str(inputs.withdrawn) if inputs.withdrawn is not None else "",
                                          max_chars=25)
                sell = st.text_input("Sell price (EUR/MWh)", str(inputs.sell_eur_mwh) if inputs.sell_eur_mwh is not None else "",
                                     max_chars=25)
            submitted = st.form_submit_button("Calculate settlement", type="primary", width="stretch")
        if submitted:
            try:
                inputs = SettlementInput(delivered=delivered, withdrawn=withdrawn, unit=unit,
                                         buy_eur_mwh=buy, sell_eur_mwh=sell)
                save_assumptions(state.model_copy(update={"settlement": inputs}))
            except ValidationError as error:
                details = ", ".join(str(issue["loc"][0]).replace("_", " ") for issue in error.errors())
                st.error(f"Check {details}. The latest saved calculation is shown.")
    with output, st.container(border=True, key="panel_settlement_output"):
        heading("Settlement calculation")
        result = settle(inputs)
        left, right = st.columns(2)
        with left:
            kpi("User imbalance", result.imbalance_mwh, "MWh", "Delivered − withdrawn", 2)
        with right:
            kpi("Signed user cash flow", result.cash_flow_eur, "EUR",
                result.direction.title() if result.direction else "Exposure unavailable", 2,
                "rose" if result.direction == "charge" else "teal")
        rows([("Delivered energy", _readout(result.delivered_mwh, "MWh")),
              ("Withdrawn energy", _readout(result.withdrawn_mwh, "MWh")),
              ("Applied side", result.side.title() if result.side else "Unavailable"),
              ("Applied price", _readout(result.price_eur_mwh, "EUR/MWh"))])
        st.caption("Cash flow = imbalance × applicable price. Negative cash flow is a charge. "
                   "Positive cash flow is a credit. Decimal rounding occurs at the final cent.")
        for issue in result.problems:
            st.warning(issue)
        with st.expander("Calculation source"):
            evidence([SETTLEMENT_NOTE])


def _readout(number, unit: str) -> str:
    return "Unavailable" if number is None else f"{number:,.2f} {unit}"


def _scenario_panel() -> None:
    state = assumptions()
    changes = state.stress
    data = fixture()
    facts = MarketContext(data, state.model, utc_now()).facts
    saved = st.session_state.get("scenario_case")
    case = ScenarioCase.model_validate(saved or facts)
    form, output = st.columns([1, 1.25], gap="medium")
    with form, st.container(border=True, key="panel_scenario_input"):
        heading("Aggregate stress inputs", kind_tag(Kind.SIMULATION))
        st.caption(f"Initial baseline from the offline fixture · {facts['label']}.")
        with st.form("scenario_form", border=False):
            a, b = st.columns(2)
            with a:
                demand = st.number_input("Baseline demand (GWh)", min_value=0.0, value=float(case.demand_gwh), step=10.0)
                storage = st.number_input("Storage contribution (GWh)", min_value=0.0,
                                          value=float(case.storage_gwh) if case.storage_gwh is not None else None)
                demand_pct = st.number_input("Demand change (%)", -100.0, 300.0, float(changes.demand_pct))
                storage_pct = st.number_input("Storage change (%)", -100.0, 300.0, float(changes.storage_pct))
            with b:
                supply = st.number_input("Baseline total supply (GWh)", min_value=0.0, value=float(case.supply_gwh), step=10.0)
                price = st.number_input("Reference price (EUR/MWh)",
                                        value=float(case.price_eur_mwh) if case.price_eur_mwh is not None else None)
                supply_pct = st.number_input("Non-storage supply change (%)", -100.0, 300.0, float(changes.supply_pct))
                price_delta = st.number_input("Price change (EUR/MWh)", -1000.0, 1000.0, float(changes.price_delta_eur_mwh))
            submitted = st.form_submit_button("Compare scenario", type="primary", width="stretch")
        if submitted:
            try:
                candidate = ScenarioCase(demand_gwh=demand, supply_gwh=supply, storage_gwh=storage, price_eur_mwh=price)
                updated = ScenarioInput(demand_pct=demand_pct, supply_pct=supply_pct, storage_pct=storage_pct,
                                        price_delta_eur_mwh=price_delta)
                scenario(candidate, updated)
                case, changes = candidate, updated
                st.session_state["scenario_case"] = case.model_dump(mode="json")
                save_assumptions(state.model_copy(update={"stress": changes}))
            except ValueError as error:
                st.error(str(error))
    with output, st.container(border=True, key="panel_scenario_output"):
        heading("Baseline and stress")
        base = scenario(case, ScenarioInput(demand_pct=0))
        stress = scenario(case, changes)
        table = pd.DataFrame([
            {"Metric": label, "Baseline": _readout(getattr(base, field), unit),
             "Stress": _readout(getattr(stress, field), unit)}
            for label, field, unit in (
                ("Demand", "demand_gwh", "GWh"), ("Total supply", "supply_gwh", "GWh"),
                ("Storage component", "storage_gwh", "GWh"), ("Coverage", "coverage_pct", "%"),
                ("Simplified imbalance", "imbalance_gwh", "GWh"), ("Gap value", "gap_value_eur", "EUR"),
            )
        ])
        st.dataframe(table, hide_index=True, width="stretch")
        if stress.gap_value_eur is not None:
            kpi("Indicative gap-value change", stress.gap_value_eur - base.gap_value_eur, "EUR", "Stress − baseline", 0)
        st.caption("Storage is already included in supply. Gap value is aggregate imbalance × reference price in EUR/MWh.")
        st.caption("Saved stress adjustments also apply in Operations. Workflows use the selected dataset’s baseline.")


def balancing() -> None:
    header("Balancing & settlement", f'{kind_tag(Kind.SIMULATION)} <span>Participant settlement and aggregate stress</span>')
    participant, aggregate = st.tabs(["Participant settlement", "Aggregate scenarios"])
    with participant:
        _settlement_panel()
    with aggregate:
        _scenario_panel()


def _sync_uploads() -> None:
    files = st.session_state.get("reg_upload") or []
    st.session_state["pdf_uploads"] = tuple((item.name, item.getvalue()) for item in files[:MAX_DOCUMENTS])


def _reg_register() -> None:
    filters = ("All findings", "High", "Medium", "Info")
    severity = st.selectbox("Severity", filters, key="reg_severity")
    cases = [entry for entry in REGISTER if severity == filters[0] or entry.finding.severity == severity.lower()]
    st.dataframe(
        [{"Finding": case.finding.title, "Severity": case.finding.severity.title(),
          "Classification": case.finding.category, "Edition review": case.review} for case in cases],
        hide_index=True, width="stretch", height=40 + 36 * len(cases),
    )
    title = st.selectbox("Inspect finding", [case.finding.title for case in cases], key="reg_finding")
    case = next(entry for entry in cases if entry.finding.title == title)
    with st.container(border=True, key="panel_reg_finding"):
        heading(case.finding.title, chip(case.finding.severity.upper(), case.finding.severity))
        st.write(case.finding.detail)
        st.caption(case.review)
        evidence(case.finding.citations)


def _reg_query(docs) -> None:
    kind = st.radio("Research action", ["Ask a question", "Search documents"], horizontal=True)
    available = ["All indexed material", *docs.documents]
    with st.form("reg_ask_form"):
        document = st.selectbox("Document", available, disabled=kind == "Ask a question")
        query = st.text_input("Question or words to locate", placeholder="How does the Network Code define commercial balancing?",
                              max_chars=600)
        submitted = st.form_submit_button("Ask regulatory analyst" if kind == "Ask a question" else "Find evidence", type="primary")
    if submitted and not query.strip():
        st.warning("Enter a question or search term.")
    if submitted and query.strip():
        if kind == "Search documents":
            found = docs.search(query, document=None if document == available[0] else document)
            st.session_state["reg_answer"] = (query, None, [hit.citation for hit in found], None, None)
        else:
            result = regulation_result(docs, RegulationArguments(query=query))
            interpretation, warning = None, None
            model = reasoner()
            if model and result.evidence:
                try:
                    interpretation, _ = model.interpret(query, {Agent.REGULATORY: result})
                except Exception as error:
                    LOG.warning("Regulatory interpretation unavailable (%s)", type(error).__name__)
                    warning = "Model unavailable. The cited evidence is shown below."
            st.session_state["reg_answer"] = (query, result.summary, result.evidence, interpretation, warning)
    answer = st.session_state.get("reg_answer")
    if answer:
        objective, summary, citations, narrative, warning = answer
        with st.container(border=True, key="panel_reg_answer"):
            heading("Retrieved evidence", chip(f"{len(citations)} REFERENCES"))
            st.text(objective)
            if summary:
                st.text(summary)
            if warning:
                st.warning(warning)
            if narrative:
                st.caption("Model interpretation of the cited editions · human review")
                st.text(narrative)
            if citations:
                evidence(citations)
            else:
                st.info("No supporting passage was found. Try a phrase from the document or upload a searchable edition.")


def _reg_explorer(docs) -> None:
    if not docs.documents:
        st.info("Load a searchable PDF to open the original pages. Reviewed edition notes are available in the register.")
        return
    selected = st.selectbox("PDF document", list(docs.documents), key="reg_doc")
    document = docs.documents[selected]
    # The document itself provides the page numbers, including covers and contents.
    page = st.number_input("PDF page", min_value=1, max_value=document.pages, step=1, value=1,
                           key=f"reg_page_{document.digest[:10]}")
    st.download_button("Download local PDF", document.data, file_name=document.name, mime="application/pdf",
                       icon=":material/download:")
    if st.button("Open PDF page", type="primary", key="reg_open_page"):
        st.session_state["opened_pdf"] = (document.digest, int(page))
    if st.session_state.get("opened_pdf") == (document.digest, int(page)):
        st.image(document.render(int(page)), caption=f"{selected} · PDF p. {page}", width=690)
    with st.expander("Edition fingerprint"):
        st.code(document.digest, language=None)


def regulatory() -> None:
    header("Regulatory intelligence", '<span>Reviewed reference editions · current applicability unverified</span>')
    left, right = st.columns([1.65, 1], gap="medium")
    with left:
        st.file_uploader("Add searchable PDFs", type=["pdf"], accept_multiple_files=True, key="reg_upload",
                         on_change=_sync_uploads)
    docs = library()
    with right, st.container(border=True, key="panel_reg_library"):
        heading("Document library", chip(f"{len(docs.documents)} PDFS"))
        if docs.documents:
            rows((title, f"{pdf.pages} pages") for title, pdf in docs.documents.items())
        else:
            st.caption("Reviewed edition notes are available offline.")
        for warning in docs.errors:
            st.warning(warning)
    register, ask, explorer = st.tabs(["Anomaly register", "Search & ask", "Evidence explorer"])
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
    heading("Human review queue", chip(f"{sum(f.id not in reviewed for f in queue)} OPEN", "review"))
    if not queue:
        st.caption("No findings require review in this run.")
        return
    labels = {f.id: f"{'Reviewed' if f.id in reviewed else f.severity.title()} · {f.title}" for f in queue}
    key = st.selectbox("Finding", list(labels), format_func=labels.__getitem__, key=f"review_item_{report.id}")
    finding = next(f for f in queue if f.id == key)
    st.caption(finding.category)
    st.text(finding.detail)
    evidence(finding.citations)
    if finding.id in reviewed:
        st.caption(f"Acknowledged {local_time(datetime.fromisoformat(reviewed[finding.id]))}")
    elif st.button("Acknowledge finding", key=f"review_{report.id}_{finding.id}", icon=":material/check:"):
        try:
            database().acknowledge(report.id, finding.id)
            st.rerun()
        except sqlite3.Error:
            LOG.exception("Unable to acknowledge finding")
            st.error("The finding could not be saved to local history.")


def _report_panel(report: Run) -> None:
    reviewed = database().reviewed(report.id)
    main, side = st.columns([1.9, 1], gap="medium")
    with main, st.container(border=True, key="panel_ops_summary"):
        heading("Executive summary", chip(report.mode, "ok" if report.mode == "LLM-assisted" else ""))
        rows([("Dataset", report.source.name), ("Finished", local_time(report.finished_at)), ("Run ID", report.id[:12])])
        for warning in report.warnings:
            st.warning(warning)
        for agent in Agent:
            if agent in report.results:
                result = report.results[agent]
                st.markdown(f"**{AGENT_LABELS[agent]}**")
                st.text(result.summary)
        if report.interpretation:
            st.caption("Model interpretation · human review")
            st.text(report.interpretation)
            st.caption("Tools referenced · " + ", ".join(AGENT_LABELS[agent] for agent in report.interpretation_sources))
        a, b = st.columns(2)
        suffix = report.id[:10]
        with a:
            payload = {**report.model_dump(mode="json"), "acknowledged_findings": reviewed}
            st.download_button("Download JSON", json.dumps(payload, ensure_ascii=False, indent=2),
                               f"gasops-{suffix}.json", mime="application/json", icon=":material/download:", width="stretch")
        with b:
            st.download_button("Download Markdown", markdown(report, reviewed), f"gasops-{suffix}.md",
                               mime="text/markdown", icon=":material/download:", width="stretch")
    with side, st.container(border=True, key="panel_ops_review"):
        _review_queue(report, reviewed)

    with st.container(border=True, key="panel_ops_trace"):
        conflict = any(item.category == "Independent validation" for item in report.findings)
        verification = chip("CONFLICT DETECTED", "high") if conflict else chip("VALIDATION COMPLETE", "ok")
        heading("Agent execution and evidence", verification if report.validated_at else "")
        with st.expander("Run inputs and data fingerprint"):
            st.code(report.input_sha256, language=None)
            st.json(report.assumptions, expanded=False)
        for agent in Agent:
            if agent not in report.results:
                continue
            item = report.results[agent]
            step = report.steps[agent]
            with st.expander(f"{AGENT_LABELS[agent]} · {STATUS[step.status][0]}"):
                if step.started_at and step.finished_at:
                    elapsed = (step.finished_at - step.started_at).total_seconds()
                    st.caption(f"{local_time(step.started_at)} · {elapsed * 1000:,.0f} ms")
                st.text(item.summary)
                evidence(item.evidence)
                if item.values:
                    st.json(item.values, expanded=False)
                for finding in item.findings:
                    st.caption(f"{finding.severity.upper()} · {finding.title}. {finding.detail}")


def operations() -> None:
    top, controls = st.container(), st.container()
    with controls:
        selection = source_filters("ops", lookback=False)
    with top:
        started = header("AI Operations Centre", selection.meta, "Run AI Market Analysis", disabled=selection.bundle is None)
    flow, analyst = st.columns([1, 1.1], gap="medium")
    with flow, st.container(border=True, key="panel_ops_flow"):
        heading("Supervisor workflow")
        st.html('<div class="gas-flow-track"><span>Data quality</span><b>→</b><span>Parallel agents</span>'
                '<b>→</b><span>Validation</span><b>→</b><span>Report</span></div>')
        step_panel = st.empty()
    with analyst, st.container(border=True, key="panel_ops_query"):
        heading("Ask the analyst")
        st.selectbox("Example question", ["Choose an example", *QUESTIONS], key="ops_example", on_change=_example_question)
        with st.form("ops_question_form", border=False):
            question = st.text_area("Analytical request", height=84, key="ops_question", max_chars=600,
                                    placeholder="Generate a daily gas market operations briefing.")
            asked = st.form_submit_button("Run question", type="primary", disabled=selection.bundle is None)
    report = None
    if started:
        report = launch(selection, full=True)
    elif asked and question.strip():
        report = launch(selection, question)
    elif asked:
        st.warning("Enter an analytical request.")
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
            "Execution history", list(entries), key="ops_history",
            format_func=lambda item: f"{local_time(entries[item].started_at)} · {entries[item].question[:65]}",
        )
        selected = entries[chosen]
        _report_panel(selected)
    step_panel.html(steps(selected, grid=True))
