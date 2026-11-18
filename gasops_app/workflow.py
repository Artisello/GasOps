"""Route market objectives and perform an independent consistency pass."""

from collections.abc import Callable
from decimal import Decimal
import re

from .agents import Assumptions, MarketArguments, MarketContext, RegulationArguments, ScenarioArguments, catalog
from .finance import CENT, MWH_PER_UNIT
from .models import Agent, Finding, Run
from .regulatory import Library
from .supervisor import Arguments, Call, Reasoner, execute

DAILY_BRIEFING = "Bollettino sul mercato del gas"
OFFLINE_REGULATION_QUERY = "Preavviso di esattamente sette giorni per mancata discarica · coefficiente T Piombino"

INTENTS = {
    Agent.QUALITY: r"anomal|quality|qualità|missing|mancant|duplicat|outlier|stale|freshness|timestamp",
    Agent.MARKET: r"demand|domanda|consum|supply|offerta|mercat|market|price|prezz|week|settiman|importaz|psv",
    Agent.FORECAST: r"forecast|prevision|expected|squilibri|balancing|bilanciamento|copertura|coverage",
    Agent.SETTLEMENT: r"settlement|regolazione|exposure|esposizione|cash.flow|flusso di cassa|fattura|buy.*sell",
    Agent.REGULATORY: r"regolament|regulatory|network code|codice|piombino|panigaglia|discarica|coefficient"
                      r"|cancellation|inconsisten|incongruenz|density|densità|denominat|normativ",
    Agent.SCENARIO: r"what if|what happens|scenario|stress|monte carlo|cvar|\\bvar\\b|expected shortfall|probabilità di deficit|simula|se la domanda|aumento|aumenta|increases by|decreases by|\d ?%",
}


def _scenario_args(question: str) -> ScenarioArguments:
    changes = {}
    for key, terms in {"demand_pct": "demand|domanda|consum[oi]", "supply_pct": "supply|offerta",
                       "storage_pct": "storage|stoccaggio"}.items():
        match = re.search(rf"\b(?:{terms})\b([^\d+-]{{0,33}})([+-]?\d+(?:[.,]\d+)?)\s*%", question, re.I)
        # Prevent an adjustment from being assigned to an earlier variable in a combined request.
        if match and not re.search(r"\b(demand|domanda|supply|offerta|storage|stoccaggio)\b", match[1], re.I):
            amount = Decimal(match[2].replace(",", "."))
            reduced = re.search(r"decreas|reduc|fall|drop|declin|ridu[cz]|diminui|cal[oa]", match[1], re.I)
            changes[key] = -amount if reduced and amount > 0 else amount
    return ScenarioArguments(**changes)


def plan(question: str, full: bool) -> list[Call]:
    briefing = full or bool(re.search(r"briefing|readout|daily gas market|report giornalier|bollettino", question, re.I))
    targets = set(Agent) if briefing else {
        agent for agent, pattern in INTENTS.items() if re.search(pattern, question, re.I)
    }
    if not briefing and Agent.REGULATORY in targets and re.search(r"define|defini[sz]|meaning", question, re.I):
        targets.discard(Agent.FORECAST)
    if Agent.SETTLEMENT in targets and not briefing and not re.search(r"\d+\s*%|demand|domanda|storage|stoccaggio|monte carlo|cvar|\\bvar\\b|expected shortfall", question, re.I):
        targets.discard(Agent.SCENARIO)
    if not targets:
        targets = {Agent.MARKET}
    args = {
        Agent.MARKET: MarketArguments(comparison="weekly" if re.search(r"week|settiman", question, re.I) else "native"),
        Agent.REGULATORY: RegulationArguments(
            query=OFFLINE_REGULATION_QUERY if briefing else question,
            review_notice=briefing,
        ),
    }
    if Agent.SCENARIO in targets:
        args[Agent.SCENARIO] = _scenario_args(question)
    return [Call(agent, args.get(agent, Arguments())) for agent in Agent if agent in targets]


