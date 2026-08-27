"""Payment links + payment observation (FR-6.2) — the real money loop.

Single responsibility: create REAL Razorpay test-mode payable links carrying
case identity in notes, and match observed payments back to cases (notes
propagate to the payment), closing them as RECOVERED.

Implementation note (verified live, Aug 27 2026): test mode enforces a LIFETIME
cap of 30 on the payment_link entity ("test mode limit of 30 reached"), and
cancelling links does not refund it. Invoices carry the same payable
short_url (hosted Razorpay payment page, test cards/UPI work) without that cap,
so per-nudge links are invoice-backed. Disclosed in SIMULATION.md.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.cases import TERMINAL, CaseState, transition
from ledger import audit
from ledger.db import PaymentObservedRow, RecoveryCaseRow


def create_case_payment_link(
    client, case: RecoveryCaseRow, *, description: str, rzp_customer_id: str
) -> dict:
    """One real test-mode payable link per nudge context (invoice-backed, see
    module docstring). notes.case_id is the match key."""
    inv = client.invoice.create(
        {
            "type": "invoice",
            "description": description,
            "customer_id": rzp_customer_id,
            "currency": "INR",
            "line_items": [
                {"name": description, "amount": case.amount_due_inr * 100, "quantity": 1}
            ],
            "notes": {"case_id": str(case.id), "entity_id": case.entity_id},
        }
    )
    return {"id": inv["id"], "short_url": inv.get("short_url", "")}


def observe_payment(session: Session, payment: dict, now: datetime) -> PaymentObservedRow | None:
    """Ingest one Razorpay payment entity. Matched via notes.case_id; a paid case
    in AWAITING_OUTCOME (or PROMISE_PENDING) transitions to RECOVERED.
    Idempotent on rzp_payment_id."""
    if session.scalar(
        select(PaymentObservedRow).where(PaymentObservedRow.rzp_payment_id == payment["id"])
    ):
        return None
    case_id = (payment.get("notes") or {}).get("case_id")
    case = session.get(RecoveryCaseRow, int(case_id)) if case_id else None
    row = PaymentObservedRow(
        rzp_payment_id=payment["id"],
        amount_inr=payment["amount"] // 100,
        method=payment.get("method"),
        matched_case_id=case.id if case else None,
        observed_ts=now.isoformat(),
    )
    session.add(row)
    audit.append(
        session,
        actor="customer",
        event_type="payment_observed",
        case_id=case.id if case else None,
        payload={"rzp_payment_id": payment["id"], "amount_inr": row.amount_inr},
    )
    if case is not None and CaseState(case.state) not in TERMINAL:
        transition(
            session,
            case,
            CaseState.RECOVERED,
            actor="customer",
            payload={"rzp_payment_id": payment["id"], "amount_inr": row.amount_inr},
        )
    session.flush()
    return row


def recovered_inr(session: Session) -> int:
    """Total ₹ recovered = matched payments on recovered cases. Measured, never claimed."""
    rows = session.scalars(
        select(PaymentObservedRow).where(PaymentObservedRow.matched_case_id.is_not(None))
    )
    return sum(r.amount_inr for r in rows)
