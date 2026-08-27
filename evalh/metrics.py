"""Metrics assembly (FR-11.2, Appendix C).

Single responsibility: turn the three ArmResults into metrics.json, using ONLY
the formulas in ledger/attribution.py. Both raw and A-adjusted numbers are
reported; stops_honored must print 100% or the run is telling on itself.
"""

from __future__ import annotations

from evalh.arms import ArmResult, WorldCase
from ledger import attribution as at

USD_INR = 88.0  # conversion estimate for the cost line, stated as an estimate


def assemble_metrics(
    cases: list[WorldCase], arm_a: ArmResult, arm_b: ArmResult, arm_c: ArmResult, extras: dict
) -> dict:
    at_risk_total = at.at_risk([c.amount_inr for c in cases])
    raw_a = at.recovered_raw(arm_a.payments, {}, count_untouched=True)
    raw_b = at.recovered_raw(arm_b.payments, arm_b.first_intervention_at)
    raw_c = at.recovered_raw(arm_c.payments, arm_c.first_intervention_at)
    nat = at.natural_rate(raw_a, at_risk_total)
    adj_b = at.recovered_adj(raw_b, nat, arm_b.touched_at_risk_inr)
    adj_c = at.recovered_adj(raw_c, nat, arm_c.touched_at_risk_inr)
    rate_a = at.recovery_rate(raw_a, at_risk_total)
    rate_b = at.recovery_rate(raw_b, at_risk_total)
    rate_c = at.recovery_rate(raw_c, at_risk_total)
    lift = at.lift(rate_c, rate_b)
    llm_cost_inr = extras["llm_cost_usd"] * USD_INR
    cost_per_rupee = at.cost_per_recovered_inr(llm_cost_inr, extras["comms_cost_est_inr"], adj_c)
    promises = extras["promises"]
    return {
        "batch": {"cases": len(cases), "at_risk_inr": at_risk_total},
        "arms": {
            "A_do_nothing": {
                "recovered_raw_inr": raw_a,
                "recovery_rate": round(rate_a, 4),
                "payments": len(arm_a.payments),
                "contacts_made": 0,
            },
            "B_baseline": {
                "recovered_raw_inr": raw_b,
                "recovered_adj_inr": round(adj_b, 2),
                "recovery_rate": round(rate_b, 4),
                "payments": len(arm_b.payments),
                "contacts_made": arm_b.contacts_made,
                "opt_outs": arm_b.opt_outs,
                "touched_at_risk_inr": arm_b.touched_at_risk_inr,
            },
            "C_wapas": {
                "recovered_raw_inr": raw_c,
                "recovered_adj_inr": round(adj_c, 2),
                "recovery_rate": round(rate_c, 4),
                "payments": len(arm_c.payments),
                "contacts_made": arm_c.contacts_made,
                "opt_outs": arm_c.opt_outs,
                "touched_at_risk_inr": arm_c.touched_at_risk_inr,
                "executed_actions": extras["executed_actions"],
            },
        },
        "attribution": {
            "natural_rate": round(nat, 4),
            "rule": "credit only payments arriving after the arm's first intervention on the "
            "case; adjusted = raw − natural_rate × at_risk(touched cases)",
        },
        "promises": promises,
        "compliance": {
            "optouts": extras["optouts"],
            "actions_after_optout": extras["actions_after_optout"],
            "stops_honored": at.stops_honored(extras["actions_after_optout"], extras["optouts"]),
        },
        "cost": {
            "llm_cost_usd": extras["llm_cost_usd"],
            "comms_cost_est_inr": extras["comms_cost_est_inr"],
            "usd_inr_est": USD_INR,
            "cost_per_recovered_inr": round(cost_per_rupee, 4)
            if cost_per_rupee != float("inf")
            else None,
        },
        "headline": {
            "at_risk_inr": at_risk_total,
            "recovered_raw_inr": {"A": raw_a, "B": raw_b, "C": raw_c},
            "recovered_adj_inr": {"B": round(adj_b, 2), "C": round(adj_c, 2)},
            "recovery_rate": {"A": round(rate_a, 4), "B": round(rate_b, 4), "C": round(rate_c, 4)},
            "lift": {
                "absolute": round(lift["absolute"], 4),
                "relative": round(lift["relative"], 4),
            },
            "stops_honored": at.stops_honored(extras["actions_after_optout"], extras["optouts"]),
            "promises_kept_rate": promises["kept_rate"],
            "exceptions_count": len(extras["exceptions"]),
        },
    }
