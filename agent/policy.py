"""Policy engine — playbooks as config-as-code (FR-4.1, FR-4.2).

Single responsibility: given a diagnosed case and the loaded policy, emit an
ordered plan of PlannedActions, each citing rule_id + human-readable rationale +
the policy file's content hash. Changing a plan requires only a YAML edit.
Whether an action is ALLOWED at execution time is the guardrails gate's job
(Phase 4) — never decided here, never by an LLM.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agent.cases import CaseState, transition
from ledger import audit
from ledger.db import PlannedActionRow, RecoveryCaseRow

POLICIES_PATH = Path("config/policies.yaml")


class PlaybookAction(BaseModel):
    action: str
    channel: str
    at: str
    if_value_gte: int | None = None
    if_voice_eligible: bool = False


class Policy(BaseModel):
    """Validated view of policies.yaml plus its content hash."""

    version: int
    contact_window: dict
    caps: dict
    cooldowns_hours: dict
    voice_eligibility: dict
    salary_days: list[int]
    playbooks: dict[str, list[PlaybookAction]]
    version_hash: str


class PlannedAction(BaseModel):
    """The explainable unit of intent (FR-4.2)."""

    case_id: int
    action_type: str
    channel: str
    scheduled_for: datetime
    rule_id: str
    rationale: str
    policy_version_hash: str


def load_policy(path: Path = POLICIES_PATH) -> Policy:
    text = path.read_text()
    data = yaml.safe_load(text)
    return Policy(**data, version_hash=hashlib.sha256(text.encode()).hexdigest())


def _playbook_key(case: RecoveryCaseRow) -> str:
    key = f"{case.category}.{case.root_cause}"
    return key


def _resolve_at(spec: str, *, now: datetime, due: datetime | None, policy: Policy) -> datetime:
    """Turn a timing spec into a concrete UTC datetime (see policies.yaml legend)."""
    if spec == "liquidity_window":
        tz = ZoneInfo(policy.contact_window["tz"])
        local = now.astimezone(tz)
        open_h, open_m = map(int, policy.contact_window["start"].split(":"))
        for ahead in range(1, 32):
            candidate = (local + timedelta(days=ahead)).replace(
                hour=open_h, minute=open_m, second=0, microsecond=0
            )
            if candidate.day in policy.salary_days:
                return candidate.astimezone(UTC)
        raise ValueError("no salary day within 31 days")  # unreachable with sane config
    if m := re.fullmatch(r"\+(\d+)([mhd])", spec):
        n, unit = int(m.group(1)), m.group(2)
        return now + timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[unit]: n})
    if m := re.fullmatch(r"due\+(\d+)d", spec):
        if due is None:
            return now  # no due anchor: act now rather than never
        return due + timedelta(days=int(m.group(1)))
    raise ValueError(f"unrecognized timing spec: {spec}")


def _voice_eligible(case: RecoveryCaseRow, policy: Policy, now: datetime) -> bool:
    ve = policy.voice_eligibility
    if case.amount_due_inr < ve["min_amount_inr"]:
        return False
    if case.due_date is None:
        return False
    overdue_days = (now - datetime.fromisoformat(case.due_date)).days
    return overdue_days >= ve["min_days_overdue"]


def plan(case: RecoveryCaseRow, policy: Policy, now: datetime) -> list[PlannedAction]:
    """Ordered plan for a diagnosed case. Unknown (category, cause) pairs fall
    back to the UNKNOWN playbook: escalate, never improvise."""
    key = _playbook_key(case)
    book = policy.playbooks.get(key) or policy.playbooks["UNKNOWN"]
    book_key = key if key in policy.playbooks else "UNKNOWN"
    due = datetime.fromisoformat(case.due_date) if case.due_date else None
    actions: list[PlannedAction] = []
    for i, pa in enumerate(book):
        if pa.if_value_gte is not None and case.amount_due_inr < pa.if_value_gte:
            continue
        if pa.if_voice_eligible and not _voice_eligible(case, policy, now):
            continue
        when = _resolve_at(pa.at, now=now, due=due, policy=policy)
        rule_id = f"{book_key}#{i}"
        actions.append(
            PlannedAction(
                case_id=case.id,
                action_type=pa.action,
                channel=pa.channel,
                scheduled_for=when,
                rule_id=rule_id,
                rationale=(
                    f"{case.category} case diagnosed {case.root_cause} "
                    f"(₹{case.amount_due_inr:,} due): playbook {book_key} step {i + 1} "
                    f"schedules {pa.action} via {pa.channel} at {pa.at} "
                    f"-> {when.isoformat()}"
                ),
                policy_version_hash=policy.version_hash,
            )
        )
    return actions


def plan_case(
    session: Session, case: RecoveryCaseRow, policy: Policy, now: datetime
) -> list[PlannedAction]:
    """Persist the plan and move the case DIAGNOSED->PLANNED, audit-paired per
    action (the dashboard shows rationale verbatim from the audit log)."""
    actions = plan(case, policy, now)
    for a in actions:
        session.add(
            PlannedActionRow(
                case_id=a.case_id,
                action_type=a.action_type,
                channel=a.channel,
                scheduled_for=a.scheduled_for.isoformat(),
                rule_id=a.rule_id,
                rationale=a.rationale,
                policy_version_hash=a.policy_version_hash,
            )
        )
        audit.append(
            session,
            actor="agent",
            event_type="action_planned",
            case_id=case.id,
            rule_id=a.rule_id,
            policy_version_hash=a.policy_version_hash,
            payload={
                "action_type": a.action_type,
                "channel": a.channel,
                "scheduled_for": a.scheduled_for.isoformat(),
                "rationale": a.rationale,
            },
        )
    transition(
        session,
        case,
        CaseState.PLANNED,
        actor="agent",
        payload={"actions": len(actions), "playbook": _playbook_key(case)},
    )
    return actions
