"""Phase 6 checkpoint: L1 and L3 happy paths end-to-end, event -> RECOVERED.

Fully local (no live API): simulator-shaped events through ingestion,
diagnosis, planning, the guardrails gate, execution, payment observation and —
for L3 — a voice promise verified against a payment.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.cases import CaseState, transition
from agent.detector import from_simulator, ingest
from agent.diagnosis import diagnose_case, load_error_map
from agent.guardrails import execute_action
from agent.policy import load_policy, plan_case
from channels.links import observe_payment, recovered_inr
from ledger import audit
from ledger.db import PlannedActionRow, get_engine
from ledger.promises import record_promise, verify_promises

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
POLICY = load_policy()
ERROR_MAP = load_error_map()


@pytest.fixture
def session(tmp_path):
    with Session(get_engine(tmp_path / "t.db")) as s:
        yield s


def _drive_to_awaiting(session, case, action):
    transition(session, case, CaseState.GATED)
    decision_row = execute_action(session, case, action, POLICY, NOW)
    assert decision_row is not None
    transition(session, case, CaseState.EXECUTING)
    transition(session, case, CaseState.AWAITING_OUTCOME)


def test_l1_happy_path_event_to_recovered(session):
    event = from_simulator(
        {
            "event_id": "evt_l1",
            "category": "L1",
            "customer_id": "cust_0007",
            "entity_type": "subscription",
            "entity_id": "sub_0042",
            "amount_inr": 499,
            "occurred_at": (NOW - timedelta(hours=2)).isoformat(),
            "error_code": "BAD_REQUEST_ERROR",
            "error_reason": "insufficient_funds",
            "error_description": "Customer's account lacked adequate balance",
        }
    )
    [case] = ingest(session, [event], NOW)
    d = diagnose_case(session, case, event, ERROR_MAP)
    assert d.root_cause == "INSUFFICIENT_FUNDS"
    actions = plan_case(session, case, POLICY, NOW)
    assert actions[0].action_type == "silent_retry"  # liquidity-window retry first
    planned = session.scalars(
        select(PlannedActionRow).where(PlannedActionRow.case_id == case.id)
    ).all()
    _drive_to_awaiting(session, case, planned[0])
    observe_payment(
        session,
        {"id": "pay_l1_1", "amount": 49900, "method": "upi", "notes": {"case_id": str(case.id)}},
        NOW + timedelta(days=5),
    )
    assert case.state == CaseState.RECOVERED
    assert recovered_inr(session) == 499
    ok, msg = audit.verify(session)
    assert ok, msg  # the whole journey is chain-verified


def test_l3_happy_path_with_voice_promise(session):
    due = NOW - timedelta(days=10)
    event = from_simulator(
        {
            "event_id": "evt_l3",
            "category": "L3",
            "customer_id": "cust_0011",
            "entity_type": "invoice",
            "entity_id": "inv_0007",
            "amount_inr": 18000,
            "occurred_at": due.isoformat(),
            "due_date": due.isoformat(),
        }
    )
    [case] = ingest(session, [event], NOW)
    diagnose_case(session, case, event, ERROR_MAP)
    actions = plan_case(session, case, POLICY, NOW)
    assert "voice_call" in {a.action_type for a in actions}  # ₹18k, 10d overdue: eligible
    planned = session.scalars(
        select(PlannedActionRow).where(PlannedActionRow.case_id == case.id)
    ).all()
    _drive_to_awaiting(session, case, planned[0])  # email reminder executes
    promise_due = NOW + timedelta(days=4)
    record_promise(
        session,
        case,
        amount_inr=18000,
        due_date=promise_due,
        now=NOW,
        confidence=0.95,
        transcript_ref="transcripts/call_003.json",
    )
    assert case.state == CaseState.PROMISE_PENDING
    observe_payment(
        session,
        {
            "id": "pay_l3_1",
            "amount": 1800000,
            "method": "netbanking",
            "notes": {"case_id": str(case.id)},
        },
        promise_due - timedelta(days=1),
    )
    changed = verify_promises(session, promise_due)
    assert [p.status for p in changed] == ["KEPT"]
    assert case.state == CaseState.RECOVERED
    assert recovered_inr(session) == 18000
    ok, msg = audit.verify(session)
    assert ok, msg