def validate(run: Run, context: MarketContext, assumptions: Assumptions) -> list[Finding]:
    findings: list[Finding] = []

    def conflict(key: str, detail: str) -> None:
        findings.append(Finding(id=key, title="Conflitto tra i risultati", severity="high",
                                detail=detail, category="Validazione indipendente"))

    result = run.results.get(Agent.SETTLEMENT)
    if result and result.status != "failed":
        supplied = assumptions.settlement
        if supplied.delivered is not None and supplied.withdrawn is not None:
            factor = MWH_PER_UNIT[supplied.unit]
            net = (supplied.delivered - supplied.withdrawn) * factor
            price = supplied.buy_eur_mwh if net < 0 else supplied.sell_eur_mwh
            expected = Decimal(0) if net == 0 else None if price is None else (net * price).quantize(CENT)
            cash = result.values.get("cash_flow_eur")
            net_found = result.values.get("imbalance_mwh")
            if (net_found is None or Decimal(str(net_found)) != net
                    or (None if cash is None else Decimal(str(cash))) != expected):
                conflict("settlement-reconcile", "Quantità o flusso di cassa della regolazione non quadrano.")

    forecasted = run.results.get(Agent.FORECAST)
    market = run.results.get(Agent.MARKET)
    if forecasted and forecasted.status == "completed":
        outputs = forecasted.values["forecast"]
        last_calendar = context.inspection.usable.index[-1].date().isoformat()
        if (any(p["train_end"] >= p["period"] for p in outputs["backtest"])
                or any(p["period"] <= last_calendar or p["estimate"] < 0 for p in outputs["points"])):
            conflict("forecast-timing", "Date o stime previsionali incoerenti.")
        if any(p["lower_80"] is not None and not 0 <= p["lower_80"] <= p["estimate"] <= p["upper_80"]
               for p in outputs["points"]):
            conflict("forecast-interval", "Fascia previsionale incoerente con la stima.")
        if market and market.values.get("gap_gwh") != forecasted.values.get("gap_gwh"):
            conflict("market-gap", "Gli agenti di mercato e di previsione hanno calcolato saldi diversi per lo stesso periodo.")

    stress = run.results.get(Agent.SCENARIO)
    if stress and stress.status == "completed":
        base = stress.values["base"]
        shock = stress.values["stress"]
        if any(Decimal(row["supply_gwh"]) - Decimal(row["demand_gwh"]) != Decimal(row["imbalance_gwh"])
               for row in (base, shock)):
            conflict("scenario-reconcile", "Il saldo dello scenario non coincide con la differenza tra offerta e domanda.")
        if market and market.values.get("gap_gwh") is not None and abs(
            float(base["imbalance_gwh"]) - market.values["gap_gwh"]
        ) > 0.000001:
            conflict("scenario-market", "La base dello scenario non coincide con il saldo di mercato.")
    regulation = run.results.get(Agent.REGULATORY)
    if regulation and regulation.evidence and any(c.page is None or not c.evidence for c in regulation.evidence):
        conflict("citation-page", "Un riferimento normativo è privo di pagina o testo di supporto.")
    return findings


def run_workflow(
    context: MarketContext,
    library: Library,
    assumptions: Assumptions,
    question: str = DAILY_BRIEFING,
    *,
    full: bool = False,
    notify: Callable[[Run], None] | None = None,
    reasoner: Reasoner | None = None,
    public_context: dict | None = None,
    planned_only: bool = False,
) -> Run:
    question = question.strip()[:600] or DAILY_BRIEFING
    defaults = plan(question, full)
    editions = {title: pdf.digest for title, pdf in library.documents.items()}
    run = Run(
        question=question, source=context.bundle.origin, input_sha256=context.bundle.fingerprint,
        assumptions={**assumptions.model_dump(mode="json"), "pdf_sha256": editions,
                     "public_operational_context":public_context or {}, "full_briefing":full,
                     "source_period":context.facts.get("period")},
    )
    required = set(Agent) if full else {call.agent for call in defaults} if len(defaults) == len(Agent) else set()
    report = execute(
        run, catalog(context, library, assumptions), defaults, required,
        lambda report: validate(report, context, assumptions), notify or (lambda _: None), reasoner, planned_only=planned_only,
    )
    if Agent.QUALITY in report.results:
        report.assumptions["source_period"] = context.facts.get("period")
    return report
