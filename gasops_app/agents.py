"""Agenti specializzati e strumenti analitici in sola lettura."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from functools import cached_property
import re
from typing import Literal

from pydantic import BaseModel, Field

from .data import Bundle, synthetic
from .finance import ScenarioCase, ScenarioInput, SettlementInput, scenario, settle
from .forecast import AUTOMATIC, MODELS, Forecast, ModelChoice, ModelName, Score, choose, compare, forecast
from .italiano import GRANULARITA, MODELLI, TIPI, data_it, numero
from .market import market_facts
from .models import Agent, Citation, Finding, Kind, Result
from .quality import Inspection, inspect
from .regulatory import Library, REGISTER, SETTLEMENT_NOTE
from .supervisor import Arguments, Tool


class Assumptions(BaseModel):
    model: ModelChoice = AUTOMATIC
    settlement: SettlementInput = Field(default_factory=SettlementInput)
    stress: ScenarioInput = Field(default_factory=ScenarioInput)
    cancellation_notice_days: int = Field(default=7, ge=0, le=366)


class MarketArguments(Arguments):
    comparison: Literal["native", "weekly"] = "native"


class RegulationArguments(Arguments):
    query: str = Field(max_length=600)
    review_notice: bool = False


class ScenarioArguments(Arguments):
    demand_pct: Decimal | None = Field(default=None, ge=-100, le=300)
    supply_pct: Decimal | None = Field(default=None, ge=-100, le=300)
    storage_pct: Decimal | None = Field(default=None, ge=-100, le=300)
    price_delta_eur_mwh: Decimal | None = Field(default=None, ge=-1000, le=1000)


@dataclass(frozen=True)
class MarketContext:
    bundle: Bundle
    model: ModelChoice
    as_of: datetime

    @cached_property
    def inspection(self) -> Inspection:
        return inspect(self.bundle, self.as_of)

    @cached_property
    def facts(self) -> dict:
        return market_facts(self.inspection.usable, self.bundle.origin.grain)

    @cached_property
    def projections(self) -> dict[ModelName, Forecast]:
        series = self.inspection.usable["demand_gwh"]
        return {model: forecast(series, self.bundle.origin.grain, model) for model in MODELS}

    @cached_property
    def forecast_scores(self) -> dict[ModelName, Score]:
        return compare(self.projections)

    @cached_property
    def projection(self) -> Forecast:
        return choose(self.projections, self.forecast_scores, self.model)


def _sources(context: MarketContext, *, price: bool = False) -> list[Citation]:
    origin = context.bundle.origin
    latest = context.facts.get("label", "periodo non disponibile")
    sources = [Citation(document=origin.name,
                        evidence=f"{TIPI[origin.kind]} · {GRANULARITA[origin.grain]} · {latest}. {origin.description}",
                        url=origin.url)]
    if price:
        sources.extend(Citation(document=feed.name, evidence=feed.description, url=feed.url)
                       for feed in origin.companions if "price_eur_mwh" in feed.fields)
    return sources


def _quality(context: MarketContext) -> Result:
    findings = context.inspection.findings
    count = sum(finding.severity != "info" for finding in findings)
    if not context.facts:
        findings = [*findings, Finding(
            id="no-demand", severity="high", title="Domanda non disponibile",
            detail="La serie contiene solo periodi senza valori utilizzabili.", category=TIPI[context.bundle.origin.kind],
        )]
        count += 1
    selected = next((f for f in findings if f.id.startswith("outlier") and f.severity != "info"), None)
    summary = f"I controlli hanno individuato {count} rilievi da rivedere." if count else "Controlli qualità completati."
    if selected:
        summary += f" {selected.title}. {selected.detail}"
    return Result(agent=Agent.QUALITY, status="review" if count else "completed", summary=summary,
                  values={"rows": len(context.bundle.rows), "usable_demand_periods":
                          int(context.inspection.usable["demand_gwh"].notna().sum())},
                  findings=findings, evidence=_sources(context, price=True))


def _market(context: MarketContext, args: MarketArguments) -> Result:
    facts = context.facts
    if not facts:
        return Result(agent=Agent.MARKET, status="unavailable", summary="Consumi utilizzabili assenti.",
                      evidence=_sources(context))
    monthly = context.bundle.origin.grain == "monthly"
    summary = f"{facts['label']} · consumi pari a {numero(facts['demand_gwh'])} GWh."
    delta = facts["demand_gwh_change_pct"]
    if args.comparison == "weekly" and monthly:
        summary += " Per il confronto settimanale serve una serie giornaliera, disponibile nell’archivio JRC."
    elif delta is not None:
        summary += f" Variazione dei consumi {numero(delta, signed=True)}% {facts['comparison']}."
    elif not monthly:
        summary += " Le due settimane hanno pochi giorni confrontabili."
    if facts["supply_gwh"] is not None:
        label = "Disponibilità contabile" if monthly else "Offerta"
        summary += f" {label} pari a {numero(facts['supply_gwh'])} GWh."
    if facts["net_imports_gwh"] is not None:
        summary += f" Importazioni nette pari a {numero(facts['net_imports_gwh'])} GWh."
    if facts["industry_gwh"] is not None:
        summary += f" L’industria ha consumato {numero(facts['industry_gwh'])} GWh."
    price = facts["price_eur_mwh"]
    if price is not None:
        label = "Prezzo di esempio" if context.bundle.origin.kind == Kind.SYNTHETIC else "PSV medio mensile (ARERA CMEM,m)"
        summary += f" {label} pari a {numero(price, 2)} €/MWh"
        price_delta = facts["price_eur_mwh_change_pct"]
        summary += f" ({numero(price_delta, signed=True)}% {facts['comparison']})." if price_delta is not None else "."
    if "weekend_vs_weekday_pct" in facts:
        summary += f" Nei fine settimana il consumo medio è stato {numero(facts['weekend_vs_weekday_pct'], signed=True)}% sui feriali negli ultimi 84 giorni della serie."
    if "peak_month" in facts:
        summary += f" Le medie per mese dell’anno raggiungono il picco a {facts['peak_month']}."
    return Result(agent=Agent.MARKET, summary=summary, values=facts, evidence=_sources(context, price=price is not None))


def _forecast(context: MarketContext) -> Result:
    series = context.projection
    facts = context.facts
    monthly = context.bundle.origin.grain == "monthly"
    first = series.points[0] if series.points else None
    summary = "Serie storica insufficiente per il modello selezionato."
    if first:
        period = data_it(date.fromisoformat(first.period), day=not monthly)
        label = "Proiezione storica" if context.bundle.origin.archive else "Previsione"
        summary = f"{label} per {period} con {MODELLI[series.model].lower()} pari a {numero(first.estimate)} GWh."
    if first and first.lower_80 is not None:
        interval = "Fascia bayesiana" if series.interval_kind == "posterior" else "Fascia empirica"
        summary += f" {interval} all’80% da {numero(first.lower_80)} a {numero(first.upper_80)} GWh."
    if first and context.model not in (AUTOMATIC, series.model):
        summary += f" La serie è troppo breve per {MODELLI[context.model].lower()}."
    if series.mae is not None:
        summary += f" Errore medio assoluto a un passo pari a {numero(series.mae)} GWh."
    gap, coverage = facts.get("gap_gwh"), facts.get("coverage_pct")
    if gap is not None and monthly:
        summary += f" Scarto tra disponibilità contabile e consumo osservato pari a {numero(gap)} GWh."
    elif gap is not None:
        summary += f" Saldo semplificato pari a {numero(gap, signed=True)} GWh."
        if coverage is not None:
            summary += f" Copertura pari al {numero(coverage)}%."
    else:
        summary += " Per il saldo servono domanda e offerta dello stesso periodo."
    deviation = None
    if series.backtest and series.backtest[-1].period == facts.get("period"):
        point = series.backtest[-1]
        deviation = point.actual - point.estimate
        summary += f" L’ultimo consumo osservato differisce di {numero(deviation, signed=True)} GWh dalla stima a un passo."
    return Result(agent=Agent.FORECAST, status="completed" if series.points else "unavailable", summary=summary,
                  values={"kind": Kind.FORECAST.value, "forecast": series.model_dump(mode="json"),
                          "model_preference": context.model,
                          "gap_gwh": gap, "coverage_pct": coverage, "observed_minus_expected_gwh": deviation},
                  evidence=_sources(context))


def settlement_result(inputs: SettlementInput) -> Result:
    result = settle(inputs)
    summary = "Con questi dati non è possibile calcolare l’esposizione."
    if result.cash_flow_eur is not None:
        summary = (f"La posizione simulata del partecipante è {numero(result.imbalance_mwh, 2, signed=True)} MWh. "
                   f"Flusso di cassa pari a {numero(result.cash_flow_eur, 2, signed=True)} €.")
    findings = [Finding(id=f"settlement-{i}", title="Dati di regolazione da verificare", severity="medium", detail=why,
                        category=TIPI[Kind.SIMULATION]) for i, why in enumerate(result.problems)]
    return Result(agent=Agent.SETTLEMENT, summary=summary, status="review" if findings else "completed",
                  values={"kind": Kind.SIMULATION.value, "inputs": inputs.model_dump(mode="json"),
                          **result.model_dump(mode="json")}, findings=findings, evidence=[SETTLEMENT_NOTE])


def regulation_result(library: Library, args: RegulationArguments, notice: int = 7) -> Result:
    matches = library.search(args.query)
    all_cases = bool(re.search(r"inconsisten|incongruenz|anomal|criticità|errori|mismatch", args.query, re.I))
    notice_question = bool(re.search(r"seven days|sette giorni|\b7\s*(days|giorni)", args.query, re.I))
    relevant = {
        (match.citation.document, match.citation.page)
        for match in matches[:2] if not match.is_pdf
    }
    cases = [
        case for case in REGISTER
        if all_cases or (case.finding.id == "notice-7" and (notice_question or (args.review_notice and notice == 7)))
        or any((c.document, c.page) in relevant and c.evidence == match.citation.evidence
               for c in case.finding.citations for match in matches[:2])
    ]
    citations = [match.citation for match in matches]
    if cases:
        citations = _unique_citations([c for case in cases for c in case.finding.citations] + citations)
    if cases:
        summary = (
            f"Il registro delle edizioni esaminate contiene {len(cases)} rilievi pertinenti. "
            + cases[0].finding.detail
        )
    elif matches:
        top = matches[0]
        quote = top.citation.evidence if not top.is_pdf else " ".join(top.citation.evidence.split()[:44]) + " …"
        summary = f"{top.citation.document}, PDF p. {top.citation.page}. {quote}"
    else:
        summary = "I materiali indicizzati non contengono un riscontro sufficiente per questa domanda."
    findings = [case.finding for case in cases]
    return Result(agent=Agent.REGULATORY, status="review" if any(f.severity != "info" for f in findings) else
                  ("completed" if citations else "unavailable"),
                  summary=summary, evidence=citations,
                  values={"query": args.query, "local_pdfs": len(library.documents),
                          "edition_status": "Edizioni esaminate. Applicabilità attuale da verificare.",
                          "notice_days": notice if args.review_notice else None},
                  findings=findings)


def _unique_citations(citations: list[Citation]) -> list[Citation]:
    return list({(c.document, c.page, c.evidence): c for c in citations}.values())


def _scenario(context: MarketContext, assumptions: ScenarioInput, args: ScenarioArguments) -> Result:
    changes = ScenarioInput.model_validate({
        **assumptions.model_dump(), **args.model_dump(exclude_none=True),
    })
    facts = context.facts
    if facts.get("demand_gwh") is None or facts.get("supply_gwh") is None:
        context = MarketContext(synthetic(), context.model, context.as_of)
        facts = context.facts
    case = ScenarioCase(**facts)
    try:
        stress = scenario(case, changes)
        base = scenario(case, ScenarioInput(demand_pct=0))
    except ValueError as error:
        return Result(agent=Agent.SCENARIO, status="review", evidence=_sources(context), summary=str(error),
                      findings=[Finding(id="scenario-baseline", severity="medium", title="Dati dello scenario da verificare",
                                        detail=str(error), category=TIPI[Kind.SIMULATION])])
    delta = None if stress.gap_value_eur is None else stress.gap_value_eur - base.gap_value_eur
    basis = "Base di esempio" if context.bundle.origin.kind == Kind.SYNTHETIC else "Base contabile Eurostat"
    summary = (f"{basis} · {facts['label']}. Con domanda {numero(changes.demand_pct, signed=True)}% e offerta "
               f"escluso stoccaggio {numero(changes.supply_pct, signed=True)}%, "
               f"il saldo simulato è {numero(stress.imbalance_gwh, signed=True)} GWh")
    summary += f" e la copertura è {numero(stress.coverage_pct)}%." if stress.coverage_pct is not None else "."
    if delta is not None:
        summary += f" Variazione indicativa del valore del saldo {numero(delta, 0, signed=True)} €."
    return Result(agent=Agent.SCENARIO, summary=summary, evidence=_sources(context, price=delta is not None),
                  values={"kind": Kind.SIMULATION.value, "inputs": case.model_dump(mode="json"),
                          "baseline_kind": context.bundle.origin.kind.value, "baseline_period": facts["period"],
                          "baseline_grain": context.bundle.origin.grain,
                          "changes": changes.model_dump(mode="json"), "base": base.model_dump(mode="json"),
                          "stress": stress.model_dump(mode="json"),
                          "gap_value_delta_eur": str(delta) if delta is not None else None})


def catalog(context: MarketContext, library: Library, assumptions: Assumptions) -> dict[Agent, Tool]:
    return {
        Agent.QUALITY: Tool("Controlla dati mancanti, conflitti, aggiornamenti, valori insoliti e misure non valide.",
                            Arguments, lambda _: _quality(context)),
        Agent.MARKET: Tool("Analizza consumi, offerta, prezzi e stagionalità alla frequenza della fonte.",
                           MarketArguments, lambda args: _market(context, args)),
        Agent.FORECAST: Tool("Calcola previsioni della domanda, errori cronologici e saldo aggregato.",
                             Arguments, lambda _: _forecast(context)),
        Agent.SETTLEMENT: Tool("Applica i volumi ipotetici e i prezzi di acquisto e vendita dell’utente.",
                               Arguments, lambda _: settlement_result(assumptions.settlement)),
        Agent.REGULATORY: Tool("Cerca pagine PDF per rispondere a domande su formule, definizioni o ambiguità.",
                               RegulationArguments,
                               lambda args: regulation_result(library, args, assumptions.cancellation_notice_days)),
        Agent.SCENARIO: Tool("Simula domanda, offerta, stoccaggio e variazioni del prezzo. "
                             "Usa gli scostamenti indicati nella richiesta o le ipotesi salvate.",
                             ScenarioArguments, lambda args: _scenario(context, assumptions.stress, args)),
    }
