"""Phase 4 exit-gate tests — WRITTEN FIRST (FR-5.1, FR-5.2, FR-5.3).

Every check in the gate has a blocking test; the gate is deterministic code
only — nothing in here mocks or touches an LLM, because the gate must never
involve one.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.cases import CaseState, open_case, transition
from agent.guardrails import (
    check,
    detect_stop_intent,
    execute_action,
    opt_out,
)
from agent.policy import load_policy
from ledger.db import (
    AuditRow,
    CustomerRow,
    ExecutedActionRow,
    PlannedActionRow,
    get_engine,
)

POLICY = load_policy()
# 2026-08-27 12:00 UTC == 17:30 IST — inside the 10:00–19:00 contact window.
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
# 2026-08-27 15:00 UTC == 20:30 IST — outside the window.
LATE = datetime(2026, 8, 27, 15, 0, tzinfo=UTC)


@pytest.fixture
def session(tmp_path):
    with Session(get_engine(tmp_path / "t.db")) as s:
        yield s


def _case(session, *, entity="inv_1", customer="cust_0001", amount=18000, category="L3"):
    case = open_case(
        session, entity_id=entity, customer_id=customer, category=category, amount_inr=amount
    )
    case.root_cause = "INVOICE_FORGOTTEN"
    for st in (CaseState.DIAGNOSED, CaseState.PLANNED):
        transition(session, case, st)
    return case


def _action(session, case, action_type="wa_nudge", channel="whatsapp", incentive=0, when=NOW):
    row = PlannedActionRow(
        case_id=case.id,
        action_type=action_type,
        channel=channel,
        scheduled_for=when.isoformat(),
        rule_id="TEST#0",
        rationale="test action",
        policy_version_hash=POLICY.version_hash,
        incentive_inr=incentive,
    )
    session.add(row)
    session.flush()
    return row


def _executed(session, case, action_type, channel, ts, incentive=0):
    """Fabricate a prior execution (for caps/cooldown tests)."""
    n = len(session.scalars(select(ExecutedActionRow)).all())
    row = ExecutedActionRow(
        planned_id=0,
        case_id=case.id,
        action_type=action_type,
        channel=channel,
        idempotency_key=f"fixture_{n}",
        executed_ts=ts.isoformat(),
        result="SUCCESS",
        incentive_inr=incentive,
    )
    session.add(row)
    session.flush()
    return row


# --- FR-5.1 (1): terminal case ------------------------------------------------


def test_terminal_case_blocked(session):
    case = _case(session)
    action = _action(session, case)
    transition(session, case, CaseState.STOPPED)
    d = check(session, case, action, POLICY, NOW)
    assert not d.allowed and d.reason == "case_terminal"


# --- FR-5.1 (2): attempt caps -------------------------------------------------


def test_retry_cap_blocks_fourth_retry(session):
    case = _case(session)
    for i in range(POLICY.caps["retries"]):
        _executed(session, case, "silent_retry", "bank", NOW - timedelta(days=3, hours=i))
    d = check(session, case, _action(session, case, "silent_retry", "bank"), POLICY, NOW)
    assert not d.allowed and d.reason == "cap_retries"


def test_nudge_cap_blocks_fifth_nudge(session):
    case = _case(session)
    for i in range(POLICY.caps["nudges"]):
        _executed(session, case, "email_nudge", "email", NOW - timedelta(days=6 - i))
    d = check(session, case, _action(session, case, "wa_nudge", "whatsapp"), POLICY, NOW)
    assert not d.allowed and d.reason == "cap_nudges"


def test_voice_cap_blocks_second_call(session):
    case = _case(session)
    _executed(session, case, "voice_call", "voice", NOW - timedelta(days=5))
    d = check(session, case, _action(session, case, "voice_call", "voice"), POLICY, NOW)
    assert not d.allowed and d.reason == "cap_voice_calls"


# --- FR-5.1 (3): cooldowns ----------------------------------------------------


def test_nudge_cooldown_blocks_then_allows(session):
    case = _case(session)
    _executed(session, case, "email_nudge", "email", NOW - timedelta(hours=5))
    d = check(session, case, _action(session, case, "wa_nudge", "whatsapp"), POLICY, NOW)
    assert not d.allowed and d.reason == "cooldown_nudge"
    case2 = _case(session, entity="inv_2", customer="cust_0002")
    _executed(session, case2, "email_nudge", "email", NOW - timedelta(hours=21))
    d2 = check(session, case2, _action(session, case2, "wa_nudge", "whatsapp"), POLICY, NOW)
    assert d2.allowed


def test_voice_cooldown_after_last_contact(session):
    case = _case(session)
    _executed(session, case, "wa_nudge", "whatsapp", NOW - timedelta(hours=24))
    d = check(session, case, _action(session, case, "voice_call", "voice"), POLICY, NOW)
    assert not d.allowed and d.reason == "cooldown_voice"
    case2 = _case(session, entity="inv_2", customer="cust_0002")
    _executed(session, case2, "wa_nudge", "whatsapp", NOW - timedelta(hours=49))
    d2 = check(session, case2, _action(session, case2, "voice_call", "voice"), POLICY, NOW)
    assert d2.allowed


# --- FR-5.1 (4): contact window + FR-5.3 auto-replan ---------------------------


def test_outside_window_blocked_with_replan(session):
    case = _case(session)
    action = _action(session, case, "wa_nudge", "whatsapp")
    d = check(session, case, action, POLICY, LATE)  # 20:30 IST
    assert not d.allowed and d.reason == "outside_contact_window"
    # next window open: Aug 28 10:00 IST == 04:30 UTC
    assert d.replan_for == datetime(2026, 8, 28, 4, 30, tzinfo=UTC)


def test_silent_retry_exempt_from_window(session):
    case = _case(session)
    d = check(session, case, _action(session, case, "silent_retry", "bank"), POLICY, LATE)
    assert d.allowed


def test_blocked_action_replanned_not_silently_dead(session):
    """FR-5.3: execute at 20:30 IST -> no execution, action rescheduled, both audited."""
    case = _case(session)
    action = _action(session, case, "wa_nudge", "whatsapp", when=LATE)
    result = execute_action(session, case, action, POLICY, LATE)
    assert result is None
    assert action.status == "PENDING"
    assert action.scheduled_for == datetime(2026, 8, 28, 4, 30, tzinfo=UTC).isoformat()
    events = [r.event_type for r in session.scalars(select(AuditRow))]
    assert "action_blocked" in events and "action_replanned" in events
    assert session.scalars(select(ExecutedActionRow)).all() == []


# --- FR-5.1 (5): opt-out registry ----------------------------------------------


def test_opted_out_customer_blocked(session):
    _case(session)
    opt_out(session, "cust_0001", source="test")
    fresh_case = _case(session, entity="inv_9", customer="cust_0001")
    d = check(session, fresh_case, _action(session, fresh_case), POLICY, NOW)
    assert not d.allowed and d.reason == "customer_opted_out"


# --- FR-5.1 (6): voice value threshold -----------------------------------------


def test_voice_below_value_threshold_blocked(session):
    case = _case(session, amount=4999)
    d = check(session, case, _action(session, case, "voice_call", "voice"), POLICY, NOW)
    assert not d.allowed and d.reason == "voice_value_threshold"


# --- FR-5.1 (7): incentive bounding --------------------------------------------


def test_incentive_budget_exhaustion_blocks(session):
    case = _case(session, category="L2", amount=4000)
    case.root_cause = "PRICE_HESITATION"
    budget = POLICY.incentives["batch_budget_inr"]
    spent, i = 0, 0
    while spent + 100 <= budget:  # burn the batch budget with prior cases
        other = _case(session, entity=f"o_{i}", customer=f"cust_1{i:03d}", category="L2")
        _executed(session, other, "link_nudge", "email", NOW - timedelta(days=2), incentive=100)
        spent += 100
        i += 1
    d = check(
        session, case, _action(session, case, "link_nudge", "email", incentive=100), POLICY, NOW
    )
    assert not d.allowed and d.reason == "incentive_budget_exhausted"


def test_incentive_per_case_rules(session):
    case = _case(session, category="L2", amount=4000)
    case.root_cause = "PRICE_HESITATION"
    over_cap = _action(session, case, "link_nudge", "email", incentive=150)  # > ₹100 cap
    d = check(session, case, over_cap, POLICY, NOW)
    assert not d.allowed and d.reason == "incentive_per_case_cap"
    wrong_cause = _case(session, entity="inv_w", customer="cust_0009")  # INVOICE_FORGOTTEN
    d2 = check(
        session,
        wrong_cause,
        _action(session, wrong_cause, "link_nudge", "email", incentive=50),
        POLICY,
        NOW,
    )
    assert not d2.allowed and d2.reason == "incentive_root_cause_not_allowed"
    ok = _action(session, case, "link_nudge", "email", incentive=50)
    assert check(session, case, ok, POLICY, NOW).allowed


# --- FR-5.1 (8): idempotency double-fire ---------------------------------------


def test_double_fire_executes_once(session):
    case = _case(session)
    action = _action(session, case, "wa_nudge", "whatsapp")
    first = execute_action(session, case, action, POLICY, NOW)
    assert first is not None and first.result == "SUCCESS"
    second = execute_action(session, case, action, POLICY, NOW)  # crash-retry replay
    assert second is not None and second.id == first.id
    assert len(session.scalars(select(ExecutedActionRow)).all()) == 1


def test_idempotency_key_deterministic(session):
    case = _case(session)
    a1 = _action(session, case, "wa_nudge", "whatsapp")
    executed = execute_action(session, case, a1, POLICY, NOW)
    from agent.guardrails import idempotency_key

    assert executed.idempotency_key == idempotency_key(case.id, "wa_nudge", 1)


# --- FR-5.2: opt-out semantics -------------------------------------------------


def test_post_opt_out_zero_actions_and_queued_cancelled(session):
    """The compliance crown jewel: queued actions die instantly and nothing
    executes afterwards."""
    case = _case(session)
    queued = [
        _action(session, case, t, c)
        for t, c in [("wa_nudge", "whatsapp"), ("email_nudge", "email"), ("voice_call", "voice")]
    ]
    opt_out(session, "cust_0001", source="customer_reply")
    assert case.state == CaseState.STOPPED
    for q in queued:
        session.refresh(q)
        assert q.status == "CANCELLED"
        assert execute_action(session, case, q, POLICY, NOW) is None
    assert session.scalars(select(ExecutedActionRow)).all() == []
    reg = session.scalar(select(CustomerRow).where(CustomerRow.customer_id == "cust_0001"))
    assert reg.opted_out and reg.opt_out_source == "customer_reply" and reg.opt_out_ts
    events = [r.event_type for r in session.scalars(select(AuditRow))]
    assert "opt_out" in events


def test_opt_out_is_permanent_and_idempotent(session):
    _case(session)
    opt_out(session, "cust_0001", source="a")
    opt_out(session, "cust_0001", source="b")  # second call: no crash, stays opted out
    reg = session.scalar(select(CustomerRow).where(CustomerRow.customer_id == "cust_0001"))
    assert reg.opted_out and reg.opt_out_source == "a"  # first trigger wins, permanent


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Please STOP calling me", True),
        ("stop", True),
        ("call mat karo mujhe", True),
        ("remove my number please", True),
        ("unsubscribe", True),
        ("mat bhejo message", True),
        ("dont call me again", True),
        ("my shop is open, stopped by yesterday", False),  # no stop-intent
        ("salary aane do, will pay", False),
        ("send link again", False),
    ],
)
def test_stop_intent_rules(text, expected):
    assert detect_stop_intent(text) is expected


# --- gate decisions are audited (FR-5.1 "all logged") --------------------------


def test_gate_decision_audited_with_reason(session):
    case = _case(session, amount=4999)
    action = _action(session, case, "voice_call", "voice")
    execute_action(session, case, action, POLICY, NOW)
    blocked = [r for r in session.scalars(select(AuditRow)) if r.event_type == "action_blocked"]
    assert blocked and "voice_value_threshold" in blocked[-1].payload_json
