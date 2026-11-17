"""The contract shared by the dashboard, analytical tools and supervisor."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Kind(StrEnum):
    SYNTHETIC = "SYNTHETIC DATA"
    HISTORICAL = "HISTORICAL PUBLIC DATA"
    LIVE = "LIVE PUBLIC DATA"
    FORECAST = "FORECAST"
    SIMULATION = "SIMULATION"
    ACCOUNTING = "ACCOUNTING DEFAULT"
    PHYSICAL = "PHYSICAL MEASUREMENT"


class Origin(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    kind: Kind
    grain: Literal["daily", "monthly"]
    fields: tuple[str, ...]
    description: str
    url: str | None = None
    retrieved_at: AwareDatetime
    published_at: AwareDatetime | None = None
    cached: bool = False
    refresh_failed: bool = False


class Citation(BaseModel):
    document: str
    evidence: str
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    url: str | None = None


class Finding(BaseModel):
    id: str
    title: str
    severity: Literal["high", "medium", "info"]
    detail: str
    category: str
    citations: list[Citation] = Field(default_factory=list)


class Agent(StrEnum):
    QUALITY = "data_quality"
    MARKET = "market_intelligence"
    FORECAST = "forecast_balancing"
    SETTLEMENT = "settlement"
    REGULATORY = "regulatory_intelligence"
    SCENARIO = "scenario"


AGENT_LABELS = {
    Agent.QUALITY: "Data Quality & Risk",
    Agent.MARKET: "Market Intelligence",
    Agent.FORECAST: "Forecasting & Balancing",
    Agent.SETTLEMENT: "Settlement",
    Agent.REGULATORY: "Regulatory Intelligence",
    Agent.SCENARIO: "Scenario Analysis",
}

Status = Literal["queued", "running", "completed", "review", "unavailable", "failed", "skipped"]


class Result(BaseModel):
    agent: Agent
    status: Status = "completed"
    summary: str
    values: dict[str, JsonValue] = Field(default_factory=dict)
    evidence: list[Citation] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)


class Step(BaseModel):
    agent: Agent
    status: Status = "queued"
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None


class Run(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    question: str
    source: Origin
    input_sha256: str
    assumptions: dict[str, JsonValue]
    started_at: AwareDatetime = Field(default_factory=utc_now)
    finished_at: AwareDatetime | None = None
    validated_at: AwareDatetime | None = None
    mode: Literal["Deterministic", "LLM-assisted", "Deterministic fallback"] = "Deterministic"
    model: str | None = None
    steps: dict[Agent, Step] = Field(
        default_factory=lambda: {agent: Step(agent=agent, status="skipped") for agent in Agent}
    )
    results: dict[Agent, Result] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: str = ""
    interpretation: str | None = None
    interpretation_sources: list[Agent] = Field(default_factory=list)
