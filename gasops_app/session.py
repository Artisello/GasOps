"""Streamlit session state, source selection and workflow execution."""

from dataclasses import dataclass
from html import escape
import logging
import os
from pathlib import Path
import sqlite3

import streamlit as st

from .agents import Assumptions, MarketContext
from .data import Bundle, ROOT, ROME, synthetic
from .eurostat import SourceUnavailable, load
from .forecast import MODELS
from .llm import CompatibleReasoner, configuration
from .models import Run, utc_now
from .regulatory import Library, read_local_pdfs
from .store import Store
from .visuals import chip, kind_tag, local_time, steps
from .workflow import DAILY_BRIEFING, run_workflow

LOG = logging.getLogger(__name__)
DEMO, PUBLIC = "Italy · offline demo", "Eurostat · Italy"
SOURCE_CHOICES = (DEMO, PUBLIC)


@st.cache_resource(show_spinner=False)
def store(state_dir: str) -> Store:
    return Store(Path(state_dir) / "state.sqlite3")


def database() -> Store:
    return store(os.environ.get("GASOPS_STATE_DIR") or str(ROOT / ".gasops"))


@st.cache_data(show_spinner=False)
def fixture() -> Bundle:
    return synthetic()


@st.cache_resource(show_spinner=False, max_entries=5)
def indexed_library(documents: tuple[tuple[str, bytes], ...]) -> Library:
    return Library(documents)


def library() -> Library:
    path = Path(os.environ.get("GASOPS_PDF_DIR") or ROOT / "data" / "regulatory")
    uploads = st.session_state.get("pdf_uploads", ())
    with st.spinner("Indexing regulatory evidence...", show_time=False):
        return indexed_library((*read_local_pdfs(path), *uploads))


def assumptions() -> Assumptions:
    return Assumptions.model_validate(st.session_state.get("assumptions", {}))


def save_assumptions(assumed: Assumptions) -> None:
    st.session_state["assumptions"] = assumed.model_dump(mode="json")


def sidebar() -> None:
    st.html('<div class="gas-sidebar-foot"></div>')
    config = None
    try:
        config = configuration()
    except ValueError as error:
        st.caption(str(error))
    modes = ["Deterministic", config.model] if config else ["Deterministic"]
    mode = st.selectbox("Execution mode", modes, key="execution_mode")
    if config and mode == config.model:
        st.caption("Local model · tool calling" if config.local else
                   "The configured endpoint receives questions, selected evidence and tool results.")
    else:
        st.caption("Offline analytical tools")
    st.html('<div class="sidebar-caption">Europe/Rome · Independent proof of concept</div>')


def reasoner() -> CompatibleReasoner | None:
    try:
        config = configuration()
    except ValueError:
        return None
    if config and st.session_state.get("execution_mode") == config.model:
        return CompatibleReasoner(config)
    return None


@dataclass(frozen=True)
class Selection:
    name: str
    model: str
    periods: int
    bundle: Bundle | None

    @property
    def meta(self) -> str:
        if not self.bundle:
            return chip("SOURCE UNAVAILABLE", "failed") + f" <span>{escape(self.name)}</span>"
        origin = self.bundle.origin
        grain = "Italian gas days · GWh/day" if origin.grain == "daily" else "Italian inland consumption · GWh/month"
        return f"{kind_tag(origin.kind)} <span>{grain}</span>"


def source_filters(page: str, *, lookback: bool = True) -> Selection:
    ctrl = st.columns([2.25, 1.4, 1.8, 1.3] if lookback else [2.25, 1.8, 1.3], vertical_alignment="bottom")
    stored = st.session_state.get("selected_source", DEMO)
    with ctrl[0]:
        name = st.selectbox("Dataset", SOURCE_CHOICES, index=SOURCE_CHOICES.index(stored), key=f"{page}_dataset")
    st.session_state["selected_source"] = name
    grain = "daily" if name == DEMO else "monthly"
    periods = 90 if grain == "daily" else 24
    if lookback:
        with ctrl[1]:
            windows = {"30D": 30, "90D": 90, "180D": 180, "1Y": 365} if grain == "daily" else {
                "12M": 12, "24M": 24, "36M": 36, "60M": 60,
            }
            window = st.selectbox("Chart lookback", tuple(windows), index=1, key=f"{page}_window_{grain}")
            periods = windows[window]
    with ctrl[-2]:
        previous = assumptions()
        model = st.selectbox("Forecast model", MODELS, index=MODELS.index(previous.model), key=f"{page}_model")
        save_assumptions(previous.model_copy(update={"model": model}))
    with ctrl[-1]:
        if name == PUBLIC:
            refresh = st.button("Refresh source", icon=":material/refresh:", width="stretch", key=f"{page}_refresh")
        else:
            refresh = False
            rows_label = "06:00 local gas-day boundary"
            st.caption(rows_label)
    if name == DEMO:
        bundle = fixture()
    else:
        try:
            with st.spinner("Loading Eurostat observations..."):
                bundle = load(database(), refresh=refresh)
        except SourceUnavailable as error:
            st.error(str(error))
            bundle = None
    return Selection(name, model, periods, bundle)


@st.cache_resource(show_spinner=False, max_entries=8)
def preview(fingerprint: str, source_json: str, model: str, today: str, _bundle: Bundle) -> MarketContext:
    context = MarketContext(_bundle, model, utc_now())
    # Prime the shared preview; workflow runs construct a fresh context.
    _ = context.facts, context.projection
    return context


def preview_market(selection: Selection) -> MarketContext:
    bundle = selection.bundle
    return preview(bundle.fingerprint, bundle.origin.model_dump_json(), selection.model,
                   utc_now().astimezone(ROME).date().isoformat(), bundle)


def applicable_run(selection: Selection) -> Run | None:
    run = st.session_state.get("last_run")
    if not run or not selection.bundle:
        return None
    if run.input_sha256 != selection.bundle.fingerprint or run.assumptions.get("model") != selection.model:
        return None
    return run


def launch(selection: Selection, question: str = DAILY_BRIEFING, *, full: bool = False) -> Run | None:
    if selection.bundle is None:
        return None
    context = MarketContext(selection.bundle, selection.model, utc_now())
    status = st.status("Supervisor running", expanded=True)
    stage = status.empty()
    stage.html(steps(None, grid=True))
    try:
        docs = library()
        report = run_workflow(
            context, docs, assumptions(), question, full=full, reasoner=reasoner(),
            notify=lambda run: stage.html(steps(run, grid=True)),
        )
    except ValueError as error:
        LOG.info("Invalid workflow request (%s)", type(error).__name__)
        status.update(label="Check analysis inputs", state="error")
        status.write(str(error))
        return None
    st.session_state["last_run"] = report
    try:
        database().save(report)
    except (OSError, RuntimeError, sqlite3.Error):
        LOG.exception("Could not persist GasOps run")
        st.warning("The run is available in this session. Local history could not be saved.")
    state = "error" if any(step.status == "failed" for step in report.steps.values()) else "complete"
    status.update(label=f"{report.mode} · {local_time(report.finished_at)}", state=state, expanded=False)
    return report
