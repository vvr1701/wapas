"""Append-only hash-chained audit log (FR-10.1) — the trust anchor.

Single responsibility: append audit records whose hashes chain
(record_hash = SHA256(prev_record_hash + canonical_payload)) and verify the
chain end to end. `python -m ledger.audit --verify` backs `make verify-audit`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ledger.db import DEFAULT_DB, AuditRow, get_engine

GENESIS = "0" * 64


def _canonical(row_fields: dict) -> str:
    """Stable serialization of the hashed fields. Uses stored strings only, so
    verification never depends on type round-trips."""
    return json.dumps(row_fields, sort_keys=True, separators=(",", ":"))


def _fields(
    ts: str,
    case_id: int | None,
    actor: str,
    event_type: str,
    payload_json: str,
    rule_id: str | None,
    policy_version_hash: str | None,
) -> dict:
    return {
        "ts": ts,
        "case_id": case_id,
        "actor": actor,
        "event_type": event_type,
        "payload_json": payload_json,
        "rule_id": rule_id,
        "policy_version_hash": policy_version_hash,
    }


def append(
    session: Session,
    *,
    actor: str,
    event_type: str,
    payload: dict,
    case_id: int | None = None,
    rule_id: str | None = None,
    policy_version_hash: str | None = None,
) -> AuditRow:
    """Append one record, chained to the current head. Flushes so the row is
    ordered within the caller's transaction."""
    prev = (
        session.scalar(select(AuditRow.record_hash).order_by(AuditRow.id.desc()).limit(1))
        or GENESIS
    )
    ts = datetime.now(UTC).isoformat()
    payload_json = json.dumps(payload, sort_keys=True, default=str)
    canonical = _canonical(
        _fields(ts, case_id, actor, event_type, payload_json, rule_id, policy_version_hash)
    )
    row = AuditRow(
        ts=ts,
        case_id=case_id,
        actor=actor,
        event_type=event_type,
        payload_json=payload_json,
        rule_id=rule_id,
        policy_version_hash=policy_version_hash,
        prev_record_hash=prev,
        record_hash=hashlib.sha256((prev + canonical).encode()).hexdigest(),
    )
    session.add(row)
    session.flush()
    return row


def verify(session: Session) -> tuple[bool, str]:
    """Walk the chain from genesis; any mutation, insertion, or deletion breaks it."""
    prev = GENESIS
    count = 0
    for row in session.scalars(select(AuditRow).order_by(AuditRow.id)):
        if row.prev_record_hash != prev:
            return False, f"broken chain link at audit id={row.id}"
        canonical = _canonical(
            _fields(
                row.ts,
                row.case_id,
                row.actor,
                row.event_type,
                row.payload_json,
                row.rule_id,
                row.policy_version_hash,
            )
        )
        expected = hashlib.sha256((prev + canonical).encode()).hexdigest()
        if row.record_hash != expected:
            return False, f"record tampered at audit id={row.id}"
        prev = row.record_hash
        count += 1
    return True, f"audit chain intact: {count} records"


def main() -> None:
    p = argparse.ArgumentParser(description="Verify the audit hash chain")
    p.add_argument("--verify", action="store_true", required=True)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = p.parse_args()
    with Session(get_engine(args.db)) as session:
        ok, msg = verify(session)
    print(("OK: " if ok else "FAIL: ") + msg)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
