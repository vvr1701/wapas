"""PRD v1.1: /api/* routes are thin wrappers over dashboard/data.py — same
skip condition as the dashboard tests (they read the eval artifacts)."""

import pytest
from fastapi.testclient import TestClient

from channels.voice.console import app
from dashboard import data

HAS_EVAL = data.DEFAULT_EVAL_DB.exists() and (data.RESULTS / "metrics.json").exists()
pytestmark = pytest.mark.skipif(not HAS_EVAL, reason="run `make eval SEED=42` first")

client = TestClient(app)


def test_overview_matches_metrics():
    body = client.get("/api/overview").json()
    assert body["kpis"] == data.kpis()
    assert body["razorpay"] in {"live", "unavailable"}
    # 250 events dedupe to one case per unique entity (FR-2.2)
    n_cases = len(client.get("/api/cases").json())
    assert sum(body["by_state"].values()) == n_cases > 200


def test_cases_and_timeline():
    cases = client.get("/api/cases", params={"category": "L3"}).json()
    assert cases and all(c["category"] == "L3" for c in cases)
    timeline = client.get(f"/api/cases/{cases[0]['case_id']}/timeline").json()
    assert timeline and timeline[0]["event"] == "case_opened"


def test_remaining_routes_serve():
    for route in (
        "/api/metrics",
        "/api/manifest",
        "/api/variance",
        "/api/guardrails",
        "/api/escalations",
        "/api/promises",
        "/api/exceptions",
    ):
        r = client.get(route)
        assert r.status_code == 200, route
    g = client.get("/api/guardrails").json()
    assert g["stops_honored"] == 1.0 and len(g["heatmap_ist"]) == 24
