"""Run typed tools, publish execution status and validate their shared results."""

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import logging
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from .models import AGENT_LABELS, Agent, Finding, Result, Run, utc_now

LOGGER = logging.getLogger(__name__)


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class Tool:
    description: str
    arguments: type[Arguments]
    invoke: Callable[[Arguments], Result]


@dataclass(frozen=True)
class Call:
    agent: Agent
    arguments: Arguments


class ModelUnavailable(RuntimeError):
    """Controlled, credential-free provider message."""


class Reasoner(Protocol):
    label: str

    def route(self, run: Run, tools: Mapping[Agent, Tool]) -> list[Call]: ...

    def review(self, run: Run, tools: Mapping[Agent, Tool]) -> list[Call]: ...

    def summarize(self, run: Run) -> tuple[str | None, list[Agent]]: ...


def _execute_batch(
    run: Run,
    calls: list[Call],
    tools: Mapping[Agent, Tool],
    notify: Callable[[Run], None],
) -> None:
    if not calls:
        return
    for call in calls:
        run.steps[call.agent].status = "queued"
    notify(run)
    with ThreadPoolExecutor(max_workers=min(6, len(calls))) as executor:
        pending = {}
        for call in calls:
            step = run.steps[call.agent]
            step.status = "running"
            step.started_at = utc_now()
            step.finished_at = None
            pending[executor.submit(tools[call.agent].invoke, call.arguments)] = call.agent
        notify(run)
        for future in as_completed(pending):
            agent = pending[future]
            try:
                result = future.result()
                if result.agent != agent:
                    raise ValueError("Agent identifier mismatch")
            except Exception:
                LOGGER.exception("GasOps tool failed for %s", agent)
                result = Result(
                    agent=agent, status="failed",
                    summary="Esecuzione non riuscita. I dettagli sono nel registro locale dell’app.",
                    findings=[Finding(
                        id=f"execution-{agent}", title=f"Errore nell’agente {AGENT_LABELS[agent]}",
                        severity="high", detail="Lo strumento non ha restituito risultati validi.",
                        category="Esecuzione",
                    )],
                )
            run.results[agent] = result
            run.steps[agent].status = result.status
            run.steps[agent].finished_at = utc_now()
            notify(run)


def _fallback(run: Run, stage: str, error: Exception) -> None:
    LOGGER.warning("Model %s failed (%s)", stage, type(error).__name__)
    run.mode = "Deterministic fallback"
    detail = " "+str(error) if isinstance(error,ModelUnavailable) else ""
    run.warnings.append(f"Modello non disponibile nella fase di {stage}.{detail} Il rapporto usa i risultati validati.")


def _gated_batch(run: Run, calls: dict[Agent, Call], tools: Mapping[Agent, Tool],
                 notify: Callable[[Run], None]) -> None:
    if Agent.QUALITY not in run.results and any(
        agent in calls for agent in (Agent.MARKET, Agent.FORECAST, Agent.SCENARIO)
    ):
        quality = calls.pop(Agent.QUALITY, Call(Agent.QUALITY, Arguments()))
        _execute_batch(run, [quality], tools, notify)
    _execute_batch(run, list(calls.values()), tools, notify)


def execute(
    run: Run,
    tools: Mapping[Agent, Tool],
    defaults: list[Call],
    required: set[Agent],
    validate: Callable[[Run], list[Finding]],
    notify: Callable[[Run], None],
    reasoner: Reasoner | None = None,
) -> Run:
    """Run the quality gate, bounded batches and a deterministic validation pass."""
    calls = {call.agent: call for call in defaults}
    summary_only = bool(reasoner and getattr(reasoner,"summary_only_full",False) and required==set(tools))
    if reasoner:
        run.mode, run.model = "LLM-assisted", reasoner.label
    if reasoner and not summary_only:
        try:
            proposed = {call.agent: call for call in reasoner.route(run, tools)}
            if not proposed:
                raise ValueError("No analytical tool was selected")
            calls = {**proposed, **{key: call for key, call in calls.items() if key in required}}
        except Exception as error:
            _fallback(run, "selezione degli strumenti", error)

    _gated_batch(run, calls, tools, notify)

    if reasoner and run.mode == "LLM-assisted" and not summary_only:
        try:
            followups = {
                call.agent: call for call in reasoner.review(run, tools)
                if call.agent not in run.results
            }
            _gated_batch(run, followups, tools, notify)
        except Exception as error:
            _fallback(run, "verifica degli strumenti", error)

    findings = [finding for result in run.results.values() for finding in result.findings]
    findings.extend(validate(run))
    run.validated_at = utc_now()
    run.findings = list({finding.id: finding for finding in findings}.values())
    summary = [run.results[agent].summary for agent in Agent if agent in run.results]
    review_count = sum(finding.severity in {"high", "medium"} for finding in run.findings)
    if review_count:
        summary.append(f"Revisione richiesta per {review_count} rilievi.")
    run.summary = " ".join(summary)

    if reasoner and run.mode == "LLM-assisted":
        try:
            run.interpretation, run.interpretation_sources = reasoner.summarize(run)
        except Exception as error:
            _fallback(run, "sintesi", error)

    run.finished_at = utc_now()
    notify(run)
    return run
