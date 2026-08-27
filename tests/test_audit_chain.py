"""FR-10.1 exit-gate tests: chain integrity, tamper detection, deletion detection."""

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ledger import audit
from ledger.db import AuditRow, get_engine


@pytest.fixture
def session(tmp_path):
    with Session(get_engine(tmp_path / "t.db")) as s:
        yield s


def _fill(session, n=5):
    for i in range(n):
        audit.append(session, actor="system", event_type="test_event", payload={"i": i})
    session.commit()


def test_clean_chain_verifies(session):
    ok, msg = audit.verify(session)
    assert ok and "0 records" in msg  # clean DB passes (make verify-audit path)
    _fill(session)
    ok, msg = audit.verify(session)
    assert ok and "5 records" in msg


def test_mutated_row_detected(session):
    _fill(session)
    session.execute(update(AuditRow).where(AuditRow.id == 3).values(payload_json='{"i":99}'))
    session.commit()
    ok, msg = audit.verify(session)
    assert not ok and "id=3" in msg


def test_deleted_row_detected(session):
    _fill(session)
    row = session.scalar(select(AuditRow).where(AuditRow.id == 3))
    session.delete(row)
    session.commit()
    ok, _ = audit.verify(session)
    assert not ok


def test_rehashed_tamper_detected(session):
    """Attacker rewrites a payload AND recomputes that row's hash — the next
    row's prev link still exposes it."""
    _fill(session)
    import hashlib
    import json

    row = session.scalar(select(AuditRow).where(AuditRow.id == 3))
    row.payload_json = '{"i":99}'
    canonical = json.dumps(
        {
            "ts": row.ts,
            "case_id": row.case_id,
            "actor": row.actor,
            "event_type": row.event_type,
            "payload_json": row.payload_json,
            "rule_id": row.rule_id,
            "policy_version_hash": row.policy_version_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    row.record_hash = hashlib.sha256((row.prev_record_hash + canonical).encode()).hexdigest()
    session.commit()
    ok, msg = audit.verify(session)
    assert not ok and "id=4" in msg
