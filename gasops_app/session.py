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
from .supervisor import ModelUnavailable
from .mensile import load_monthly
from .entsog import load as load_daily
from .models import Agent, Kind, Run, utc_now
from .public_data import SourceUnavailable
from .regulatory import Library, read_local_pdfs
from .store import Store
from .visuals import chip, info, kind_tag, local_time, steps
from .workflow import DAILY_BRIEFING, run_workflow, plan
from .country_analysis import requested_country, country_report, direct_market_question
from .market import demand_trend_question
from .assistant_sources import requested_sources, add_price_source, complete_requirements, MARKET

LOG = logging.getLogger(__name__)
DEMO, PUBLIC, ARCHIVE = "Dati di esempio · giornalieri", "Eurostat + ARERA · mensili", "JRC · archivio giornaliero"
DAILY = "ENTSOG · prelievi SRG giornalieri"
SOURCE_CHOICES = (PUBLIC, DAILY, ARCHIVE, DEMO)
RUN_ANALYSIS = "Genera bollettino AI"
SOURCE_LABELS = {
    PUBLIC: "Italia · consumi e prezzi mensili (Eurostat + ARERA)",
    DAILY: "Rete SRG · prelievi giornalieri (ENTSOG)",
    ARCHIVE: "Archivio 2015–2021 (JRC)",
    DEMO: "Simulazione · dati di esempio",
}
ENTSOG_METADATA_NOTE = ("ENTSOG: totale dichiarato discordante; griglia giorno-settore richiesta verificata integralmente. "
                        "Completezza delle eventuali revisioni non certificata.")


def source_notices(warning: str | None) -> tuple[str, str]:
    # Only the exact known informational notice is demoted; any other
    # warnings, including partial history and stale cache, stay visible.
    if not warning:
        return "", ""
    notes = (ENTSOG_METADATA_NOTE,
             "ENTSOG: totale dichiarato discordante; verificati i singoli valori ricevuti. Completezza delle eventuali revisioni non certificata.")
    found = []
    for note in notes:
        if note in warning:
            found.append(note)
            warning = warning.replace(note, "")
    return warning.strip(), " ".join(found)


def store(state_dir: str) -> Store:
    # Store owns no persistent connection. Recreate the lightweight wrapper so
    # Streamlit hot reload cannot reuse instances of an older Store class.
    # SQLite state and request counters remain on disk; schema is idempotent.
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
        local = read_local_pdfs(path)
        # The process-wide resource cache is for server-provided public PDFs only.
        # Never include session uploads in its keys, arguments or cached results.
        if uploads:
            return Library((*local, *uploads))
        return indexed_library(local)


def assumptions() -> Assumptions:
    return Assumptions.model_validate(st.session_state.get("assumptions", {}))


def save_assumptions(assumed: Assumptions) -> None:
    st.session_state["assumptions"] = assumed.model_dump(mode="json")


def _configuration():
    try:
        return configuration(st.secrets)
    except (FileNotFoundError,KeyError):
        return configuration()


def _reserve_remote_request() -> bool:
    # Never permit a remote call if the persisted budget cannot be enforced.
    try:
        return database().reserve_llm()
    except (AttributeError, OSError, sqlite3.Error, RuntimeError):
        raise ModelUnavailable("Contatore AI non disponibile: richiesta bloccata.") from None


