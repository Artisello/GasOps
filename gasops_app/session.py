"""Streamlit session state, source selection and workflow execution."""

from dataclasses import dataclass
from html import escape
import logging
import os
from pathlib import Path
import sqlite3

import streamlit as st

from .agents import Assumptions, MarketContext
from .data import Bundle, ROOT, ROME, jrc_archive, synthetic
from .forecast import MODEL_CHOICES, ModelChoice
from .italiano import MODALITA, MODELLI
from .llm import CompatibleReasoner, configuration
from .mensile import load_monthly
from .entsog import load as load_daily
from .models import Run, utc_now
from .public_data import SourceUnavailable
from .regulatory import Library, read_local_pdfs
from .store import Store
from .visuals import chip, kind_tag, local_time, steps
from .workflow import DAILY_BRIEFING, run_workflow

LOG = logging.getLogger(__name__)
DEMO, PUBLIC, ARCHIVE = "Dati di esempio · giornalieri", "Eurostat + ARERA · mensili", "JRC · archivio giornaliero"
DAILY = "ENTSOG · prelievi SRG giornalieri"
SOURCE_CHOICES = (PUBLIC, DAILY, ARCHIVE, DEMO)
RUN_ANALYSIS = "Avvia analisi di mercato AI"
SOURCE_LABELS = {
    PUBLIC: "Italia · bilancio mensile (Eurostat + ARERA)",
    DAILY: "Italia · prelievi giornalieri (ENTSOG/SRG)",
    ARCHIVE: "Archivio giornaliero 2015–2021 (JRC)",
    DEMO: "Simulazione · dati di esempio",
}
ENTSOG_METADATA_NOTE = ("ENTSOG: totale dichiarato discordante; griglia giorno-settore richiesta verificata integralmente. "
                        "Completezza delle eventuali revisioni non certificata.")


def source_notices(warning: str | None) -> tuple[str, str]:
    # Only the exact known informational notice is demoted; any other
    # warnings, including partial history and stale cache, stay visible.
    if not warning:
        return "", ""
    if ENTSOG_METADATA_NOTE not in warning:
        return warning, ""
    return warning.replace(ENTSOG_METADATA_NOTE, "").strip(), ENTSOG_METADATA_NOTE


@st.cache_resource(show_spinner=False)
def store(state_dir: str) -> Store:
    return Store(Path(state_dir) / "state.sqlite3")


def database() -> Store:
    return store(os.environ.get("GASOPS_STATE_DIR") or str(ROOT / ".gasops"))


@st.cache_data(show_spinner=False)
def fixture() -> Bundle:
    return synthetic()


@st.cache_data(show_spinner=False)
def archive() -> Bundle:
    return jrc_archive()


@st.cache_resource(show_spinner=False, max_entries=5)
def indexed_library(documents: tuple[tuple[str, bytes], ...]) -> Library:
    return Library(documents)


def library() -> Library:
    path = Path(os.environ.get("GASOPS_PDF_DIR") or ROOT / "data" / "regulatory")
    uploads = st.session_state.get("pdf_uploads", ())
    with st.spinner("Indicizzazione dei documenti…", show_time=False):
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
    mode = st.selectbox("Modalità di analisi", modes, format_func=lambda value: MODALITA.get(value, value),
                        key="execution_mode")
    if config and mode == config.model:
        st.caption("Modello locale con accesso agli strumenti" if config.local else
                   "L’endpoint configurato riceve le domande, le fonti selezionate e i risultati degli strumenti.")
    else:
        st.caption("Calcoli locali senza modello")
    st.html('<div class="sidebar-caption">Europe/Rome · Prototipo indipendente</div>')


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
    model: ModelChoice
    periods: int
    bundle: Bundle | None

    @property
    def meta(self) -> str:
        if not self.bundle:
            return chip("FONTE NON DISPONIBILE", "failed") + f" <span>{escape(self.name)}</span>"
        origin = self.bundle.origin
        grain = ("SRG · GWh/giorno gas" if self.name == DAILY else "Italia · GWh/giorno gas") if origin.grain == "daily" else "Italia · GWh/mese"
        if origin.latest_period:
            grain += f" · ultimo periodo {origin.latest_period}"
        if origin.archive:
            grain += " · 2015–2021"
        return f"{kind_tag(origin.kind)} <span>{grain}</span>"


def _choose_source(page: str, source: str) -> None:
    st.session_state["selected_source"] = source
    st.session_state[f"{page}_dataset"] = source


