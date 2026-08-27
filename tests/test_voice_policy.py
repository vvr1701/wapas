"""FR-7.2 exit-gate tests: every conversation-policy behavior, text-mode
harness, CI-safe (no audio, no live LLM — behaviors are code-enforced rails)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.cases import CaseState, open_case, transition
from channels.voice.call_agent import apply_turn_effects, new_call
from channels.voice.policy import (
    ABUSE_SCRIPT,
    DISCLOSURE,
    DISPUTE_SCRIPT,
    FALLBACK_LINE,
    STOP_SCRIPT,
    promise_within_bounds,
    respond,
)
from ledger.db import CustomerRow, EscalationRow, get_engine

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


@pytest.fixture
def session(tmp_path):
    with Session(get_engine(tmp_path / "t.db")) as s:
        yield s


def _case(session, entity="inv_1"):
    case = open_case(
        session, entity_id=entity, customer_id="cust_0001", category="L3", amount_inr=18000
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
    return case


def _call(case):
    return new_call(case, "Vikram Singh", "2026-08-27")


def polite_llm(call, text):
    return "Theek hai ji, aap kab tak payment kar payenge?"


# --- FR-7.2 (1): disclosure ALWAYS first, enforced by code ---------------------


def test_disclosure_first_even_when_llm_omits_it(session):
    call = _call(_case(session))
    turn = respond(call, "Hello, kaun bol raha hai?", polite_llm)
    assert turn.text.startswith(DISCLOSURE)
    turn2 = respond(call, "Haan boliye", polite_llm)
    assert DISCLOSURE not in turn2.text  # said once, not parroted every turn


def test_disclosure_first_even_on_immediate_stop(session):
    call = _call(_case(session))
    turn = respond(call, "stop calling me", None)
    assert turn.text.startswith(DISCLOSURE) and STOP_SCRIPT in turn.text


# --- FR-7.2 (3): negotiation bounds are code, not vibes ------------------------


@pytest.mark.parametrize(
    ("amount", "days", "due", "ok"),
    [
        (18000, 5, 18000, True),  # full amount within window
        (9000, 14, 18000, True),  # exactly 50%, exactly 14 days
        (8999, 5, 18000, False),  # below 50%
        (18000, 15, 18000, False),  # beyond 14 days
        (18000, 0, 18000, False),  # today/past is not a promise
    ],
)
def test_promise_bounds(amount, days, due, ok):
    assert promise_within_bounds(amount, days, due) is ok


# --- FR-7.2 (5): stop phrase -> apologize, end, opt-out fires ------------------


def test_stop_phrase_ends_call_and_opts_out(session):
    case = _case(session)
    call = _call(case)
    respond(call, "Namaste", polite_llm)
    turn = respond(call, "please call mat karo mujhe", polite_llm)
    assert STOP_SCRIPT in turn.text and turn.end_call and call.ended
    apply_turn_effects(session, case, turn)
    reg = session.scalar(select(CustomerRow).where(CustomerRow.customer_id == "cust_0001"))
    assert reg.opted_out and reg.opt_out_source == "in_call_stop_phrase"
    assert case.state == CaseState.STOPPED
    assert respond(call, "hello?", polite_llm).end_call  # ended calls stay ended


# --- FR-7.2 (6): dispute -> never argue, verify, escalate ----------------------


def test_dispute_never_argued_and_escalated(session):
    case = _case(session)
    call = _call(case)
    turn = respond(call, "maine already pay kar diya hai bhai", polite_llm)
    assert DISPUTE_SCRIPT in turn.text and turn.end_call
    apply_turn_effects(session, case, turn)
    esc = session.scalar(select(EscalationRow))
    assert esc is not None and esc.reason == "DISPUTE"
    assert case.state == CaseState.ESCALATED


# --- FR-7.2 (7): abuse -> de-escalate, end politely, human --------------------


def test_abuse_deescalates_and_escalates_to_human(session):
    case = _case(session)
    call = _call(case)
    turn = respond(call, "saala chutiya company, phone rakh", polite_llm)
    assert ABUSE_SCRIPT in turn.text and turn.end_call
    apply_turn_effects(session, case, turn)
    esc = session.scalar(select(EscalationRow))
    assert esc is not None and esc.reason == "ABUSE_DISTRESS"


# --- §6.2: malformed/unavailable LLM never crashes or leaks -------------------


def test_llm_exception_falls_back_deterministically(session):
    def broken(call, text):
        raise RuntimeError("api down")

    call = _call(_case(session))
    turn = respond(call, "haan boliye", broken)
    assert FALLBACK_LINE in turn.text and not turn.llm_used


def test_llm_tone_violation_suppressed(session):
    def rogue(call, text):
        return "Pay now or we will take legal action against you!"

    call = _call(_case(session))
    turn = respond(call, "kya chahiye", rogue)
    assert "legal action" not in turn.text.lower()
    assert FALLBACK_LINE in turn.text and not turn.llm_used
