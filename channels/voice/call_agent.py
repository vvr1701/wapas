"""Call agent (FR-7.1/7.2/7.3 glue).

Single responsibility: run one call session against a RecoveryCase — the live
Claude conversation function, the rail triggers (opt-out, dispute check, abuse
escalation) wired to real case state, and post-call promise extraction feeding
the promise ledger or the human-review queue. Works identically in text mode
(FR-7.4) and under the audio console.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from agent.escalation import EscalationReason, escalate
from agent.guardrails import opt_out
from agent.llm import CONVERSATION_MODEL, call_claude, load_prompt
from channels.voice.policy import (
    MAX_PROMISE_DAYS,
    MIN_PROMISE_PCT,
    AgentTurn,
    CallFacts,
    CallSession,
    respond,
)
from channels.voice.promise_parser import extract_promise
from ledger import audit
from ledger.db import RecoveryCaseRow
from ledger.promises import record_promise


def claude_conversation(db: Session | None):
    """The live LLM for policy.respond — Sonnet 5, short streaming-friendly turns."""

    def llm(call: CallSession, customer_text: str) -> str:
        history = "\n".join(f"{t['role'].upper()}: {t['text']}" for t in call.transcript)
        prompt, prompt_hash = load_prompt(
            "voice_policy.txt",
            customer_name=call.facts.customer_name,
            amount_inr=f"{call.facts.amount_inr:,}",
            due_date=call.facts.due_date,
            context=call.facts.context,
            today=call.facts.today,
            max_days=MAX_PROMISE_DAYS,
            min_pct=MIN_PROMISE_PCT,
        )
        return call_claude(
            db,
            purpose="conversation",
            prompt_file="voice_policy.txt",
            prompt=f"{prompt}\n\nCONVERSATION SO FAR:\n{history}\n\nCUSTOMER: {customer_text}",
            prompt_hash=prompt_hash,
            model=CONVERSATION_MODEL,
            max_tokens=200,
        )

    return llm


def apply_turn_effects(db: Session, case: RecoveryCaseRow, turn: AgentTurn) -> None:
    """Rail triggers -> real state, audit-paired. LLM output never reaches here."""
    if turn.suspicious_input:
        audit.append(
            db,
            actor="customer",
            event_type="suspicious_input",
            case_id=case.id,
            payload={"note": "possible prompt injection in customer speech; treated as content"},
        )
    if turn.trigger_opt_out:
        opt_out(db, case.customer_id, source="in_call_stop_phrase")
    if turn.trigger_abuse_escalation:
        escalate(
            db,
            case,
            EscalationReason.ABUSE_DISTRESS,
            recommended="Human follow-up; customer distressed on call.",
        )
    if turn.trigger_dispute_check:
        audit.append(
            db,
            actor="system",
            event_type="dispute_check_requested",
            case_id=case.id,
            payload={"source": "voice_call"},
        )
        escalate(
            db,
            case,
            EscalationReason.DISPUTE,
            recommended="Verify claimed payment against ledger; confirm back to customer.",
        )


def finish_call(db: Session, case: RecoveryCaseRow, call: CallSession) -> dict:
    """Post-call: extract promise, apply rails, record or route to human review.
    A case already terminal (opted out / escalated during the call) gets NO
    further processing — FR-5.2 outranks extraction."""
    from agent.cases import TERMINAL, CaseState

    if CaseState(case.state) in TERMINAL:
        return {"outcome": "case_terminal", "state": case.state}
    decision = extract_promise(
        db,
        call.transcript,
        amount_due_inr=case.amount_due_inr,
        call_date=datetime.now(UTC).date(),
    )
    if decision.auto_record and decision.extracted is not None:
        promise = record_promise(
            db,
            case,
            amount_inr=decision.extracted.amount_inr,
            due_date=datetime.fromisoformat(decision.extracted.date).replace(tzinfo=UTC),
            now=datetime.now(UTC),
            conditions=decision.extracted.conditions,
            confidence=decision.extracted.confidence,
            transcript_ref=f"call_case{case.id}",
        )
        return {"outcome": "promise_recorded", "promise_id": promise.id}
    if decision.review_reason is not None:
        escalate(
            db,
            case,
            EscalationReason.EXTRACTION_UNCERTAIN,
            recommended=f"Review transcript; extraction flagged: {decision.review_reason}",
        )
        return {"outcome": "human_review", "reason": decision.review_reason}
    return {"outcome": "no_promise"}


def new_call(case: RecoveryCaseRow, customer_name: str, today: str) -> CallSession:
    return CallSession(
        facts=CallFacts(
            case_id=case.id,
            customer_id=case.customer_id,
            customer_name=customer_name,
            amount_inr=case.amount_due_inr,
            due_date=case.due_date or "",
            today=today,
        )
    )


__all__ = ["claude_conversation", "apply_turn_effects", "finish_call", "new_call", "respond"]