def source_filters(page: str, *, lookback: bool = True) -> Selection:
    ctrl = st.columns([3, 1.35, 1.3] if lookback else [3, 1.3], vertical_alignment="bottom")
    stored = st.session_state.get("selected_source", PUBLIC)
    with ctrl[0]:
        name = st.selectbox("Fonte dati", SOURCE_CHOICES, index=SOURCE_CHOICES.index(stored) if stored in SOURCE_CHOICES else 0,
                            key=f"{page}_dataset", format_func=SOURCE_LABELS.__getitem__,
                            help="Scegli il perimetro: dati mensili nazionali, prelievi SRG giornalieri, archivio o simulazione.")
    st.session_state["selected_source"] = name
    grain = "monthly" if name == PUBLIC else "daily"
    periods = 90 if grain == "daily" else 24
    if lookback:
        with ctrl[1]:
            windows = {"30 giorni": 30, "90 giorni": 90, "180 giorni": 180, "1 anno": 365} if grain == "daily" else {
                "12 mesi": 12, "24 mesi": 24, "36 mesi": 36, "60 mesi": 60,
            }
            window = st.selectbox("Periodo del grafico", tuple(windows), index=1, key=f"{page}_window_{grain}")
            periods = windows[window]
    with ctrl[-1]:
        if name in (PUBLIC, DAILY):
            refresh = st.button("Aggiorna fonti", icon=":material/refresh:", width="stretch", key=f"{page}_refresh")
        else:
            refresh = False
            st.caption("Giorno gas dalle 06:00 locali")
    with st.expander("Impostazioni avanzate · modello previsionale"):
        previous = assumptions()
        model = st.selectbox("Modello previsionale", MODEL_CHOICES, index=MODEL_CHOICES.index(previous.model),
                             format_func=MODELLI.__getitem__, key=f"{page}_model",
                             help="Automatico usa il modello con l’errore medio più basso sugli stessi periodi storici.")
        save_assumptions(previous.model_copy(update={"model": model}))
    st.caption({
        PUBLIC:"Bilancio nazionale mensile e prezzo medio PSV. La disponibilità è contabile, non fisica.",
        DAILY:"Somma dei prelievi SRG di distribuzione, industria e termoelettrico. Non è il totale nazionale; non include offerta o prezzi.",
        ARCHIVE:"Serie pubblica storica 2015–2021. Le proiezioni non descrivono il mercato di oggi.",
        DEMO:"Dati interamente sintetici, utilizzabili solo per provare i calcoli."
    }[name])
    st.session_state[f"{page}_source_note"] = ""
    if name == DEMO:
        bundle = fixture()
    elif name == ARCHIVE:
        bundle = archive()
    else:
        try:
            if name == DAILY:
                with st.spinner("Aggiornamento ENTSOG (finestre mensili; primo caricamento più lungo)…"):
                    bundle, warning = load_daily(database(), refresh=refresh)
            else:
                with st.spinner("Caricamento dei dati Eurostat e ARERA…"):
                    bundle, warning = load_monthly(database(), refresh=refresh)
            visible_warning, note = source_notices(warning)
            if visible_warning:
                st.warning(visible_warning)
            if note:
                st.session_state[f"{page}_source_note"] = note
                with st.expander("Nota tecnica ENTSOG"):
                    st.caption(note)
        except SourceUnavailable as error:
            st.error(str(error))
            if name == DAILY:
                st.button("Apri Eurostat + ARERA", on_click=_choose_source, args=(page, PUBLIC), key=f"{page}_monthly")
            left, right = st.columns(2)
            left.button("Apri archivio pubblico JRC", on_click=_choose_source, args=(page, ARCHIVE), key=f"{page}_archive")
            right.button("Usa dati di esempio", on_click=_choose_source, args=(page, DEMO), key=f"{page}_demo")
            bundle = None
    st.session_state["active_bundle"] = bundle
    return Selection(name, model, periods, bundle)


@st.cache_resource(show_spinner=False, max_entries=8)
def preview(fingerprint: str, source_json: str, model: ModelChoice, today: str, _bundle: Bundle) -> MarketContext:
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
    status = st.status("Supervisore in esecuzione", expanded=True)
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
        status.update(label="Verifica i dati di ingresso", state="error")
        status.write(str(error))
        return None
    st.session_state["last_run"] = report
    try:
        database().save(report)
    except (OSError, RuntimeError, sqlite3.Error):
        LOG.exception("Could not persist GasOps run")
        st.warning("Esecuzione disponibile in questa sessione. Salvataggio nello storico locale non riuscito.")
    state = "error" if any(step.status == "failed" for step in report.steps.values()) else "complete"
    status.update(label=f"{MODALITA[report.mode]} · {local_time(report.finished_at)}", state=state, expanded=False)
    return report
