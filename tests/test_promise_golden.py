"""FR-7.3 exit-gate: promise extraction ≥90% exact-match on the 20-transcript
hand-labeled golden set (live Claude, skips without credentials — never fakes
green), plus CI-safe rail tests."""

import json
import os
from datetime import date
from pathlib import Path

import pytest

from channels.voice.promise_parser import (
    ExtractedPromise,
    extract_promise,
    validate_rails,
)

GOLDEN = json.loads((Path(__file__).parent / "golden" / "promises.json").read_text())
CALL_DATE = date.fromisoformat(GOLDEN["call_date"])
HAS_LLM = bool(os.getenv("ANTHROPIC_API_KEY"))


# --- Deterministic rails (CI-safe) ---------------------------------------------


def _p(**kw) -> ExtractedPromise:
    base = dict(promise=True, amount_inr=18000, date="2026-09-02", conditions=None, confidence=0.9)
    return ExtractedPromise(**base | kw)


def test_rails_accept_sane_promise():
    d = validate_rails(_p(), amount_due_inr=18000, call_date=CALL_DATE)
    assert d.auto_record


@pytest.mark.parametrize(
    ("promise", "reason"),
    [
        (_p(confidence=0.5), "low_confidence"),
        (_p(amount_inr=0), "absurd_amount"),
        (_p(amount_inr=40000), "absurd_amount"),  # > 2x due
        (_p(date="2026-10-15"), "absurd_date"),  # > 30 days out
        (_p(date="2026-08-20"), "absurd_date"),  # in the past
        (_p(date=None), "no_date"),
    ],
)
def test_rails_route_to_human_review(promise, reason):
    d = validate_rails(promise, amount_due_inr=18000, call_date=CALL_DATE)
    assert not d.auto_record and d.review_reason == reason


def test_no_promise_is_not_reviewed():
    d = validate_rails(_p(promise=False), amount_due_inr=18000, call_date=CALL_DATE)
    assert not d.auto_record and d.review_reason is None


# --- Live golden set (the ≥90% gate; local run with ANTHROPIC_API_KEY) ---------


@pytest.mark.skipif(not HAS_LLM, reason="ANTHROPIC_API_KEY not configured")
def test_golden_set_exact_match_rate():
    results = []
    for case in GOLDEN["cases"]:
        decision = extract_promise(
            None,
            case["transcript"],
            amount_due_inr=case["amount_due_inr"],
            call_date=CALL_DATE,
        )
        got = decision.extracted
        exp = case["expected"]
        match = (
            got is not None
            and got.promise == exp["promise"]
            and (not exp["promise"] or got.amount_inr == exp["amount_inr"])
            and (got.date if exp["promise"] else None) == exp["date"]
        )
        results.append((case["id"], match, got and got.model_dump()))
    misses = [r for r in results if not r[1]]
    rate = 1 - len(misses) / len(results)
    assert rate >= 0.9, f"exact-match {rate:.0%}; misses: {misses}"
