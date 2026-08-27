"""FR-6.2 exit-gate: the real money loop, one pytest.

Creates a REAL Razorpay test-mode payment link for a case, then feeds the
payment observation (shaped exactly like Razorpay's payment entity, notes
propagated from the link) through ingestion: case -> RECOVERED, recovered ₹
increments. Skips (never fakes green) when test keys are absent — CI has no
secrets; the gate run happens locally. The link is cancelled afterwards to
respect the 30-active-link test-mode cap.
"""

import os
from datetime import UTC, datetime

import pytest
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from agent.cases import CaseState, open_case, transition
from agent.guardrails import execute_action
from agent.policy import load_policy
from channels.links import create_case_payment_link, observe_payment, recovered_inr
from ledger.db import PlannedActionRow, get_engine

load_dotenv()
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
HAS_KEYS = bool(os.getenv("RAZORPAY_KEY_ID", "").startswith("rzp_test_"))


@pytest.mark.skipif(not HAS_KEYS, reason="Razorpay test keys not configured")
def test_link_paid_case_recovered(tmp_path):
    import razorpay

    client = razorpay.Client(
        auth=(os.environ["RAZORPAY_KEY_ID"], os.environ["RAZORPAY_KEY_SECRET"])
    )
    policy = load_policy()
    with Session(get_engine(tmp_path / "t.db")) as s:
        case = open_case(
            s, entity_id="order_e2e_1", customer_id="cust_0001", category="L2", amount_inr=1200
        )
        case.root_cause = "AUTH_ABANDONED"
        for st in (CaseState.DIAGNOSED, CaseState.PLANNED):
            transition(s, case, st)
        assert recovered_inr(s) == 0

        # real test-mode payable link (invoice-backed), case identity in notes
        import json
        from pathlib import Path

        rzp_cust = next(
            iter(json.loads(Path("data/seed_registry.json").read_text())["customers"].values())
        )
        link = create_case_payment_link(
            client, case, description="Kirana+ order (e2e test)", rzp_customer_id=rzp_cust
        )
        assert link["id"].startswith("inv_") and link["short_url"]
        try:
            action = PlannedActionRow(
                case_id=case.id,
                action_type="link_nudge",
                channel="whatsapp",
                scheduled_for=NOW.isoformat(),
                rule_id="L2.AUTH_ABANDONED#0",
                rationale="e2e",
                policy_version_hash=policy.version_hash,
            )
            s.add(action)
            s.flush()
            executed = execute_action(
                s,
                case,
                action,
                policy,
                NOW,
                perform=lambda: {"result": "SUCCESS", "external_ref": link["id"]},
            )
            assert executed is not None and executed.external_ref == link["id"]
            for st in (CaseState.GATED, CaseState.EXECUTING, CaseState.AWAITING_OUTCOME):
                transition(s, case, st)

            # payment completion observed (notes propagate link -> payment)
            payment = {
                "id": "pay_e2e_simulated1",
                "amount": 120000,
                "method": "upi",
                "notes": {"case_id": str(case.id), "entity_id": case.entity_id},
            }
            observed = observe_payment(s, payment, NOW)
            assert observed is not None and observed.matched_case_id == case.id
            assert case.state == CaseState.RECOVERED
            assert recovered_inr(s) == 1200  # recovered ₹ incremented
            assert observe_payment(s, payment, NOW) is None  # idempotent re-observe
        finally:
            client.invoice.cancel(link["id"])  # no strays in the test account