def ai_controls(*, prefix="sidebar") -> None:
    config, problem = None, None
    try:
        config = _configuration()
    except ValueError as error:
        problem = str(error)
    if problem:
        st.warning(problem)
    if not config:
        st.caption("AI non configurata · report locali disponibili")
    usage = None
    budget_ready = True
    if config and not config.local:
        try:
            db = database()
            if not callable(getattr(db, "reserve_llm", None)):
                raise AttributeError("Missing quota reservation")
            usage = db.llm_usage()
        except (AttributeError, OSError, sqlite3.Error, RuntimeError) as error:
            budget_ready = False
            LOG.warning("AI budget unavailable (%s)", type(error).__name__)
            if prefix == "sidebar":
                st.warning("Contatore AI non disponibile. I calcoli locali restano utilizzabili.")
    with st.expander("Connessione e limiti AI", expanded=False):
        if config and st.session_state.get("execution_mode")=="Deterministic":
            st.caption("Modello disponibile: attivalo dalla modalità di analisi o dall’assistente.")
        if not config:
            st.write("Per Groq Cloud, imposta GROQ_API_KEY nei Secrets di Streamlit; "
                     "oppure i tre campi GASOPS_LLM_URL, GASOPS_LLM_MODEL, GASOPS_LLM_API_KEY.")
            st.code('GROQ_API_KEY = "LA_TUA_CHIAVE"',language="toml")
            st.caption("Groq Cloud non è Grok di xAI. Non inserire la chiave qui o in GitHub.")
            return
        st.caption(("Groq Cloud" if config.groq else "Ollama locale" if config.local else "Provider remoto")+" · "+config.model)
        if not config.local:
            if budget_ready:
                st.caption(f"Richieste interne ultime 24 h: {usage}/30 · max 4/min. "
                           "Non è il saldo della quota del provider.")
            else:
                st.caption("Contatore non disponibile: richieste AI bloccate. Se persiste, riavvia l’app.")
        if st.button("Test connessione AI",key=prefix+"_llm_probe",disabled=not budget_ready):
            try:
                CompatibleReasoner(config,reserve=None if config.local else _reserve_remote_request).probe()
                st.session_state["llm_probe_result"]=(config.model,True,"Connessione e risposta JSON con riferimento verificate (test sintetico).")
            except ModelUnavailable as error:
                st.session_state["llm_probe_result"]=(config.model,False,str(error))
            except Exception:
                st.session_state["llm_probe_result"]=(config.model,False,"Connessione o risposta non valida.")
        probe=st.session_state.get("llm_probe_result")
        if probe and probe[0]==config.model:
            (st.success if probe[1] else st.warning)(probe[2])


def sidebar() -> None:
    config=None
    try:
        config=_configuration()
    except ValueError:
        pass
    modes=["Deterministic",config.model] if config else ["Deterministic"]
    # A configured model is the initial mode; an operator can still switch to local calculations.
    st.selectbox("Modalità di analisi",modes,index=1 if config else 0,
                 format_func=lambda value:"Calcoli senza AI" if value=="Deterministic" else value,key="execution_mode")
    ai_controls()
    with st.expander("Fonti bollettino",expanded=False):
        st.checkbox("GIE · stoccaggi, GNL, UMM",value=True,key="briefing_gie",
                    help="Consulta AGSI+ e ALSI Italia e IIP al lancio del report. Se usi un modello remoto, invia solo indicatori pubblici con attribuzione, non record UMM originali.")
        import os
        weather_allowed=os.getenv("IGOR_WEATHER_ENABLED","1").lower() not in ("0","false","no","off")
        st.checkbox("Meteo · Open-Meteo (demo non commerciale)",value=weather_allowed,key="briefing_weather",disabled=not weather_allowed,
                    help="Attivo di default nel prototipo: HDD e previsioni, con cache. Disattivabile qui.")
        st.caption("Solo dati pubblici autorizzati alla condivisione.")
    if config and not config.local:
        st.caption("AI remota: solo dati pubblici. I PDF richiedono consenso separato.")


def ai_configured() -> bool:
    try:
        return _configuration() is not None
    except ValueError:
        return False


def reasoner() -> CompatibleReasoner | None:
    try:
        config = _configuration()
    except ValueError:
        return None
    if config and st.session_state.get("execution_mode",config.model)==config.model:
        return CompatibleReasoner(config,reserve=None if config.local else _reserve_remote_request)
    return None


def activate_ai(model_name: str) -> None:
    """Explicit widget callback, runs before the sidebar is rebuilt."""
    try:
        config = _configuration()
    except ValueError:
        return
    if config and config.model == model_name:
        st.session_state["execution_mode"] = config.model


def ai_activation_panel(*, prefix: str) -> None:
    """Allow reactivation after switching to local calculations; no network request here."""
    try:
        config = _configuration()
    except ValueError:
        config = None
    if config:
        st.info("Attiva l’AI per fare domande.")
        if not config.local:
            st.caption("Domande e aggregati pubblici saranno inviati al provider esterno. Nessun dato riservato.")
        st.button("Attiva AI · "+config.model, key=prefix+"_activate_ai",type="primary",
                  on_click=activate_ai,args=(config.model,))
    else:
        st.info("AI non configurata. Usa i report locali o configura il modello nelle impostazioni.")


def analysis_label() -> str:
    return RUN_ANALYSIS if reasoner() else "Genera bollettino di mercato"


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


