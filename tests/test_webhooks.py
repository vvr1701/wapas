"""FR-2.3 tests: flag-gated, signature-verified, sample payload handled."""

import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import webhooks

SECRET = "whsec_test_dummy"  # test-only value, not a real credential


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ENABLE_WEBHOOKS", "true")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(webhooks, "DB_PATH", tmp_path / "t.db")
    app = FastAPI()
    app.include_router(webhooks.router)
    return TestClient(app)


def _signed(body: dict) -> tuple[bytes, str]:
    raw = json.dumps(body).encode()
    return raw, hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()


SAMPLE = {
    "event": "payment.captured",
    "payload": {
        "payment": {"entity": {"id": "pay_wh_1", "amount": 49900, "method": "upi", "notes": {}}}
    },
}


def test_valid_signature_handles_payment(client):
    raw, sig = _signed(SAMPLE)
    r = client.post("/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig})
    assert r.status_code == 200 and r.json()["handled"] == "payment.captured"


def test_bad_signature_rejected(client):
    raw, _ = _signed(SAMPLE)
    r = client.post("/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": "forged"})
    assert r.status_code == 401


def test_disabled_flag_hides_route(client, monkeypatch):
    monkeypatch.setenv("ENABLE_WEBHOOKS", "false")
    raw, sig = _signed(SAMPLE)
    r = client.post("/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig})
    assert r.status_code == 404
