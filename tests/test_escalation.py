"""FR-9.1 exit-gate test: context packet renders complete from a fixture case."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.cases import CaseState, open_case, transition
from agent.escalation import EscalationReason, acknowledge, build_context_packet, escalate
from agent.guardrails import execute_action
from agent.policy import load_policy
from ledger.db import AuditRow, PlannedActionRow, get_engine
from ledger.promises import record_promise

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
POLICY = load_policy()


@pytest.fixture
def session(tmp_path):
    with Session(get_engine(tmp_path / "t.db")) as s:
        yield s


def _fixture_case(session):
    """A case with real history: diagnosed, planned, one executed nudge, a promise."""
    case = open_case(
        session, entity_id="inv_77", customer_id="cust_0042", category="L3", amount_inr=52000
    )
    case.root_cause = "CLIENT_CASHFLOW_DELAY"
    case.diagnosis_confidence = 0.7
    case.diagnosis_source = "rule"
    for st in (CaseState.DIAGNOSED, CaseState.PLANNED):
        transition(session, case, st)
    action = PlannedActionRow(
        case_id=case.id,
        action_type="email_nudge",
        channel="email",
        scheduled_for=NOW.isoformat(),
        rule_id="L3.CLIENT_CASHFLOW_DELAY#0",
        rationale="reminder ladder step 1",
        policy_version_hash=POLICY.version_hash,
    )
    session.add(action)
    session.flush()
    execute_action(session, case, action, POLICY, NOW)
    for st in (CaseState.GATED, CaseState.EXECUTING, CaseState.AWAITING_OUTCOME):
        transition(session, case, st)
    record_promise(
        session,
        case,
        amount_inr=52000,
        due_date=NOW,
        now=NOW,
        confidence=0.9,
        transcript_ref="transcripts/call_007.json",
    )
    return case


def test_context_packet_complete(session):
    case = _fixture_case(session)
    packet = build_context_packet(session, case, recommended="Call client CFO; verify dispute")
    assert packet["case_summary"]["case_id"] == case.id
    assert packet["case_summary"]["amount_due_inr"] == 52000
    assert packet["diagnosis"] == {
        "root_cause": "CLIENT_CASHFLOW_DELAY",
        "confidence": 0.7,
        "source": "rule",
    }
    assert packet["actions_tried"] and packet["actions_tried"][0]["action_type"] == "email_nudge"
    assert len(packet["timeline"]) >= 6  # opened + transitions + executed + promise
    assert packet["transcripts"] == ["transcripts/call_007.json"]
    assert packet["recommended_next_step"]


def test_escalate_persists_packet_and_closes_case(session):
    case = _fixture_case(session)
    row = escalate(
        session, case, EscalationReason.HIGH_VALUE_STALLED, recommended="Human follow-up"
    )
    assert case.state == CaseState.ESCALATED
    stored = json.loads(row.context_packet_json)
    assert stored["case_summary"]["case_id"] == case.id
    assert row.reason == EscalationReason.HIGH_VALUE_STALLED


def test_acknowledge_logs_human_action(session):
    case = _fixture_case(session)
    row = escalate(session, case, EscalationReason.DISPUTE, recommended="Review dispute claim")
    acknowledge(session, row, by="ops@kirana.plus")
    assert row.acked_by and row.acked_ts
    acks = [
        r for r in session.scalars(select(AuditRow)) if r.event_type == "escalation_acknowledged"
    ]
    assert len(acks) == 1 and acks[0].actor == "human"
