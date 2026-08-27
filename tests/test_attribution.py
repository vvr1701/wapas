"""Appendix C exit-gate tests: formulas reproduced exactly on hand-computed fixtures."""

from datetime import UTC, datetime, timedelta

from ledger.attribution import (
    Payment,
    at_risk,
    cost_per_recovered_inr,
    lift,
    natural_rate,
    promise_kept_rate,
    recovered_adj,
    recovered_raw,
    recovery_rate,
    stops_honored,
)

T0 = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def test_at_risk_sum():
    assert at_risk([499, 2000, 18000]) == 20499


def test_recovered_raw_credits_only_post_intervention_payments():
    payments = [
        Payment(case_id=1, amount_inr=499, observed_at=T0 + timedelta(days=2)),  # after
        Payment(case_id=2, amount_inr=5000, observed_at=T0 - timedelta(days=1)),  # before
        Payment(case_id=3, amount_inr=700, observed_at=T0 + timedelta(days=1)),  # untouched case
    ]
    first = {1: T0, 2: T0}
    assert recovered_raw(payments, first) == 499  # pre-intervention & untouched excluded


def test_recovered_raw_do_nothing_arm_counts_everything():
    payments = [
        Payment(case_id=1, amount_inr=499, observed_at=T0),
        Payment(case_id=2, amount_inr=700, observed_at=T0),
    ]
    assert recovered_raw(payments, {}, count_untouched=True) == 1199


def test_natural_rate_and_adjustment():
    # Hand-computed: arm A recovered 2,000 of 40,000 at risk -> natural 5%.
    nat = natural_rate(2000, 40000)
    assert nat == 0.05
    # Arm C recovered 9,000 raw over touched cases worth 30,000:
    # adjusted = 9000 - 0.05 * 30000 = 7500.
    assert recovered_adj(9000, nat, 30000) == 7500.0


def test_recovery_rate_lift_absolute_and_relative():
    rate_b = recovery_rate(4000, 40000)  # 0.10
    rate_c = recovery_rate(9000, 40000)  # 0.225
    result = lift(rate_c, rate_b)
    assert result["absolute"] == 0.125
    assert abs(result["relative"] - 1.25) < 1e-9  # 2.25x baseline == +125%


def test_cost_per_recovered_inr():
    # ₹120 LLM + ₹80 comms over ₹7,500 adjusted -> ₹0.0266.../recovered ₹
    assert cost_per_recovered_inr(120, 80, 7500.0) == 200 / 7500
    assert cost_per_recovered_inr(120, 80, 0) == float("inf")  # never divide into a claim


def test_promise_kept_rate_and_stops_honored():
    assert promise_kept_rate(3, 4) == 0.75
    assert promise_kept_rate(0, 0) == 0.0
    assert stops_honored(0, 7) == 1.0  # the number that must print 100%
    assert stops_honored(1, 4) == 0.75
    assert stops_honored(0, 0) == 1.0


def test_zero_at_risk_never_divides():
    assert natural_rate(0, 0) == 0.0
    assert recovery_rate(100, 0) == 0.0
