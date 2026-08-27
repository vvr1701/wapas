"""FR-3.1/3.2 exit-gate tests: table-driven diagnosis, every enum value covered,
unknown -> UNKNOWN, case application audit-paired."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from agent.cases import CaseState, open_case
from agent.detector import RevenueEvent
from agent.diagnosis import Diagnosis, RootCause, diagnose, diagnose_case, load_error_map
from agent.policy import load_policy, plan
from ledger.db import get_engine

ERROR_MAP = load_error_map()
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _event(category="L1", *, reason=None, auth_attempted=None) -> RevenueEvent:
    return RevenueEvent(
        event_id="evt_x",
        category=category,
        source="simulator",
        customer_id="cust_0001",
        entity_type={"L1": "subscription", "L2": "order", "L3": "invoice"}[category],
        entity_id="ent_x",
        amount_inr=499,
        occurred_at=NOW,
        error_reason=reason,
        auth_attempted=auth_attempted,
    )


# Table-driven: every rule-producible root cause, incl. the honest UNKNOWN.
DIAGNOSIS_TABLE = [
    (_event(reason="insufficient_funds"), RootCause.INSUFFICIENT_FUNDS),
    (_event(reason="card_expired"), RootCause.CARD_EXPIRED),
    (_event(reason="debit_instrument_blocked"), RootCause.CARD_EXPIRED),
    (_event(reason="mandate_cancelled"), RootCause.MANDATE_PAUSED_CANCELLED),
    (_event(reason="mandate_paused"), RootCause.MANDATE_PAUSED_CANCELLED),
    (_event(reason="gateway_technical_error"), RootCause.BANK_GATEWAY_DOWNTIME),
    (_event(reason="bank_technical_error"), RootCause.BANK_GATEWAY_DOWNTIME),
    (_event(reason="authentication_failed"), RootCause.AUTH_ABANDONED),
    (_event(reason="payment_timed_out"), RootCause.AUTH_ABANDONED),
    (_event(reason="never_seen_reason_xyz"), RootCause.UNKNOWN),
    (_event(reason=None), RootCause.UNKNOWN),
    (_event("L2", auth_attempted=True), RootCause.AUTH_ABANDONED),
    (_event("L2", auth_attempted=False), RootCause.PRICE_HESITATION),
    (_event("L3"), RootCause.INVOICE_FORGOTTEN),
]


@pytest.mark.parametrize(("event", "expected"), DIAGNOSIS_TABLE)
def test_diagnosis_table(event, expected):
    d = diagnose(event, ERROR_MAP)
    assert d.root_cause == expected
    assert d.source == "rule"
    if expected is RootCause.UNKNOWN:
        assert d.confidence == 0.0


def test_every_root_cause_enum_value_has_a_plan_path(tmp_path):
    """Closed taxonomy (FR-3.2): the policy engine can plan for EVERY enum value —
    values with no dedicated playbook fall back to UNKNOWN -> escalate."""
    policy = load_policy()
    with Session(get_engine(tmp_path / "t.db")) as s:
        for i, cause in enumerate(RootCause):
            case = open_case(
                s, entity_id=f"e_{i}", customer_id="c", category="L3", amount_inr=20000
            )
            case.root_cause = cause
            actions = plan(case, policy, NOW)
            assert actions, f"no plan path for {cause}"


def test_diagnose_case_sets_fields_and_transitions(tmp_path):
    with Session(get_engine(tmp_path / "t.db")) as s:
        case = open_case(
            s, entity_id="sub_1", customer_id="cust_0001", category="L1", amount_inr=499
        )
        d = diagnose_case(s, case, _event(reason="insufficient_funds"), ERROR_MAP)
        assert isinstance(d, Diagnosis)
        assert case.state == CaseState.DIAGNOSED
        assert case.root_cause == RootCause.INSUFFICIENT_FUNDS
        assert case.diagnosis_source == "rule"
