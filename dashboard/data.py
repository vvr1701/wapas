"""Dashboard data layer (FR-12.1).

Single responsibility: every number the dashboard shows comes from a function
here, sourced from results/metrics.json, results/run_manifest.json, or the eval
SQLite — so the spot-check test can assert screen values == metrics.json keys,
and the per-case timeline provably renders from the audit log alone.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ledger.db import (
    AuditRow,
    CustomerRow,
    EscalationRow,
    PlannedActionRow,
    PromiseRow,
    RecoveryCaseRow,
    get_engine,
)

RESULTS = Path("results")
DEFAULT_EVAL_DB = Path("data/eval_seed42.db")


def load_metrics() -> dict:
    return json.loads((RESULTS / "metrics.json").read_text())


def load_manifest() -> dict:
    return json.loads((RESULTS / "run_manifest.json").read_text())


def session(db_path: Path = DEFAULT_EVAL_DB) -> Session:
    return Session(get_engine(db_path))


def kpis() -> dict:
    """Command-center headline numbers — verbatim metrics.json keys."""
    m = load_metrics()
    h = m["headline"]
    return {
        "at_risk_inr": h["at_risk_inr"],
        "recovered_raw_c_inr": h["recovered_raw_inr"]["C"],
        "recovered_adj_c_inr": h["recovered_adj_inr"]["C"],
        "lift_relative": h["lift"]["relative"],
        "stops_honored": h["stops_honored"],
        "promises_kept_rate": h["promises_kept_rate"],
        "exceptions_count": h["exceptions_count"],
        "natural_rate": m["attribution"]["natural_rate"],
    }


def cases_by_state(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(RecoveryCaseRow.state, func.count()).group_by(RecoveryCaseRow.state)
    ).all()
    return dict(sorted(rows))


def recovery_by_category(db: Session) -> list[dict]:
    rows = db.execute(
        select(
            RecoveryCaseRow.category,
            func.count(),
            func.sum(RecoveryCaseRow.amount_due_inr),
        ).group_by(RecoveryCaseRow.category)
    ).all()
    out = []
    for category, n, at_risk in rows:
        recovered = db.scalar(
            select(func.coalesce(func.sum(RecoveryCaseRow.amount_due_inr), 0)).where(
                RecoveryCaseRow.category == category, RecoveryCaseRow.state == "RECOVERED"
            )
        )
        out.append(
            {
                "category": category,
                "cases": n,
                "at_risk_inr": at_risk,
                "recovered_inr": recovered,
                "rate": recovered / at_risk if at_risk else 0,
            }
        )
    return out


def list_cases(db: Session, state: str | None = None, category: str | None = None) -> list[dict]:
    q = select(RecoveryCaseRow).order_by(RecoveryCaseRow.amount_due_inr.desc())
    if state:
        q = q.where(RecoveryCaseRow.state == state)
    if category:
        q = q.where(RecoveryCaseRow.category == category)
    return [
        {
            "case_id": c.id,
            "entity": c.entity_id,
            "customer": c.customer_id,
            "category": c.category,
            "amount_inr": c.amount_due_inr,
            "state": c.state,
            "root_cause": c.root_cause,
            "confidence": c.diagnosis_confidence,
        }
        for c in db.scalars(q)
    ]


def case_timeline(db: Session, case_id: int) -> list[dict]:
    """FR-10.3: rendered from the audit log ONLY — proving the log is complete."""
    return [
        {
            "ts": r.ts,
            "actor": r.actor,
            "event": r.event_type,
            "rule_id": r.rule_id,
            "detail": json.loads(r.payload_json),
            "hash": r.record_hash[:10],
            "prev": r.prev_record_hash[:10],
        }
        for r in db.scalars(
            select(AuditRow).where(AuditRow.case_id == case_id).order_by(AuditRow.id)
        )
    ]


def guardrails_view(db: Session) -> dict:
    m = load_metrics()
    blocked = db.execute(
        select(AuditRow.rule_id, func.count())
        .where(AuditRow.event_type == "action_blocked")
        .group_by(AuditRow.rule_id)
    ).all()
    optouts = db.scalar(
        select(func.count()).select_from(CustomerRow).where(CustomerRow.opted_out.is_(True))
    )
    cancelled = db.scalar(
        select(func.count())
        .select_from(PlannedActionRow)
        .where(PlannedActionRow.status == "CANCELLED")
    )
    return {
        "stops_honored": m["compliance"]["stops_honored"],
        "actions_after_optout": m["compliance"]["actions_after_optout"],
        "opt_out_registry_size": optouts,
        "cancelled_actions": cancelled,
        "blocked_by_reason": dict(blocked),
    }


def contact_hour_histogram(db: Session) -> dict[int, int]:
    """Executed customer contacts by IST hour — the contact-window heatmap.
    Uses executed_ts (world time), which the gate enforced against."""
    from datetime import datetime, timedelta

    from ledger.db import ExecutedActionRow

    hist: dict[int, int] = dict.fromkeys(range(24), 0)
    rows = db.scalars(select(ExecutedActionRow))
    for r in rows:
        if r.channel in {"email", "whatsapp", "voice"}:
            ist = datetime.fromisoformat(r.executed_ts) + timedelta(hours=5, minutes=30)
            hist[ist.hour] += 1
    return hist


def escalation_queue(db: Session) -> list[dict]:
    out = []
    for e in db.scalars(select(EscalationRow).order_by(EscalationRow.id)):
        packet = json.loads(e.context_packet_json)
        out.append(
            {
                "escalation_id": e.id,
                "case_id": e.case_id,
                "reason": e.reason,
                "acked_by": e.acked_by,
                "packet": packet,
            }
        )
    return out


def promises_list(db: Session) -> list[dict]:
    return [
        {
            "promise_id": p.id,
            "case_id": p.case_id,
            "amount_inr": p.amount_inr,
            "due_date": p.due_date,
            "status": p.status,
            "confidence": p.confidence,
        }
        for p in db.scalars(select(PromiseRow).order_by(PromiseRow.id))
    ]


def exceptions_table() -> str:
    path = Path("EXCEPTIONS.md")
    return path.read_text() if path.exists() else "run `make eval` first"


def _razorpay_ping() -> None:
    """Cheap reachability probe; any exception means unavailable."""
    import requests

    requests.head("https://api.razorpay.com", timeout=2).raise_for_status()


def razorpay_status() -> str:
    """NFR-7: live-API health for the degraded-mode banner. Never raises —
    simulator-driven screens keep working either way."""
    try:
        _razorpay_ping()
        return "live"
    except Exception:  # noqa: BLE001 — any failure is the same answer
        return "unavailable"