def market_scope(name: str) -> tuple[str,str]:
    """Explicit scope, never infer the geography from a display title."""
    return {
        PUBLIC:("Italia","Bilancio nazionale mensile"),
        DAILY:("Italia · rete Snam (SRG)","Prelievi giornalieri · non totale nazionale"),
        ARCHIVE:("Italia · archivio storico","Consumi giornalieri 2015–2021 · non dati attuali"),
        DEMO:("Simulazione","Dati fittizi · nessuna copertura geografica reale"),
    }[name]


def source_filters(page: str, *, lookback: bool = True) -> Selection:
    ctrl = st.columns([3, 1.35, 1.3, 1.15] if lookback else [3, 1.3, 1.15], vertical_alignment="bottom")
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
            window = st.selectbox("Periodo", tuple(windows), index=1, key=f"{page}_window_{grain}")
            periods = windows[window]
    with ctrl[-2]:
        if name in (PUBLIC, DAILY):
            refresh = st.button("Aggiorna dati", icon=":material/refresh:", width="stretch", key=f"{page}_refresh")
        else:
            refresh = False
            pass
    with ctrl[-1]:
        with st.popover("Opzioni",icon=":material/info:",width="stretch"):
            previous = assumptions()
            model = st.selectbox("Modello previsionale", MODEL_CHOICES, index=MODEL_CHOICES.index(previous.model),
                                 format_func=MODELLI.__getitem__, key=f"{page}_model",
                                 help="Automatico usa il modello con l’errore medio più basso sugli stessi periodi storici.")
            save_assumptions(previous.model_copy(update={"model": model}))
            st.write({
                PUBLIC:"Bilancio nazionale mensile e prezzo medio PSV. La disponibilità è contabile, non fisica.",
                DAILY:"Somma dei prelievi SRG di distribuzione, industria e termoelettrico. Non è il totale nazionale; non include offerta o prezzi.",
                ARCHIVE:"Serie pubblica storica 2015–2021. Le proiezioni non descrivono il mercato di oggi.",
                DEMO:"Dati sintetici, utilizzabili solo per provare i calcoli."
            }[name])
            st.caption("Il giorno gas inizia alle 06:00 locali.")
    if page!="market" and name in (ARCHIVE,DEMO):
        st.caption("Archivio storico · non mercato attuale" if name==ARCHIVE else "Dati sintetici · simulazione")
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
            st.warning("Fonte non disponibile. Riprova con Aggiorna dati.")
            with st.expander("Dettagli della fonte"):
                st.text(str(error))
            if name == DAILY:
                st.button("Apri Eurostat + ARERA", on_click=_choose_source, args=(page, PUBLIC), key=f"{page}_monthly")
            left, right = st.columns(2)
            left.button("Apri archivio pubblico JRC", on_click=_choose_source, args=(page, ARCHIVE), key=f"{page}_archive")
            # Simulation remains an explicit selection in the source menu.
            from .live_sources import BUNDLES
            bundle=st.session_state.get(BUNDLES,{}).get("daily" if name==DAILY else "monthly")
            if bundle is not None:
                # Preserve original timestamp/fingerprint and propagate the failed
                # refresh to every consumer, including forecasts/reports.
                bundle=Bundle(bundle.rows,bundle.origin.model_copy(update={"cached":True,"refresh_failed":True}),
                              bundle.fingerprint)
                st.warning("Ultimo dato valido della stessa fonte · aggiornamento non riuscito.")
    if bundle is not None and name in (PUBLIC,DAILY) and not bundle.origin.refresh_failed:
        from .live_sources import remember_bundle
        remember_bundle(st.session_state,bundle,utc_now())
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


def briefing_run() -> Run | None:
    """Only the last full report from this session, not another visitor's history."""
    report=st.session_state.get("last_briefing")
    if report:
        return report
    previous=st.session_state.get("last_run")
    if previous and previous.question==DAILY_BRIEFING and previous.finished_at:
        return previous
    return None


