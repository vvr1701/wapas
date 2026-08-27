"""Eval arms A (do-nothing) and B (baseline) + the shared world conventions.

Single responsibility: simulate the two comparison arms against the SAME frozen
hidden world the agent faces. Natural payment is consulted exactly once per
case, on the customer's liquidity (salary) day — the identical draw key in all
three arms, so cross-arm differences come only from intervention decisions
(FR-1.4). Arm B is the industry-default dumb policy: one immediate retry plus
two templated email reminders, no windows, no opt-out registry, no caps logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ledger.attribution import Payment
from simulator import behavior_model as bm


@dataclass(frozen=True)
class WorldCase:
    """Arm-independent view of one revenue-at-risk case."""

    key: int  # stable index within the batch
    entity_id: str
    customer_id: str
    category: str
    amount_inr: int
    opened_at: datetime


@dataclass
class ArmResult:
    payments: list[Payment] = field(default_factory=list)
    first_intervention_at: dict[int, datetime] = field(default_factory=dict)
    touched_at_risk_inr: int = 0
    opt_outs: int = 0
    contacts_made: int = 0


def natural_payment_day(seed: int, case: WorldCase, start: datetime, days: int) -> datetime | None:
    """The one arm-independent natural-recovery draw per case: does this customer
    pay on their salary day, with nobody asking? Same (seed, entity) key in every
    arm — identical worlds by construction."""
    hidden = bm.sample_hidden_state(seed, case.customer_id)
    for d in range(days):
        day = start + timedelta(days=d)
        if day.day == hidden.liquidity_day:
            if bm.pays_naturally(seed, f"nat|{case.entity_id}", hidden, day.day):
                return day.replace(hour=9, minute=0)
            return None  # one consultation per case; no daily re-rolls
    return None


def run_arm_a(seed: int, cases: list[WorldCase], start: datetime, days: int) -> ArmResult:
    """Do-nothing: natural recovery only. Claiming credit for these payments is
    the classic dishonesty the adjustment corrects (FR-11.1)."""
    result = ArmResult()
    for case in cases:
        paid_at = natural_payment_day(seed, case, start, days)
        if paid_at is not None:
            result.payments.append(Payment(case.key, case.amount_inr, paid_at))
    return result


def run_arm_b(seed: int, cases: list[WorldCase], start: datetime, days: int) -> ArmResult:
    """Baseline dumb policy: 1 immediate retry (L1) + 2 templated emails for all,
    fired blindly. The behavior model punishes blind contact via annoyance and
    opt-out propensity — same physics the agent faces."""
    result = ArmResult()
    for case in cases:
        hidden = bm.sample_hidden_state(seed, case.customer_id)
        plan = []
        if case.category == "L1":
            plan.append(("retry", "bank", case.opened_at))
        plan.append(("nudge", "email", case.opened_at + timedelta(days=1)))
        plan.append(("nudge", "email", case.opened_at + timedelta(days=4)))
        result.first_intervention_at[case.key] = plan[0][2]
        result.touched_at_risk_inr += case.amount_inr
        paid_at: datetime | None = None
        contacts = 0
        opted_out = False
        for attempt_no, (kind, channel, when) in enumerate(plan, start=1):
            if paid_at is not None or opted_out:
                break
            reaction = bm.react(
                seed,
                case.customer_id,
                hidden,
                kind,
                channel,
                when.day,
                contacts,
                attempt_no,
            )
            if kind == "nudge":
                contacts += 1
                result.contacts_made += 1
            if reaction.opts_out:
                opted_out = True  # dumb baseline at least stops on explicit opt-out
                result.opt_outs += 1
            elif reaction.pays:
                paid_at = when
        natural = natural_payment_day(seed, case, start, days)
        if paid_at is None and natural is not None:
            paid_at = natural
        if paid_at is not None:
            result.payments.append(Payment(case.key, case.amount_inr, paid_at))
    return result
