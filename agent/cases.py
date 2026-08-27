"""Case lifecycle spine (PRD §4.2) and the FR-10.2 service layer.

Single responsibility: every RecoveryCase write goes through open_case/transition,
which pair the business write with an audit record in the same transaction —
audit symmetry is enforced here, not left to discipline. Transitions happen only
along defined edges; terminal states are immutable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from ledger import audit
from ledger.db import RecoveryCaseRow


class CaseState(StrEnum):
    DETECTED = "DETECTED"
    DIAGNOSED = "DIAGNOSED"
    PLANNED = "PLANNED"
    GATED = "GATED"
    EXECUTING = "EXECUTING"
    AWAITING_OUTCOME = "AWAITING_OUTCOME"
    PROMISE_PENDING = "PROMISE_PENDING"
    RECOVERED = "RECOVERED"
    ESCALATED = "ESCALATED"
    STOPPED = "STOPPED"
    EXHAUSTED = "EXHAUSTED"


TERMINAL = {CaseState.RECOVERED, CaseState.ESCALATED, CaseState.STOPPED, CaseState.EXHAUSTED}

_EDGES: dict[CaseState, set[CaseState]] = {
    CaseState.DETECTED: {CaseState.DIAGNOSED},
    CaseState.DIAGNOSED: {CaseState.PLANNED},
    CaseState.PLANNED: {CaseState.GATED},
    CaseState.GATED: {CaseState.EXECUTING},
    CaseState.EXECUTING: {CaseState.AWAITING_OUTCOME},
    CaseState.AWAITING_OUTCOME: {
        CaseState.RECOVERED,
        CaseState.PROMISE_PENDING,
        CaseState.PLANNED,  # retry loop, until caps
        CaseState.ESCALATED,
        CaseState.EXHAUSTED,
    },
    CaseState.PROMISE_PENDING: {CaseState.RECOVERED, CaseState.PLANNED, CaseState.ESCALATED},
}
# Opt-out or a blocking rule may stop any non-terminal case instantly (FR-5.2).
EDGES = {s: targets | {CaseState.STOPPED} for s, targets in _EDGES.items()}


class InvalidTransition(Exception):
    """Raised on any edge not defined in §4.2 or any write to a terminal case."""


class DuplicateCase(Exception):
    """Raised when a case already exists for the underlying entity (FR-2.2)."""


def open_case(
    session: Session,
    *,
    entity_id: str,
    customer_id: str,
    category: str,
    amount_inr: int,
    due_date: str | None = None,
) -> RecoveryCaseRow:
    """Open a case in DETECTED with its paired audit record."""
    existing = session.scalar(select(RecoveryCaseRow).where(RecoveryCaseRow.entity_id == entity_id))
    if existing is not None:
        raise DuplicateCase(f"case {existing.id} already covers entity {entity_id}")
    row = RecoveryCaseRow(
        entity_id=entity_id,
        customer_id=customer_id,
        category=category,
        amount_due_inr=amount_inr,
        due_date=due_date,
        state=CaseState.DETECTED,
        opened_ts=datetime.now(UTC).isoformat(),
    )
    session.add(row)
    session.flush()
    audit.append(
        session,
        actor="system",
        event_type="case_opened",
        case_id=row.id,
        payload={"entity_id": entity_id, "category": category, "amount_inr": amount_inr},
    )
    return row


def transition(
    session: Session,
    case: RecoveryCaseRow,
    to: CaseState,
    *,
    actor: str = "system",
    rule_id: str | None = None,
    payload: dict | None = None,
) -> RecoveryCaseRow:
    """Move a case along a defined edge, audit-paired. Terminal states are immutable."""
    current = CaseState(case.state)
    if current in TERMINAL:
        raise InvalidTransition(f"case {case.id} is terminal ({current}); no further writes")
    if to not in EDGES[current]:
        raise InvalidTransition(f"{current} -> {to} is not a defined edge")
    case.state = to
    if to in TERMINAL:
        case.closed_ts = datetime.now(UTC).isoformat()
    audit.append(
        session,
        actor=actor,
        event_type="state_transition",
        case_id=case.id,
        rule_id=rule_id,
        payload={"from": current, "to": to, **(payload or {})},
    )
    session.flush()
    return case
