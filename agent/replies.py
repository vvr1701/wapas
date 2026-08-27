"""Inbound reply handling (FR-5.2 triggers, §6.4 adversarial posture).

Single responsibility: process a customer's free-text reply to a nudge with
deterministic rules — stop-intent fires the opt-out, dispute markers route to
human escalation, and anything smelling of prompt injection is treated as
content, never as command, and flagged in the audit log. No LLM is consulted
before state changes.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from agent.cases import CaseState
from agent.escalation import EscalationReason, escalate
from agent.guardrails import opt_out
from channels.voice.policy import Intent, classify_intent, is_suspicious
from ledger import audit
from ledger.db import RecoveryCaseRow


def process_reply(session: Session, case: RecoveryCaseRow, text: str) -> dict:
    """Returns what happened, for the outbox/dashboard view. Audit-paired."""
    audit.append(
        session,
        actor="customer",
        event_type="reply_received",
        case_id=case.id,
        payload={"text": text[:500]},
    )
    outcome: dict = {"handled": "none"}
    if is_suspicious(text):
        audit.append(
            session,
            actor="customer",
            event_type="suspicious_input",
            case_id=case.id,
            payload={"note": "possible prompt injection in reply; treated as content"},
        )
        outcome = {"handled": "flagged_suspicious"}
    intent = classify_intent(text)
    if intent == Intent.STOP:
        opt_out(session, case.customer_id, source="reply_stop_intent")
        return {"handled": "opt_out"}
    if intent == Intent.DISPUTE and CaseState(case.state) not in (
        CaseState.RECOVERED,
        CaseState.ESCALATED,
        CaseState.STOPPED,
        CaseState.EXHAUSTED,
    ):
        case.root_cause = "INVOICE_DISPUTED" if case.category == "L3" else case.root_cause
        escalate(
            session,
            case,
            EscalationReason.DISPUTE,
            recommended="Customer claims payment/dispute in reply; verify ledger.",
        )
        return {"handled": "dispute_escalated"}
    return outcome
