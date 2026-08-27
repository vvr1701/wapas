"""§4.2 / FR-2.x / FR-10.2 exit-gate tests: edges only, terminal immutability,
duplicate-case guard, audit symmetry, normalization parity."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agent.cases import (
    TERMINAL,
    CaseState,
    DuplicateCase,
    InvalidTransition,
    open_case,
    transition,
)
from agent.detector import (
    RevenueEvent,
    from_razorpay_invoice,
    from_simulator,
    ingest,
)
from ledger.db import AuditRow, RecoveryCaseRow, get_engine

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


@pytest.fixture
def session(tmp_path):
    with Session(get_engine(tmp_path / "t.db")) as s:
        yield s


def _open(session, entity="inv_0001"):
    return open_case(
        session, entity_id=entity, customer_id="cust_0001", category="L3", amount_inr=18000
    )


def test_happy_path_to_recovered(session):
    case = _open(session)
    path = [
        CaseState.DIAGNOSED,
        CaseState.PLANNED,
        CaseState.GATED,
        CaseState.EXECUTING,
        CaseState.AWAITING_OUTCOME,
        CaseState.RECOVERED,
    ]
    for state in path:
        transition(session, case, state)
    assert case.state == CaseState.RECOVERED
    assert case.closed_ts is not None


def test_undefined_edge_rejected(session):
    case = _open(session)
    with pytest.raises(InvalidTransition):
        transition(session, case, CaseState.EXECUTING)  # DETECTED -> EXECUTING undefined


def test_terminal_states_immutable(session):
    case = _open(session)
    transition(session, case, CaseState.STOPPED)
    for target in CaseState:
        with pytest.raises(InvalidTransition):
            transition(session, case, target)


def test_stop_reachable_from_any_nonterminal(session):
    for i, upto in enumerate(range(5)):
        case = _open(session, entity=f"inv_100{i}")
        path = [CaseState.DIAGNOSED, CaseState.PLANNED, CaseState.GATED, CaseState.EXECUTING]
        for state in path[:upto]:
            transition(session, case, state)
        transition(session, case, CaseState.STOPPED)  # never raises (FR-5.2 spine)
        assert case.state in TERMINAL


def test_promise_pending_flow(session):
    case = _open(session)
    for state in [
        CaseState.DIAGNOSED,
        CaseState.PLANNED,
        CaseState.GATED,
        CaseState.EXECUTING,
        CaseState.AWAITING_OUTCOME,
        CaseState.PROMISE_PENDING,
        CaseState.RECOVERED,
    ]:
        transition(session, case, state)
    assert case.state == CaseState.RECOVERED


def test_duplicate_case_service_and_constraint(session):
    _open(session)
    with pytest.raises(DuplicateCase):
        _open(session)  # service layer guard
    session.add(  # raw insert bypassing the service: DB constraint catches it
        RecoveryCaseRow(
            entity_id="inv_0001",
            customer_id="x",
            category="L3",
            amount_due_inr=1,
            state="DETECTED",
            opened_ts=NOW.isoformat(),
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_audit_symmetry(session):
    """FR-10.2: every business write has a paired audit record."""
    case = _open(session)
    writes = 1
    for state in [CaseState.DIAGNOSED, CaseState.PLANNED, CaseState.GATED, CaseState.STOPPED]:
        transition(session, case, state)
        writes += 1
    audit_count = session.scalar(select(func.count()).select_from(AuditRow))
    assert audit_count == writes


# --- FR-2.1/2.2: normalization parity and detection rules ----------------------


def _sim_event(**over) -> dict:
    base = dict(
        event_id="evt_0001",
        category="L3",
        customer_id="cust_TUx",
        entity_type="invoice",
        entity_id="inv_TUx001",
        amount_inr=18000,
        occurred_at=(NOW - timedelta(days=10)).isoformat(),
        due_date=(NOW - timedelta(days=3)).isoformat(),
    )
    return base | over


def test_both_paths_produce_identical_normalized_events():
    sim = from_simulator(_sim_event())
    rzp = from_razorpay_invoice(
        {
            "id": "inv_TUx001",
            "customer_id": "cust_TUx",
            "amount": 1800000,
            "created_at": int((NOW - timedelta(days=10)).timestamp()),
            "expire_by": int((NOW - timedelta(days=3)).timestamp()),
        },
        event_id="evt_0001",
    )
    assert isinstance(sim, RevenueEvent) and isinstance(rzp, RevenueEvent)
    assert sim.model_dump(exclude={"source"}) == rzp.model_dump(exclude={"source"})


def test_ingest_opens_cases_per_rules(session):
    events = [
        from_simulator(_sim_event()),  # L3 past due -> case
        from_simulator(  # L3 not yet due -> no case
            _sim_event(
                event_id="evt_0002",
                entity_id="inv_x2",
                due_date=(NOW + timedelta(days=2)).isoformat(),
            )
        ),
        from_simulator(  # L2 too young -> no case
            _sim_event(
                event_id="evt_0003",
                category="L2",
                entity_type="order",
                entity_id="order_x1",
                occurred_at=(NOW - timedelta(minutes=5)).isoformat(),
                due_date=None,
            )
        ),
        from_simulator(  # L2 aged past T -> case
            _sim_event(
                event_id="evt_0004",
                category="L2",
                entity_type="order",
                entity_id="order_x2",
                occurred_at=(NOW - timedelta(hours=2)).isoformat(),
                due_date=None,
            )
        ),
        from_simulator(  # L1 -> immediate case
            _sim_event(
                event_id="evt_0005",
                category="L1",
                entity_type="subscription",
                entity_id="sub_x1",
                amount_inr=499,
                due_date=None,
                error_code="BAD_REQUEST_ERROR",
                error_reason="payment_failed",
            )
        ),
    ]
    opened = ingest(session, events, NOW)
    assert {c.entity_id for c in opened} == {"inv_TUx001", "order_x2", "sub_x1"}
    # re-ingestion is idempotent: no new events, no new cases
    assert ingest(session, events, NOW) == []
