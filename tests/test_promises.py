"""FR-8.1 exit-gate tests: KEPT / BROKEN / PARTIAL with the +1-day grace window."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.cases import CaseState, open_case, transition
from channels.links import observe_payment
from ledger.db import PaymentObservedRow, get_engine
from ledger.promises import promise_metrics, record_promise, verify_promises

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
DUE = NOW + timedelta(days=5)


@pytest.fixture
def session(tmp_path):
    with Session(get_engine(tmp_path / "t.db")) as s:
        yield s


def _promised_case(session, entity="inv_1", amount=18000):
    case = open_case(
        session, entity_id=entity, customer_id="cust_0001", category="L3", amount_inr=amount
    )
    case.root_cause = "INVOICE_FORGOTTEN"
    for st in (
        CaseState.DIAGNOSED,
        CaseState.PLANNED,
        CaseState.GATED,
        CaseState.EXECUTING,
        CaseState.AWAITING_OUTCOME,
    ):
        transition(session, case, st)
    promise = record_promise(
        session,
        case,
        amount_inr=amount,
        due_date=DUE,
        now=NOW,
        confidence=0.95,
        transcript_ref="transcripts/call_001.json",
    )
    assert case.state == CaseState.PROMISE_PENDING
    return case, promise


def _pay(session, case, amount, when):
    return observe_payment(
        session,
        {
            "id": f"pay_{case.id}_{when.isoformat()}",
            "amount": amount * 100,
            "method": "upi",
            "notes": {"case_id": str(case.id)},
        },
        when,
    )


def test_promise_kept_full_payment_within_grace(session):
    case, promise = _promised_case(session)
    _pay(session, case, 18000, DUE + timedelta(hours=20))  # inside due+1d grace
    changed = verify_promises(session, DUE + timedelta(days=1))
    assert [p.status for p in changed] == ["KEPT"]
    assert case.state == CaseState.RECOVERED
    payment = session.scalar(select(PaymentObservedRow))
    assert payment.matched_promise_id == promise.id
    assert promise_metrics(session) == {
        "made": 1,
        "kept": 1,
        "kept_rate": 1.0,
        "inr_via_promises": 18000,
    }


def test_promise_broken_nothing_paid_after_grace(session):
    case, promise = _promised_case(session)
    still_open = verify_promises(session, DUE + timedelta(hours=23))
    assert still_open == [] and promise.status == "PENDING"  # grace not over yet
    changed = verify_promises(session, DUE + timedelta(days=1, minutes=1))
    assert [p.status for p in changed] == ["BROKEN"]
    assert case.state == CaseState.PLANNED  # gentle follow-up replan, not silence


def test_promise_partial_reduces_due_and_replans(session):
    case, promise = _promised_case(session, amount=18000)
    _pay(session, case, 8000, DUE - timedelta(days=1))
    assert case.state == CaseState.PROMISE_PENDING  # partial never fake-recovers
    changed = verify_promises(session, DUE + timedelta(days=2))
    assert [p.status for p in changed] == ["PARTIAL"]
    assert case.amount_due_inr == 10000
    assert case.state == CaseState.PLANNED


def test_payment_before_promise_does_not_count(session):
    case = open_case(
        session, entity_id="inv_pre", customer_id="cust_0002", category="L3", amount_inr=5000
    )
    case.root_cause = "INVOICE_FORGOTTEN"
    for st in (
        CaseState.DIAGNOSED,
        CaseState.PLANNED,
        CaseState.GATED,
        CaseState.EXECUTING,
        CaseState.AWAITING_OUTCOME,
    ):
        transition(session, case, st)
    _pay(session, case, 5000, NOW - timedelta(days=2))  # pre-promise payment recovers case
    assert case.state == CaseState.RECOVERED
