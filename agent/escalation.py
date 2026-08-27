"""Escalation to humans (FR-9.1).

Single responsibility: build a self-sufficient context packet (a judge could act
on it without reading code) and hand the case to the human queue as ESCALATED.
Human acknowledgements are logged too — symmetry applies to people (FR-9.2).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.cases import CaseState, transition
from ledger import audit
from ledger.db import AuditRow, EscalationRow, ExecutedActionRow, RecoveryCaseRow


class EscalationReason(StrEnum):
    DISPUTE = "DISPUTE"
    ABUSE_DISTRESS = "ABUSE_DISTRESS"
    EXTRACTION_UNCERTAIN = "EXTRACTION_UNCERTAIN"
    HIGH_VALUE_STALLED = "HIGH_VALUE_STALLED"
    POLICY_EXHAUSTED_HIGH_VALUE = "POLICY_EXHAUSTED_HIGH_VALUE"
    UNKNOWN_DIAGNOSIS = "UNKNOWN_DIAGNOSIS"


def build_context_packet(session: Session, case: RecoveryCaseRow, *, recommended: str) -> dict:
    """Everything a human needs on one page: summary, diagnosis, actions tried,
    timeline (from the audit log — proving it is complete), transcripts."""
    timeline = [
        {
            "ts": r.ts,
            "actor": r.actor,
            "event": r.event_type,
            "rule_id": r.rule_id,
            "detail": json.loads(r.payload_json),
        }
        for r in session.scalars(
            select(AuditRow).where(AuditRow.case_id == case.id).order_by(AuditRow.id)
        )
    ]
    executed = session.scalars(
        select(ExecutedActionRow).where(ExecutedActionRow.case_id == case.id)
    )
    return {
        "case_summary": {
            "case_id": case.id,
            "entity_id": case.entity_id,
            "customer_id": case.customer_id,
            "category": case.category,
            "amount_due_inr": case.amount_due_inr,
            "state": case.state,
            "opened_ts": case.opened_ts,
            "due_date": case.due_date,
        },
        "diagnosis": {
            "root_cause": case.root_cause,
            "confidence": case.diagnosis_confidence,
            "source": case.diagnosis_source,
        },
        "actions_tried": [
            {
                "action_type": e.action_type,
                "channel": e.channel,
                "executed_ts": e.executed_ts,
                "result": e.result,
            }
            for e in executed
        ],
        "timeline": timeline,
        "transcripts": [
            t["detail"].get("transcript_ref")
            for t in timeline
            if t["event"] == "promise_recorded" and t["detail"].get("transcript_ref")
        ],
        "recommended_next_step": recommended,
    }


def escalate(
    session: Session,
    case: RecoveryCaseRow,
    reason: EscalationReason,
    *,
    recommended: str,
) -> EscalationRow:
    """Persist the packet, move the case to ESCALATED (terminal), audit-paired."""
    packet = build_context_packet(session, case, recommended=recommended)
    row = EscalationRow(
        case_id=case.id,
        reason=reason,
        context_packet_json=json.dumps(packet, sort_keys=True),
        created_ts=datetime.now(UTC).isoformat(),
    )
    session.add(row)
    session.flush()
    transition(
        session,
        case,
        CaseState.ESCALATED,
        actor="agent",
        payload={"reason": reason, "escalation_id": row.id},
    )
    return row


def acknowledge(session: Session, escalation: EscalationRow, *, by: str) -> None:
    """FR-9.2: the human action is logged too."""
    escalation.acked_by = by
    escalation.acked_ts = datetime.now(UTC).isoformat()
    audit.append(
        session,
        actor="human",
        event_type="escalation_acknowledged",
        case_id=escalation.case_id,
        payload={"escalation_id": escalation.id, "by": by},
    )
    session.flush()
