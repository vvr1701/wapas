"""Attribution & metric formulas — Appendix C, implemented exactly (FR-11.2).

Single responsibility: pure functions from observed facts to the metrics the
README prints. No I/O, no state: the eval harness (Phase 8) feeds these from
the DB and every number on screen traces back to one of them. The core honesty
rule: an arm gets credit only for payments arriving AFTER its first
intervention on that case, and natural recovery (arm A) is subtracted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Payment:
    case_id: int
    amount_inr: int
    observed_at: datetime


def at_risk(case_amounts: list[int]) -> int:
    """at_risk = Σ amount_due over opened cases."""
    return sum(case_amounts)


def recovered_raw(
    payments: list[Payment],
    first_intervention_at: dict[int, datetime],
    *,
    count_untouched: bool = False,
) -> int:
    """recovered_raw(arm) = Σ payments matched to cases, arriving after the
    arm's first intervention on that case.

    count_untouched=True is the do-nothing arm (no interventions exist, every
    matched payment is natural recovery). For intervening arms, payments on
    cases the arm never touched — or before it acted — are natural, not credit.
    """
    total = 0
    for p in payments:
        if count_untouched:
            total += p.amount_inr
            continue
        first = first_intervention_at.get(p.case_id)
        if first is not None and p.observed_at > first:
            total += p.amount_inr
    return total


def natural_rate(recovered_raw_a: int, at_risk_total: int) -> float:
    """natural_rate = recovered_raw(A) / at_risk."""
    return recovered_raw_a / at_risk_total if at_risk_total else 0.0


def recovered_adj(recovered_raw_arm: int, nat_rate: float, at_risk_touched: int) -> float:
    """recovered_adj(arm) = recovered_raw(arm) − natural_rate × at_risk(arm-touched cases)."""
    return recovered_raw_arm - nat_rate * at_risk_touched


def recovery_rate(recovered_raw_arm: int, at_risk_total: int) -> float:
    return recovered_raw_arm / at_risk_total if at_risk_total else 0.0


def lift(rate_c: float, rate_b: float) -> dict[str, float]:
    """lift = rate(C) − rate(B); reported absolute and relative."""
    return {
        "absolute": rate_c - rate_b,
        "relative": (rate_c - rate_b) / rate_b if rate_b else float("inf"),
    }


def cost_per_recovered_inr(llm_cost_inr: float, comms_cost_inr: float, adj: float) -> float:
    """cost_per_recovered_₹ = (llm_cost + comms_cost_est) / recovered_adj(C)."""
    return (llm_cost_inr + comms_cost_inr) / adj if adj > 0 else float("inf")


def promise_kept_rate(kept: int, made: int) -> float:
    return kept / made if made else 0.0


def stops_honored(actions_after_optout: int, optouts: int) -> float:
    """Must print 100%: 1 − (actions_after_optout / optouts)."""
    return 1.0 - (actions_after_optout / optouts) if optouts else 1.0
