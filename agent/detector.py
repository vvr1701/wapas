"""Ingestion & detection (FR-2.1, FR-2.2).

Single responsibility: normalize revenue-at-risk facts from any source
(Razorpay poll, webhook, simulator injection) into one RevenueEvent shape,
persist them idempotently, and open RecoveryCases per detection rule.
The agent sees only these normalized events — never simulator internals.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.cases import DuplicateCase, open_case
from ledger.db import RecoveryCaseRow, RevenueEventRow

# Detection thresholds; moves to config/policies.yaml in Phase 3.
L2_UNPAID_AGE_MIN = 30


class RevenueEvent(BaseModel):
    """The single normalized shape every ingestion path must produce (FR-2.1)."""

    event_id: str
    category: Literal["L1", "L2", "L3"]
    source: Literal["rzp_poll", "webhook", "simulator"]
    customer_id: str
    entity_type: Literal["subscription", "order", "invoice"]
    entity_id: str
    amount_inr: int
    occurred_at: datetime
    due_date: datetime | None = None
    auth_attempted: bool | None = None
    error_code: str | None = None
    error_reason: str | None = None
    error_description: str | None = None


def from_simulator(raw: dict) -> RevenueEvent:
    """Normalize one simulator-injected event (the dicts in data/events_seed*.json)."""
    return RevenueEvent(source="simulator", **{k: v for k, v in raw.items() if v is not None})


def from_razorpay_order(raw: dict, *, customer_id: str, event_id: str) -> RevenueEvent:
    """Normalize a polled Razorpay Order entity (L2 candidate: created, unpaid)."""
    return RevenueEvent(
        event_id=event_id,
        category="L2",
        source="rzp_poll",
        customer_id=customer_id,
        entity_type="order",
        entity_id=raw["id"],
        amount_inr=raw["amount"] // 100,
        occurred_at=datetime.fromtimestamp(raw["created_at"], tz=UTC),
        auth_attempted=raw.get("attempts", 0) > 0,
    )


def from_razorpay_invoice(raw: dict, *, event_id: str) -> RevenueEvent:
    """Normalize a polled Razorpay Invoice entity (L3 candidate: past due)."""
    return RevenueEvent(
        event_id=event_id,
        category="L3",
        source="rzp_poll",
        customer_id=raw["customer_id"],
        entity_type="invoice",
        entity_id=raw["id"],
        amount_inr=raw["amount"] // 100,
        occurred_at=datetime.fromtimestamp(raw["created_at"], tz=UTC),
        due_date=datetime.fromtimestamp(raw["expire_by"], tz=UTC) if raw.get("expire_by") else None,
    )


def _due(event: RevenueEvent, now: datetime) -> bool:
    """Detection rules per FR-2.2: is this event case-worthy right now?"""
    if event.category == "L1":
        return True  # charge failure is immediately at risk
    if event.category == "L2":
        return now - event.occurred_at >= timedelta(minutes=L2_UNPAID_AGE_MIN)
    return event.due_date is not None and event.due_date < now


def ingest(session: Session, events: list[RevenueEvent], now: datetime) -> list[RecoveryCaseRow]:
    """Persist events (idempotent on event_id) and open cases per detection rules.
    Duplicate entities never get a second case (FR-2.2)."""
    opened: list[RecoveryCaseRow] = []
    for e in events:
        if session.scalar(select(RevenueEventRow).where(RevenueEventRow.event_id == e.event_id)):
            continue
        session.add(
            RevenueEventRow(
                event_id=e.event_id,
                category=e.category,
                source=e.source,
                customer_id=e.customer_id,
                entity_type=e.entity_type,
                entity_id=e.entity_id,
                amount_inr=e.amount_inr,
                occurred_at=e.occurred_at.isoformat(),
                raw_payload=json.dumps(e.model_dump(mode="json"), sort_keys=True),
            )
        )
        if not _due(e, now):
            continue
        try:
            opened.append(
                open_case(
                    session,
                    entity_id=e.entity_id,
                    customer_id=e.customer_id,
                    category=e.category,
                    amount_inr=e.amount_inr,
                    due_date=e.due_date.isoformat() if e.due_date else None,
                )
            )
        except DuplicateCase:
            continue
    session.flush()
    return opened
