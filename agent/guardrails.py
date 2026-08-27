"""Guardrails gate (FR-5.1, 5.2, 5.3) — every action passes here or dies here.

Single responsibility: deterministic permission checks immediately before any
execution, opt-out semantics, and idempotent at-most-once execution. NO LLM is
ever consulted in this module; permissions must be provable (PRD §6.1).
Checks run in FR-5.1 order; the first failure blocks and is audited.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.cases import TERMINAL, CaseState, transition
from agent.policy import Policy
from ledger import audit
from ledger.db import CustomerRow, ExecutedActionRow, PlannedActionRow, RecoveryCaseRow

NUDGE_TYPES = {"link_nudge", "email_nudge", "wa_nudge", "method_update_nudge"}
CUSTOMER_CONTACT_TYPES = NUDGE_TYPES | {"voice_call"}

# Rule-list stop intents (FR-5.2); an LLM fallback (P1) may ADD triggers later,
# never remove these. Word-bounded so "stopped by the shop" doesn't trip it.
_STOP_PATTERNS = [
    r"\bstop\b(?!ped\b)",
    r"\bunsubscribe\b",
    r"\bcall\s+mat\s+karo\b",
    r"\bmat\s+karo\b",
    r"\bmat\s+bhejo\b",
    r"\bremove\s+my\s+number\b",
    r"\bdon'?t\s+(call|message|contact)\b",
]


class GateDecision(BaseModel):
    allowed: bool
    reason: str | None = None  # first failed check, e.g. "cap_retries"
    checks_passed: list[str] = []
    replan_for: datetime | None = None  # FR-5.3: when a window block can reschedule


def idempotency_key(case_id: int, action_type: str, attempt_no: int) -> str:
    """FR-5.1(8): key = hash(case_id, action_type, attempt_no)."""
    return hashlib.sha256(f"{case_id}|{action_type}|{attempt_no}".encode()).hexdigest()


def detect_stop_intent(text: str) -> bool:
    low = text.lower()
    return any(re.search(p, low) for p in _STOP_PATTERNS)


def _executed(session: Session, case_id: int) -> list[ExecutedActionRow]:
    return list(
        session.scalars(select(ExecutedActionRow).where(ExecutedActionRow.case_id == case_id))
    )


def _next_window_open(now: datetime, policy: Policy) -> datetime:
    tz = ZoneInfo(policy.contact_window["tz"])
    local = now.astimezone(tz)
    open_h, open_m = map(int, policy.contact_window["start"].split(":"))
    candidate = local.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


def _in_window(now: datetime, policy: Policy) -> bool:
    tz = ZoneInfo(policy.contact_window["tz"])
    local = now.astimezone(tz)
    start_h, start_m = map(int, policy.contact_window["start"].split(":"))
    end_h, end_m = map(int, policy.contact_window["end"].split(":"))
    return (start_h, start_m) <= (local.hour, local.minute) < (end_h, end_m)


def check(
    session: Session,
    case: RecoveryCaseRow,
    action: PlannedActionRow,
    policy: Policy,
    now: datetime,
) -> GateDecision:
    """Run every FR-5.1 check in order; first failure blocks."""
    passed: list[str] = []

    def blocked(reason: str, replan_for: datetime | None = None) -> GateDecision:
        return GateDecision(
            allowed=False, reason=reason, checks_passed=passed, replan_for=replan_for
        )

    # (1) case not terminal / action not cancelled
    if CaseState(case.state) in TERMINAL or action.status == "CANCELLED":
        return blocked("case_terminal")
    passed.append("case_not_terminal")

    history = _executed(session, case.id)

    # (2) attempt caps per kind; escalate is internal (no customer contact, no cap)
    def kind_of(t: str) -> str:
        if t == "silent_retry":
            return "retries"
        if t == "voice_call":
            return "voice_calls"
        return "internal" if t == "escalate" else "nudges"

    kind = kind_of(action.action_type)
    if kind in policy.caps:
        used = sum(1 for e in history if kind_of(e.action_type) == kind)
        if used >= policy.caps[kind]:
            return blocked(f"cap_{kind}")
    passed.append("caps")

    # (3) cooldowns
    contacts = [e for e in history if e.action_type in CUSTOMER_CONTACT_TYPES]
    last_contact = max((datetime.fromisoformat(e.executed_ts) for e in contacts), default=None)
    if action.action_type in NUDGE_TYPES and last_contact is not None:
        if now - last_contact < timedelta(hours=policy.cooldowns_hours["nudge"]):
            return blocked("cooldown_nudge")
    if action.action_type == "voice_call" and last_contact is not None:
        cooldown = timedelta(hours=policy.cooldowns_hours["voice_after_last_contact"])
        if now - last_contact < cooldown:
            return blocked("cooldown_voice")
    passed.append("cooldowns")

    # (4) contact-time window; silent actions exempt (rate-limited via caps)
    if action.action_type in CUSTOMER_CONTACT_TYPES and not _in_window(now, policy):
        return blocked("outside_contact_window", replan_for=_next_window_open(now, policy))
    passed.append("contact_window")

    # (5) opt-out registry
    reg = session.scalar(select(CustomerRow).where(CustomerRow.customer_id == case.customer_id))
    if reg is not None and reg.opted_out:
        return blocked("customer_opted_out")
    passed.append("opt_out_registry")

    # (6) voice value threshold
    if (
        action.action_type == "voice_call"
        and case.amount_due_inr < policy.voice_eligibility["min_amount_inr"]
    ):
        return blocked("voice_value_threshold")
    passed.append("voice_value_threshold")

    # (7) incentive bounding (FR-4.3)
    if action.incentive_inr > 0:
        inc = policy.incentives
        if not inc.get("enabled", False):
            return blocked("incentive_disabled")
        if case.root_cause not in inc["allowed_root_causes"]:
            return blocked("incentive_root_cause_not_allowed")
        per_case_cap = min(
            inc["per_case_inr_max"], case.amount_due_inr * inc["per_case_pct_max"] // 100
        )
        if action.incentive_inr > per_case_cap:
            return blocked("incentive_per_case_cap")
        if any(e.incentive_inr > 0 for e in history):
            return blocked("incentive_already_given")
        spent = sum(
            e.incentive_inr for e in session.scalars(select(ExecutedActionRow)) if e.incentive_inr
        )
        if spent + action.incentive_inr > inc["batch_budget_inr"]:
            return blocked("incentive_budget_exhausted")
    passed.append("incentive_budget")

    # (8) idempotency is enforced structurally in execute_action (unique key);
    # the check here is that the gate produced the key's inputs deterministically.
    passed.append("idempotency_ready")
    return GateDecision(allowed=True, checks_passed=passed)


def execute_action(
    session: Session,
    case: RecoveryCaseRow,
    action: PlannedActionRow,
    policy: Policy,
    now: datetime,
    perform: Callable[[], dict] | None = None,
) -> ExecutedActionRow | None:
    """Gate then execute at-most-once. Blocked -> audited, optionally replanned
    (FR-5.3), returns None. Allowed -> idempotent execution row; a replayed key
    returns the existing row untouched (crash-safe double-fire)."""
    already = session.scalar(
        select(ExecutedActionRow).where(ExecutedActionRow.planned_id == action.id)
    )
    if already is not None:
        return already  # crash-retry replay of an executed action: at-most-once
    decision = check(session, case, action, policy, now)
    if not decision.allowed:
        audit.append(
            session,
            actor="system",
            event_type="action_blocked",
            case_id=case.id,
            rule_id=decision.reason,
            payload={
                "action_type": action.action_type,
                "reason": decision.reason,
                "checks_passed": decision.checks_passed,
            },
        )
        if decision.replan_for is not None:
            action.scheduled_for = decision.replan_for.isoformat()
            audit.append(
                session,
                actor="system",
                event_type="action_replanned",
                case_id=case.id,
                payload={
                    "action_type": action.action_type,
                    "rescheduled_for": action.scheduled_for,
                    "why": decision.reason,
                },
            )
        session.flush()
        return None

    attempt_no = (
        sum(1 for e in _executed(session, case.id) if e.action_type == action.action_type) + 1
    )
    key = idempotency_key(case.id, action.action_type, attempt_no)
    existing = session.scalar(
        select(ExecutedActionRow).where(ExecutedActionRow.idempotency_key == key)
    )
    if existing is not None:
        return existing  # double-fire: never execute the same attempt twice

    outcome = perform() if perform is not None else {}
    row = ExecutedActionRow(
        planned_id=action.id,
        case_id=case.id,
        action_type=action.action_type,
        channel=action.channel,
        idempotency_key=key,
        executed_ts=now.isoformat(),
        result=outcome.get("result", "SUCCESS"),
        external_ref=outcome.get("external_ref"),
        incentive_inr=action.incentive_inr,
    )
    session.add(row)
    action.status = "EXECUTED"
    audit.append(
        session,
        actor="agent",
        event_type="action_executed",
        case_id=case.id,
        rule_id=action.rule_id,
        policy_version_hash=action.policy_version_hash,
        payload={
            "action_type": action.action_type,
            "channel": action.channel,
            "idempotency_key": key,
            "attempt_no": attempt_no,
            "external_ref": outcome.get("external_ref"),
        },
    )
    session.flush()
    return row


def opt_out(session: Session, customer_id: str, *, source: str, ts: str | None = None) -> None:
    """FR-5.2: instant, permanent, logged. Cancels every pending action and
    stops every non-terminal case for the customer. `ts` lets sim-time callers
    stamp the world clock instead of the wall clock."""
    reg = session.scalar(select(CustomerRow).where(CustomerRow.customer_id == customer_id))
    if reg is None:
        reg = CustomerRow(customer_id=customer_id)
        session.add(reg)
    if reg.opted_out:
        return  # permanent: first trigger wins, nothing to redo
    reg.opted_out = True
    reg.opt_out_ts = ts or datetime.now(UTC).isoformat()
    reg.opt_out_source = source
    audit.append(
        session,
        actor="customer",
        event_type="opt_out",
        payload={"customer_id": customer_id, "source": source},
    )
    cases = session.scalars(
        select(RecoveryCaseRow).where(RecoveryCaseRow.customer_id == customer_id)
    )
    for case in cases:
        pending = session.scalars(
            select(PlannedActionRow).where(
                PlannedActionRow.case_id == case.id, PlannedActionRow.status == "PENDING"
            )
        )
        for p in pending:
            p.status = "CANCELLED"
            audit.append(
                session,
                actor="system",
                event_type="action_cancelled",
                case_id=case.id,
                payload={"action_type": p.action_type, "why": "opt_out"},
            )
        if CaseState(case.state) not in TERMINAL:
            transition(
                session,
                case,
                CaseState.STOPPED,
                actor="customer",
                payload={"why": "opt_out", "source": source},
            )
    session.flush()