def launch(selection: Selection, question: str = DAILY_BRIEFING, *, full: bool = False,
           persist: bool = False, planned_only: bool = False, compact: bool = False,
           ai_policy: str = "selected") -> Run | None:
    if selection.bundle is None:
        return None
    if ai_policy not in ("selected","required","off"):
        raise ValueError("Modalità di analisi non valida.")
    model = None if ai_policy == "off" else reasoner()
    if ai_policy == "required" and model is None:
        raise ModelUnavailable("AI non attiva. Nessuna domanda eseguita.")
    country=requested_country(question) if not full else None
    if country:
        from .operational_sources import gie_key
        try:
            key=gie_key(st.secrets)
        except (FileNotFoundError,KeyError):
            key=gie_key()
        with st.spinner("Consultazione delle fonti del mercato richiesto…"):
            report=country_report(
                database(),question,country,selection.model,model,gie_key=key,
                include_gie=bool(st.session_state.get("briefing_gie",True)))
        st.session_state["last_run"]=report
        return report
    context = MarketContext(selection.bundle, selection.model, utc_now())
    status = st.status("Generazione del bollettino…" if full else "Analisi della domanda…", expanded=not compact)
    stage = status.empty()
    stage.html(steps(None, grid=True))
    try:
        requested=() if full else requested_sources(question)
        targets={call.agent for call in plan(question,False)} if requested else set()
        source_direct=bool(requested) and targets<={Agent.QUALITY,Agent.MARKET,Agent.FORECAST}
        direct=not full and (direct_market_question(question) or source_direct)
        narrow=direct and demand_trend_question(question) and set(requested)<=set(MARKET)
        docs = Library(include_notes=False) if direct else library()
        from .briefing_context import collect
        from .operational_sources import gie_key
        include_gie=bool(st.session_state.get("briefing_gie",True))
        from .weather_source import enabled,refresh as refresh_weather,STATE as WEATHER_STATE
        origin=selection.bundle.origin
        current_context=not origin.archive and origin.kind in (Kind.HISTORICAL,Kind.LIVE)
        include_gie=include_gie and current_context and not narrow
        include_weather=enabled(st.session_state) and current_context and not narrow
        public_context={}
        if include_gie or include_weather:
            try:
                key=gie_key(st.secrets) if include_gie else ""
            except (FileNotFoundError,KeyError):
                key=gie_key() if include_gie else ""
            with st.spinner("Consultazione delle fonti pubbliche selezionate…"):
                if include_weather:refresh_weather(st.session_state,database(),utc_now())
                public_context=collect(database(),context,utc_now(),key=key,include_gie=include_gie,include_weather=include_weather,
                    weather_snapshots=st.session_state.get(WEATHER_STATE,{}) if include_weather else None,
                    clock=utc_now)
        if current_context and (full or model is not None):
            from .briefing_market_sources import collect_market_sources
            from .terna_power import credentials
            try:
                terna=credentials(st.secrets)
            except (FileNotFoundError,KeyError):
                terna=credentials()
            with st.spinner("Lettura delle fonti di mercato e degli indicatori pubblici…"):
                public_context.update(collect_market_sources(database(),selection.bundle,utc_now(),
                    st.session_state,terna=terna,clock=utc_now,only=set(MARKET) if narrow else None))
        if current_context and model is not None and not full:
            add_price_source(public_context)
            complete_requirements(public_context,requested)
        requirements=requested if current_context and model is not None and not full else ()
        report = run_workflow(
            context, docs, assumptions(), question, full=full, reasoner=model,public_context=public_context,planned_only=planned_only or direct,
            source_requirements=requirements,
            notify=lambda run: stage.html(steps(run, grid=True)),
        )
    except ValueError as error:
        LOG.info("Invalid workflow request (%s)", type(error).__name__)
        status.update(label="Verifica i dati di ingresso", state="error")
        status.write(str(error))
        return None
    # Record why AI was not used on this run, not the state of a later rerun.
    if model is None:
        report.assumptions["ai_mode_reason"] = ("Modalità locale selezionata" if ai_policy=="off" or ai_configured()
                                               else "Modello AI non configurato o configurazione non valida")
    st.session_state["last_run"] = report
    if full:
        st.session_state["last_briefing"] = report
    # UI runs are session-only. Even an explicit caller must opt in on an
    # operator-controlled private deployment before writing a shared history.
    if persist and os.getenv("GASOPS_PRIVATE_RUN_HISTORY") == "1":
        try:
            database().save(report)
        except (OSError, RuntimeError, sqlite3.Error):
            LOG.exception("Could not persist GasOps run")
            st.warning("Esecuzione disponibile in questa sessione. Salvataggio nello storico locale non riuscito.")
    if not compact:
        for warning in report.warnings:
            st.warning(warning)
    state = "error" if any(step.status == "failed" for step in report.steps.values()) else "complete"
    status.update(label="Analisi completata" if state=="complete" else "Analisi con errori", state=state, expanded=False)
    return report
