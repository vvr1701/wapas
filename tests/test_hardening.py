"""Phase 10 exit-gate tests (NFR-2, NFR-7): SIGKILL mid-batch then resume with
zero duplicate actions, and the degradation paths."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from channels.voice import promise_parser
from ledger import audit
from ledger.db import ExecutedActionRow, get_engine

REPO = Path(__file__).resolve().parent.parent


def test_kill_and_resume_no_duplicate_actions(tmp_path):
    """NFR-2: SIGKILL mid-batch -> resume -> no duplicate actions, chain intact."""
    db_path = tmp_path / "kill.db"
    cmd = [sys.executable, "-m", "tests._kill_resume_driver", str(db_path)]
    proc = subprocess.Popen(
        [*cmd, "slow"], cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    deadline = time.monotonic() + 60
    killed = False
    while time.monotonic() < deadline:  # wait until real work exists, then kill hard
        time.sleep(0.3)
        if proc.poll() is not None:
            break
        if db_path.exists():
            with Session(get_engine(db_path)) as s:
                n = s.scalar(select(func.count()).select_from(ExecutedActionRow)) or 0
            if n >= 3:
                os.kill(proc.pid, signal.SIGKILL)
                proc.wait()
                killed = True
                break
    assert killed, "driver finished before it could be killed — slow it down"
    with Session(get_engine(db_path)) as s:
        mid_run = s.scalar(select(func.count()).select_from(ExecutedActionRow))
    assert mid_run >= 3

    resumed = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=120)
    assert resumed.returncode == 0 and "DONE" in resumed.stdout, resumed.stderr[-800:]

    with Session(get_engine(db_path)) as s:
        rows = list(s.scalars(select(ExecutedActionRow)))
        keys = [r.idempotency_key for r in rows]
        assert len(keys) == len(set(keys))  # no duplicate executions, ever
        planned_ids = [r.planned_id for r in rows]
        assert len(planned_ids) == len(set(planned_ids))  # each action ran at most once
        ok, msg = audit.verify(s)
        assert ok, msg


# --- NFR-7: LLM invalid output degrades, never crashes -------------------------


def test_extraction_invalid_json_routes_to_review(monkeypatch):
    monkeypatch.setattr(
        promise_parser, "call_claude", lambda *a, **k: "sure! I promise to pay someday :)"
    )
    d = promise_parser.extract_promise(
        None,
        [{"role": "customer", "text": "kal pakka"}],
        amount_due_inr=18000,
        call_date=__import__("datetime").date(2026, 8, 27),
    )
    assert not d.auto_record and d.review_reason == "invalid_output"


def test_extraction_llm_down_routes_to_review(monkeypatch):
    def down(*a, **k):
        raise promise_parser.LlmUnavailable("api down")

    monkeypatch.setattr(promise_parser, "call_claude", down)
    d = promise_parser.extract_promise(
        None,
        [{"role": "customer", "text": "kal pakka"}],
        amount_due_inr=18000,
        call_date=__import__("datetime").date(2026, 8, 27),
    )
    assert not d.auto_record and d.review_reason == "llm_unavailable"


# --- NFR-7: Razorpay-down banner ----------------------------------------------


def test_razorpay_status_degrades_gracefully(monkeypatch):
    from dashboard import data

    monkeypatch.setattr(
        data, "_razorpay_ping", lambda: (_ for _ in ()).throw(OSError("network down"))
    )
    assert data.razorpay_status() == "unavailable"


def test_razorpay_status_never_raises():
    from dashboard import data

    assert data.razorpay_status() in {"live", "unavailable"}
