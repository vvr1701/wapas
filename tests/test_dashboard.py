"""FR-12.1 exit-gate tests: on-screen numbers map to metrics.json keys, the
per-case timeline renders purely from the audit log, and the data layer loads
from the eval SQLite fast. Requires one `make eval SEED=42` beforehand (the
eval DB and results/ are inputs); skips honestly if absent."""

import json
import time
from pathlib import Path

import pytest
from sqlalchemy import select

from dashboard import data
from ledger.db import AuditRow

HAS_EVAL = data.DEFAULT_EVAL_DB.exists() and (data.RESULTS / "metrics.json").exists()
pytestmark = pytest.mark.skipif(not HAS_EVAL, reason="run `make eval SEED=42` first")


def test_five_kpis_map_to_metrics_keys():
    """Spot-check (exit gate): 5 on-screen numbers == their metrics.json keys."""
    m = json.loads((data.RESULTS / "metrics.json").read_text())
    k = data.kpis()
    assert k["at_risk_inr"] == m["headline"]["at_risk_inr"]
    assert k["recovered_raw_c_inr"] == m["headline"]["recovered_raw_inr"]["C"]
    assert k["recovered_adj_c_inr"] == m["headline"]["recovered_adj_inr"]["C"]
    assert k["stops_honored"] == m["headline"]["stops_honored"]
    assert k["lift_relative"] == m["headline"]["lift"]["relative"]


def test_timeline_renders_purely_from_audit_log():
    with data.session() as db:
        case = data.list_cases(db)[0]
        timeline = data.case_timeline(db, case["case_id"])
        audit_rows = db.scalars(
            select(AuditRow).where(AuditRow.case_id == case["case_id"]).order_by(AuditRow.id)
        ).all()
        assert len(timeline) == len(audit_rows) > 0  # 1:1 with the log, nothing else
        assert [t["event"] for t in timeline] == [r.event_type for r in audit_rows]


def test_cold_start_under_10s():
    started = time.monotonic()
    data.kpis()
    data.load_manifest()
    with data.session() as db:
        data.cases_by_state(db)
        data.recovery_by_category(db)
        data.list_cases(db)
        data.guardrails_view(db)
        data.contact_hour_histogram(db)
        data.escalation_queue(db)
        data.promises_list(db)
    assert time.monotonic() - started < 10


def test_guardrails_view_consistency():
    with data.session() as db:
        g = data.guardrails_view(db)
    assert g["stops_honored"] == 1.0
    assert g["actions_after_optout"] == 0
    assert "outside_contact_window" in g["blocked_by_reason"]


def test_contact_histogram_respects_window():
    """No executed customer contact outside 10:00–19:00 IST — the heatmap proof."""
    with data.session() as db:
        hist = data.contact_hour_histogram(db)
    outside = {h: n for h, n in hist.items() if n and not (10 <= h < 19)}
    assert outside == {}, f"contacts outside window: {outside}"


def test_streamlit_pages_importable():
    """Screens compile: a syntax error in any page fails here, not on demo day."""
    import ast

    pages = [Path("dashboard/app.py"), *sorted(Path("dashboard/pages").glob("*.py"))]
    assert len(pages) == 5
    for p in pages:
        ast.parse(p.read_text())
