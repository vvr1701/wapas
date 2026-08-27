"""SQLAlchemy engine and ORM models (PRD §7, Phase 2 subset).

Single responsibility: define the persistent schema and hand out engines/sessions.
Tables land phase by phase; this phase: revenue_events, recovery_cases, audit_log.
Timestamps are stored as ISO-8601 UTC strings — SQLite round-trips them exactly,
which the audit hash chain depends on.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.orm import Session as Session  # re-export for callers

DEFAULT_DB = Path("data/wapas.db")


class Base(DeclarativeBase):
    pass


class RevenueEventRow(Base):
    """Normalized revenue-at-risk event, whatever its source (FR-2.1)."""

    __tablename__ = "revenue_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String, unique=True)  # dedupe on re-ingestion
    category: Mapped[str]  # L1 | L2 | L3
    source: Mapped[str]  # rzp_poll | webhook | simulator
    customer_id: Mapped[str]
    entity_type: Mapped[str]  # subscription | order | invoice
    entity_id: Mapped[str]
    amount_inr: Mapped[int]
    occurred_at: Mapped[str]  # ISO-8601 UTC
    raw_payload: Mapped[str] = mapped_column(Text)


class RecoveryCaseRow(Base):
    """One recovery case per underlying at-risk entity (FR-2.2)."""

    __tablename__ = "recovery_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[str] = mapped_column(String, unique=True)  # duplicate-case guard
    customer_id: Mapped[str]
    category: Mapped[str]
    amount_due_inr: Mapped[int]
    currency: Mapped[str] = mapped_column(String, default="INR")
    state: Mapped[str]  # agent.cases.CaseState
    root_cause: Mapped[str | None]
    diagnosis_confidence: Mapped[float | None]
    diagnosis_source: Mapped[str | None]  # rule | llm
    due_date: Mapped[str | None]  # L3 scheduling anchor ("due+Nd" playbook timings)
    opened_ts: Mapped[str]
    closed_ts: Mapped[str | None]


class PlannedActionRow(Base):
    """One intervention the policy engine decided on — explainable by construction:
    rule_id + rationale + policy_version_hash are NOT NULL (FR-4.2)."""

    __tablename__ = "planned_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int]
    action_type: Mapped[str]
    channel: Mapped[str]
    scheduled_for: Mapped[str]  # ISO-8601 UTC
    rule_id: Mapped[str]
    rationale: Mapped[str] = mapped_column(Text)
    policy_version_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String, default="PENDING")
    incentive_inr: Mapped[int] = mapped_column(default=0)  # bounded by FR-4.3 rules


class CustomerRow(Base):
    """Customer registry — synthetic PII only. opted_out is the permanent
    opt-out registry the gate consults (FR-5.2)."""

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[str] = mapped_column(String, unique=True)
    opted_out: Mapped[bool] = mapped_column(default=False, index=True)
    opt_out_ts: Mapped[str | None]
    opt_out_source: Mapped[str | None]


class ExecutedActionRow(Base):
    """One executed intervention. idempotency_key is UNIQUE — the same logical
    attempt can never execute twice (FR-5.1 check 8, NFR-2)."""

    __tablename__ = "executed_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    planned_id: Mapped[int]
    case_id: Mapped[int] = mapped_column(index=True)
    action_type: Mapped[str]
    channel: Mapped[str]
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    executed_ts: Mapped[str]
    result: Mapped[str]
    external_ref: Mapped[str | None]  # payment_link_id etc.
    incentive_inr: Mapped[int] = mapped_column(default=0)


class PromiseRow(Base):
    """Promise-to-pay captured from a voice call (FR-8.1)."""

    __tablename__ = "promises"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(index=True)
    amount_inr: Mapped[int]
    due_date: Mapped[str]  # ISO-8601 UTC
    conditions: Mapped[str | None]
    confidence: Mapped[float]
    status: Mapped[str] = mapped_column(String, default="PENDING")  # KEPT|BROKEN|PARTIAL
    transcript_ref: Mapped[str | None]
    created_ts: Mapped[str]


class EscalationRow(Base):
    """Human handoff with a self-sufficient context packet (FR-9.1)."""

    __tablename__ = "escalations"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(index=True)
    reason: Mapped[str]
    context_packet_json: Mapped[str] = mapped_column(Text)
    acked_by: Mapped[str | None]
    acked_ts: Mapped[str | None]
    created_ts: Mapped[str]


class PaymentObservedRow(Base):
    """Incoming test-mode payments matched to cases — the recovered-₹ source of
    truth (FR-6.2, FR-11.2)."""

    __tablename__ = "payments_observed"

    id: Mapped[int] = mapped_column(primary_key=True)
    rzp_payment_id: Mapped[str] = mapped_column(String, unique=True)
    amount_inr: Mapped[int]
    method: Mapped[str | None]
    matched_case_id: Mapped[int | None] = mapped_column(index=True)
    matched_promise_id: Mapped[int | None]
    attribution_arm: Mapped[str | None]  # set by the eval harness (Phase 8)
    observed_ts: Mapped[str]


class AuditRow(Base):
    """Append-only, tamper-evident audit record (FR-10.1). id is chain order."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[str]
    case_id: Mapped[int | None]
    actor: Mapped[str]  # system | agent | human | customer
    event_type: Mapped[str]
    payload_json: Mapped[str] = mapped_column(Text)
    rule_id: Mapped[str | None]
    policy_version_hash: Mapped[str | None]
    prev_record_hash: Mapped[str] = mapped_column(String(64))
    record_hash: Mapped[str] = mapped_column(String(64))


class LlmCallRow(Base):
    """One LLM API call — cost and behavior are measured, never claimed (§6.2)."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    purpose: Mapped[str]  # conversation | promise_extraction | diagnosis | ...
    prompt_file: Mapped[str]
    prompt_hash: Mapped[str] = mapped_column(String(64))
    model: Mapped[str]
    tokens_in: Mapped[int]
    tokens_out: Mapped[int]
    latency_ms: Mapped[int]
    cost_usd: Mapped[float]
    valid_output: Mapped[bool]
    ts: Mapped[str]


def get_engine(path: Path = DEFAULT_DB):
    """Engine with schema ensured. SQLite file lives under data/."""
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    return engine
