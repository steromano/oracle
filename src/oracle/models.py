"""Pydantic v2 data schemas for Oracle (§7) plus deterministic ID helpers.

All datetimes are stored tz-aware in UTC. Naive datetimes are assumed to be
UTC; tz-aware non-UTC datetimes are converted to the equivalent UTC instant.
This normalization is centralized in ``UTCModel`` so every record type inherits
it. Records are append-only (§6.1); the CLI — never the caller — stamps IDs and
timestamps (§5.9).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, field_validator


class UTCModel(BaseModel):
    """Base model that forces every ``datetime`` field to tz-aware UTC.

    Naive datetimes are interpreted as UTC (rather than rejected) so that JSON
    round-trips and hand-authored fixtures stay ergonomic; aware datetimes in
    another zone are converted to the same instant in UTC.
    """

    @field_validator("*", mode="before")
    @classmethod
    def _coerce_datetimes_to_utc(cls, value: object) -> object:
        return _normalize(value)


def _normalize(value: object) -> object:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_normalize(v) for v in value)
    return value


class MarketLink(UTCModel):
    platform: str
    market_id: str
    price_at_creation: float | None = None


class QuestionSpec(UTCModel):
    """§7.1 — id ``Q-YYYYMMDD-NNN``."""

    id: str
    title: str
    question_text: str
    q_type: Literal["binary", "threshold_ladder", "multiple_choice"]
    thresholds: list[float] | None = None
    resolution_criteria: str
    resolution_source: str
    resolution_deadline: datetime
    edge_cases: str
    domain: str
    horizon_days: int
    linked_markets: list[MarketLink] = []
    origin: Literal["user", "import"]
    blind: bool = False
    sealed_snapshot: str | None = None
    created_at: datetime
    created_by: str


class EnsembleMember(UTCModel):
    kind: str  # "evidence-slice:A" | "method:base-rate" | "model:openrouter/x"
    probability: float
    crux: str


class UpdateTrigger(UTCModel):
    type: Literal["date", "release", "market_move", "event"]
    check: str
    due: datetime | None = None


class ForecastRecord(UTCModel):
    """§7.2 — id ``F-YYYYMMDD-NNN``."""

    id: str
    question_id: str
    stream_id: str
    stream_seq: int
    probability: float
    raw_pool: dict[str, float]
    ensemble: list[EnsembleMember]
    pool_method: str
    market_price_used: float | None = None
    calibration_map_id: str | None = None
    resilience: Literal["robust", "moderate", "fragile"]
    ensemble_iqr: float
    process_audit: dict[str, bool]
    effort_tier: Literal["quick", "standard", "deep"]
    tools_used: list[str]
    evidence_log: str
    evidence_hash: str
    info_cutoff: datetime | None = None
    committed_at: datetime
    git_sha: str
    supersedes: str | None = None
    update_rationale: str | None = None
    update_triggers: list[UpdateTrigger] = []
    variant: Literal["control", "paid-trial"] = "control"  # §8.3
    blind_violated: bool = False  # §9.6.6


class TradeResult(UTCModel):
    direction: Literal["yes", "no", "none"]
    stake: float
    entry_price: float
    payoff: float
    log_wealth_delta: float


class ResolutionRecord(UTCModel):
    """§7.3."""

    forecast_id: str
    question_id: str
    outcome: Literal["yes", "no", "void"]
    resolved_at: datetime
    resolution_evidence: str
    scores: dict[str, float]
    baseline_scores: dict[str, dict[str, float]]
    pnl: TradeResult | None = None
    spec_defect_audit: str | None = None


def new_question_id(date: datetime, seq: int) -> str:
    """Deterministic question id, e.g. ``Q-20260705-001``."""
    return f"Q-{date:%Y%m%d}-{seq:03d}"


def new_forecast_id(date: datetime, seq: int) -> str:
    """Deterministic forecast id, e.g. ``F-20260705-001``."""
    return f"F-{date:%Y%m%d}-{seq:03d}"
