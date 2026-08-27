"""Promise-to-pay ledger (FR-8.1).

Single responsibility: persist promises captured on calls and verify them
against observed payments — KEPT (paid in full by due date + 1 day grace),
PARTIAL (something arrived, window closed), BROKEN (nothing arrived, window
closed). Kept promises recover the case with voice_promise attribution; broken
and partial ones re-enter planning. Every change is audit-paired.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.cases import TERMINAL, CaseState, transition
from ledger import audit
from ledger.db import PaymentObservedRow, PromiseRow, RecoveryCaseRow

GRACE = timedelta(days=1)


def record_promise(
    session: Session,
    case: RecoveryCaseRow,
    *,
    amount_inr: int,
    due_date: datetime,
    now: datetime,
    conditions: str | None = None,
    confidence: float,
    transcript_ref: str | None = None,
) -> PromiseRow:
    """Persist a captured promise; case enters PROMISE_PENDING."""
    row = PromiseRow(
        case_id=case.id,
        amount_inr=amount_inr,
        due_date=due_date.isoformat(),
        conditions=conditions,
        confidence=confidence,
        transcript_ref=transcript_ref,
        created_ts=now.isoformat(),
    )
    session.add(row)
    session.flush()
    audit.append(
        session,
        actor="customer",
        event_type="promise_recorded",
        case_id=case.id,
        payload={
            "promise_id": row.id,
            "amount_inr": amount_inr,
            "due_date": row.due_date,
            "confidence": confidence,
            "transcript_ref": transcript_ref,
        },
    )
    if CaseState(case.state) == CaseState.AWAITING_OUTCOME:
        transition(
            session,
            case,
            CaseState.PROMISE_PENDING,
            actor="agent",
            payload={"promise_id": row.id},
        )
    return row


def _payments_in_window(
    session: Session, promise: PromiseRow, window_end: datetime
) -> list[PaymentObservedRow]:
    rows = session.scalars(
        select(PaymentObservedRow).where(PaymentObservedRow.matched_case_id == promise.case_id)
    )
    return [r for r in rows if promise.created_ts <= r.observed_ts <= window_end.isoformat()]


def verify_promises(session: Session, now: datetime) -> list[PromiseRow]:
    """Walk PENDING promises against observed payments. Returns promises whose
    status changed this pass."""
    changed: list[PromiseRow] = []
    pending = session.scalars(select(PromiseRow).where(PromiseRow.status == "PENDING"))
    for p in pending:
        case = session.get(RecoveryCaseRow, p.case_id)
        window_end = datetime.fromisoformat(p.due_date) + GRACE
        paid_rows = _payments_in_window(session, p, window_end)
        paid = sum(r.amount_inr for r in paid_rows)
        if paid >= p.amount_inr:
            p.status = "KEPT"
            for r in paid_rows:
                r.matched_promise_id = p.id
            audit.append(
                session,
                actor="system",
                event_type="promise_kept",
                case_id=p.case_id,
                payload={"promise_id": p.id, "paid_inr": paid, "attribution": "voice_promise"},
            )
            if CaseState(case.state) not in TERMINAL:
                transition(
                    session,
                    case,
                    CaseState.RECOVERED,
                    actor="system",
                    payload={"promise_id": p.id, "attribution": "voice_promise"},
                )
        elif now > window_end:
            p.status = "PARTIAL" if paid > 0 else "BROKEN"
            for r in paid_rows:
                r.matched_promise_id = p.id
            if paid > 0:
                case.amount_due_inr -= paid  # remainder is what's still recoverable
            audit.append(
                session,
                actor="system",
                event_type=f"promise_{p.status.lower()}",
                case_id=p.case_id,
                payload={
                    "promise_id": p.id,
                    "paid_inr": paid,
                    "remaining_inr": case.amount_due_inr,
                },
            )
            if CaseState(case.state) not in TERMINAL:
                # next-day re-plan (one gentle follow-up) or escalation per policy
                transition(
                    session,
                    case,
                    CaseState.PLANNED,
                    actor="system",
                    payload={"why": f"promise_{p.status.lower()}", "promise_id": p.id},
                )
        else:
            continue  # window still open, keep waiting
        changed.append(p)
    session.flush()
    return changed


def promise_metrics(session: Session) -> dict:
    """FR-8.2 surface: made / kept-rate / ₹ via promises."""
    rows = list(session.scalars(select(PromiseRow)))
    kept = [p for p in rows if p.status == "KEPT"]
    return {
        "made": len(rows),
        "kept": len(kept),
        "kept_rate": len(kept) / len(rows) if rows else 0.0,
        "inr_via_promises": sum(p.amount_inr for p in kept),
    }
