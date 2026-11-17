"""Specialised agents and the read-only tools they expose to the supervisor."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from functools import cached_property
import re
from typing import Literal

from pydantic import BaseModel, Field

from .data import Bundle
from .finance import ScenarioCase, ScenarioInput, SettlementInput, scenario, settle
from .forecast import Forecast, ModelName, forecast
from .market import market_facts
from .models import Agent, Citation, Finding, Kind, Result
from .quality import Inspection, inspect
from .regulatory import Library, REGISTER, SETTLEMENT_NOTE
from .supervisor import Arguments, Tool


class Assumptions(BaseModel):
    model: ModelName = "Seasonal regression"
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
    model: ModelName
    as_of: datetime

    @cached_property
    def inspection(self) -> Inspection:
        return inspect(self.bundle, self.as_of)

    @cached_property
    def facts(self) -> dict:
        return market_facts(self.inspection.usable, self.bundle.origin.grain)

    @cached_property
    def projection(self) -> Forecast:
        return forecast(self.inspection.usable["demand_gwh"], self.bundle.origin.grain, self.model)


def _source(context: MarketContext) -> Citation:
    origin = context.bundle.origin
    latest = context.facts.get("label", "period unavailable")
    return Citation(document=origin.name, evidence=f"{origin.kind.value} · {origin.grain} · {latest}. {origin.description}",
                    url=origin.url)


def _quality(context: MarketContext) -> Result:
    findings = context.inspection.findings
    count = sum(finding.severity != "info" for finding in findings)
    if not context.facts:
        findings = [*findings, Finding(
            id="no-demand", severity="high", title="Demand unavailable",
            detail="The dataset contains no usable demand periods.", category=context.bundle.origin.kind.value,
        )]
        count += 1
    selected = next((f for f in findings if f.id.startswith("outlier")), None)
    summary = f"Quality found {count} issue(s) requiring review." if count else "Quality checks passed."
    if selected:
        summary += f" {selected.title}. {selected.detail}"
    return Result(agent=Agent.QUALITY, status="review" if count else "completed", summary=summary,
                  values={"rows": len(context.bundle.rows), "usable_demand_periods":
                          int(context.inspection.usable["demand_gwh"].notna().sum())},
                  findings=findings, evidence=[_source(context)])


def _market(context: MarketContext, args: MarketArguments) -> Result:
    facts = context.facts
    if not facts:
        return Result(agent=Agent.MARKET, status="unavailable", summary="Usable demand was unavailable.",
                      evidence=[_source(context)])
    monthly = context.bundle.origin.grain == "monthly"
    summary = f"{facts['label']} demand was {facts['demand_gwh']:,.1f} GWh."
    delta = facts["demand_gwh_change_pct"]
    if args.comparison == "weekly" and monthly:
        summary += " A week-on-week comparison requires a daily series. This source is monthly."
    elif delta is not None:
        summary += f" Demand was {delta:+.1f}% {facts['comparison']}."
    elif not monthly:
        summary += " The two seven-day windows have insufficient matched demand observations."
    if facts["supply_gwh"] is not None:
        summary += f" Supply was {facts['supply_gwh']:,.1f} GWh."
    price = facts["price_eur_mwh"]
    if price is not None:
        label = "Simulated reference price" if context.bundle.origin.kind == Kind.SYNTHETIC else "Reference price"
        summary += f" {label} was €{price:,.2f}/MWh"
        price_delta = facts["price_eur_mwh_change_pct"]
        summary += f" ({price_delta:+.1f}% {facts['comparison']})." if price_delta is not None else "."
    if "weekend_vs_weekday_pct" in facts:
        summary += f" Weekend demand averaged {facts['weekend_vs_weekday_pct']:+.1f}% vs weekdays over 84 days."
    if "peak_month" in facts:
        summary += f" Calendar-month averages in this series peak in {facts['peak_month']}."
    return Result(agent=Agent.MARKET, summary=summary, values=facts, evidence=[_source(context)])


def _forecast(context: MarketContext) -> Result:
    series = context.projection
    facts = context.facts
    summary = "The selected model has insufficient demand history." if not series.points else (
        f"{series.model} projects {series.points[0].estimate:,.1f} GWh for {series.points[0].period}."
    )
    first = series.points[0] if series.points else None
    if first and first.lower_80 is not None:
        summary += f" The 80% empirical interval is {first.lower_80:,.1f}–{first.upper_80:,.1f} GWh."
    if series.mae is not None:
        summary += f" One-step walk-forward MAE was {series.mae:,.1f} GWh."
    gap, coverage = facts.get("gap_gwh"), facts.get("coverage_pct")
    if gap is not None:
        summary += f" The observed-period screening gap was {gap:+,.1f} GWh."
        if coverage is not None:
            summary += f" Coverage was {coverage:.1f}%."
    else:
        summary += " The balancing screen requires same-period demand and supply."
    deviation = None
    if series.backtest and series.backtest[-1].period == facts.get("period"):
        point = series.backtest[-1]
        deviation = point.actual - point.estimate
        summary += f" Latest demand was {deviation:+,.1f} GWh from its one-step estimate."
    return Result(agent=Agent.FORECAST, status="completed" if series.points else "unavailable", summary=summary,
                  values={"kind": Kind.FORECAST.value, "forecast": series.model_dump(mode="json"),
                          "gap_gwh": gap, "coverage_pct": coverage, "observed_minus_expected_gwh": deviation},
                  evidence=[_source(context)])


def settlement_result(inputs: SettlementInput) -> Result:
    result = settle(inputs)
    summary = "Settlement exposure is unavailable with the supplied inputs."
    if result.cash_flow_eur is not None:
        summary = (f"The simulated user position is {result.imbalance_mwh:+,.2f} MWh. "
                   f"Signed user cash flow is {result.cash_flow_eur:+,.2f} EUR.")
    findings = [Finding(id=f"settlement-{i}", title="Settlement input review", severity="medium", detail=why,
                        category=Kind.SIMULATION.value) for i, why in enumerate(result.problems)]
    return Result(agent=Agent.SETTLEMENT, summary=summary, status="review" if findings else "completed",
                  values={"kind": Kind.SIMULATION.value, "inputs": inputs.model_dump(mode="json"),
                          **result.model_dump(mode="json")}, findings=findings, evidence=[SETTLEMENT_NOTE])


def regulation_result(library: Library, args: RegulationArguments, notice: int = 7) -> Result:
    matches = library.search(args.query)
    all_cases = bool(re.search(r"inconsisten|anomal|criticità|errori|mismatch", args.query, re.I))
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
            f"The edition register has {len(cases)} relevant entries. "
            + cases[0].finding.detail
        )
    elif matches:
        top = matches[0]
        quote = top.citation.evidence if not top.is_pdf else " ".join(top.citation.evidence.split()[:44]) + " …"
        summary = f"{top.citation.document}, PDF p. {top.citation.page}. {quote}"
    else:
        summary = "The indexed material returned insufficient page evidence for this question."
    findings = [case.finding for case in cases]
    return Result(agent=Agent.REGULATORY, status="review" if any(f.severity != "info" for f in findings) else
                  ("completed" if citations else "unavailable"),
                  summary=summary, evidence=citations,
                  values={"query": args.query, "local_pdfs": len(library.documents),
                          "edition_status": "Reviewed copies; current applicability unverified",
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
        return Result(agent=Agent.SCENARIO, status="unavailable", evidence=[_source(context)],
                      summary="Aggregate stress needs an aligned supply and demand baseline.")
    case = ScenarioCase(**facts)
    try:
        stress = scenario(case, changes)
        base = scenario(case, ScenarioInput(demand_pct=0))
    except ValueError as error:
        return Result(agent=Agent.SCENARIO, status="review", evidence=[_source(context)], summary=str(error),
                      findings=[Finding(id="scenario-baseline", severity="medium", title="Scenario input review",
                                        detail=str(error), category=Kind.SIMULATION.value)])
    delta = None if stress.gap_value_eur is None else stress.gap_value_eur - base.gap_value_eur
    summary = (f"With demand {changes.demand_pct:+.1f}% and non-storage supply {changes.supply_pct:+.1f}%, "
               f"the simulated gap is {stress.imbalance_gwh:+,.1f} GWh")
    summary += f" and coverage is {stress.coverage_pct:.1f}%." if stress.coverage_pct is not None else "."
    if delta is not None:
        summary += f" The indicative gap-value change is {delta:+,.0f} EUR."
    return Result(agent=Agent.SCENARIO, summary=summary, evidence=[_source(context)],
                  values={"kind": Kind.SIMULATION.value, "inputs": case.model_dump(mode="json"),
                          "changes": changes.model_dump(mode="json"), "base": base.model_dump(mode="json"),
                          "stress": stress.model_dump(mode="json"),
                          "gap_value_delta_eur": str(delta) if delta is not None else None})


def catalog(context: MarketContext, library: Library, assumptions: Assumptions) -> dict[Agent, Tool]:
    return {
        Agent.QUALITY: Tool("Check missing, conflicting, stale, outlier and invalid gas observations.",
                            Arguments, lambda _: _quality(context)),
        Agent.MARKET: Tool("Inspect demand, supply, price and seasonal patterns at source frequency.",
                           MarketArguments, lambda args: _market(context, args)),
        Agent.FORECAST: Tool("Generate demand forecast, chronological errors and aggregate balancing screen.",
                             Arguments, lambda _: _forecast(context)),
        Agent.SETTLEMENT: Tool("Apply the user's saved hypothetical volumes and supplied buy/sell prices.",
                               Arguments, lambda _: settlement_result(assumptions.settlement)),
        Agent.REGULATORY: Tool("Retrieve cited PDF evidence for a question, formula, definition or ambiguity.",
                               RegulationArguments,
                               lambda args: regulation_result(library, args, assumptions.cancellation_notice_days)),
        Agent.SCENARIO: Tool("Model gas demand, non-storage supply, storage contribution and price changes. "
                             "Only specify adjustments given in the question, otherwise use saved assumptions.",
                             ScenarioArguments, lambda args: _scenario(context, assumptions.stress, args)),
    }
