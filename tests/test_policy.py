"""FR-4.1/4.2 exit-gate tests: every PlannedAction fully explainable, timing
resolution, value/voice guards, and plan-changes-via-YAML-only."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.cases import CaseState, open_case
from agent.policy import POLICIES_PATH, load_policy, plan, plan_case
from ledger.db import AuditRow, PlannedActionRow, get_engine

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
POLICY = load_policy()


@pytest.fixture
def session(tmp_path):
    with Session(get_engine(tmp_path / "t.db")) as s:
        yield s


def _case(
    session,
    *,
    category="L1",
    cause="INSUFFICIENT_FUNDS",
    amount=499,
    due_days_ago=None,
    entity="ent_1",
):
    due = (NOW - timedelta(days=due_days_ago)).isoformat() if due_days_ago else None
    case = open_case(
        session,
        entity_id=entity,
        customer_id="cust_0001",
        category=category,
        amount_inr=amount,
        due_date=due,
    )
    case.root_cause = cause
    case.state = CaseState.DIAGNOSED
    return case


# --- FR-4.2: fixture batch -> every action fully explainable -------------------

FIXTURE_BATCH = [
    dict(category="L1", cause="INSUFFICIENT_FUNDS", amount=499),
    dict(category="L1", cause="CARD_EXPIRED", amount=12000),
    dict(category="L1", cause="BANK_GATEWAY_DOWNTIME", amount=499),
    dict(category="L2", cause="AUTH_ABANDONED", amount=2500),
    dict(category="L2", cause="PRICE_HESITATION", amount=900),
    dict(category="L3", cause="INVOICE_FORGOTTEN", amount=18000, due_days_ago=10),
    dict(category="L3", cause="INVOICE_DISPUTED", amount=50000, due_days_ago=5),
    dict(category="L1", cause="UNKNOWN", amount=499),
]


def test_fixture_batch_every_action_explainable(session):
    for i, spec in enumerate(FIXTURE_BATCH):
        case = _case(session, entity=f"ent_{i}", **spec)
        for a in plan(case, POLICY, NOW):
            assert a.rule_id and "#" in a.rule_id
            assert a.rationale and str(case.root_cause) in a.rationale
            assert a.policy_version_hash == POLICY.version_hash


def test_plan_case_persists_and_audits(session):
    case = _case(session, category="L3", cause="INVOICE_FORGOTTEN", amount=18000, due_days_ago=10)
    actions = plan_case(session, case, POLICY, NOW)
    assert case.state == CaseState.PLANNED
    rows = session.scalars(select(PlannedActionRow)).all()
    assert len(rows) == len(actions) > 0
    assert all(r.rule_id and r.rationale and r.policy_version_hash for r in rows)
    audit_planned = session.scalars(
        select(AuditRow).where(AuditRow.event_type == "action_planned")
    ).all()
    assert len(audit_planned) == len(actions)  # FR-10.2 symmetry per action


# --- Timing resolution ---------------------------------------------------------


def test_liquidity_window_lands_on_salary_day_at_window_open(session):
    case = _case(session)
    first = plan(case, POLICY, NOW)[0]
    assert first.action_type == "silent_retry"
    # Aug 27 -> next salary day is Sep 1; 10:00 IST == 04:30 UTC
    assert first.scheduled_for == datetime(2026, 9, 1, 4, 30, tzinfo=UTC)


def test_due_anchored_timing(session):
    case = _case(session, category="L3", cause="INVOICE_FORGOTTEN", amount=18000, due_days_ago=10)
    actions = plan(case, POLICY, NOW)
    due = NOW - timedelta(days=10)
    assert actions[0].scheduled_for == due + timedelta(days=1)  # email@due+1d


# --- Guards --------------------------------------------------------------------


def test_value_threshold_filters_escalation(session):
    small = _case(session, amount=499, entity="e_small")
    big = _case(session, amount=18000, entity="e_big")
    assert "escalate" not in {a.action_type for a in plan(small, POLICY, NOW)}
    assert "escalate" in {a.action_type for a in plan(big, POLICY, NOW)}


def test_voice_only_when_eligible(session):
    eligible = _case(
        session,
        category="L3",
        cause="INVOICE_FORGOTTEN",
        amount=18000,
        due_days_ago=10,
        entity="e_v1",
    )
    too_small = _case(
        session,
        category="L3",
        cause="INVOICE_FORGOTTEN",
        amount=5000,
        due_days_ago=10,
        entity="e_v2",
    )
    too_fresh = _case(
        session,
        category="L3",
        cause="INVOICE_FORGOTTEN",
        amount=18000,
        due_days_ago=2,
        entity="e_v3",
    )
    assert "voice_call" in {a.action_type for a in plan(eligible, POLICY, NOW)}
    assert "voice_call" not in {a.action_type for a in plan(too_small, POLICY, NOW)}
    assert "voice_call" not in {a.action_type for a in plan(too_fresh, POLICY, NOW)}


def test_dispute_never_dunned(session):
    case = _case(session, category="L3", cause="INVOICE_DISPUTED", amount=50000, due_days_ago=5)
    actions = plan(case, POLICY, NOW)
    assert [a.action_type for a in actions] == ["escalate"]


# --- FR-4.1 AC: plan changes require only YAML edits ---------------------------


def test_yaml_edit_changes_plan_without_code_change(session, tmp_path):
    case = _case(session, amount=18000)
    before = [(a.action_type, a.scheduled_for) for a in plan(case, POLICY, NOW)]
    edited = tmp_path / "policies.yaml"
    edited.write_text(Path(POLICIES_PATH).read_text().replace('at: "+72h"', 'at: "+12h"'))
    reloaded = load_policy(edited)
    after = [(a.action_type, a.scheduled_for) for a in plan(case, reloaded, NOW)]
    assert before != after
    assert reloaded.version_hash != POLICY.version_hash
    assert [a for a, _ in before] == [a for a, _ in after]  # same actions, new timing
