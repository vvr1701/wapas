"""FR-7.1/7.4 exit-gate (CI-safe part): console serves, text mode works without
any external key, audio mode degrades gracefully mid-session instead of dying.
The live STT/TTS manual check is logged in BUILD_LOG (needs SARVAM_API_KEY)."""

import os

import pytest
from fastapi.testclient import TestClient

import channels.voice.console as console
from channels.voice.policy import DISCLOSURE
from ledger.db import get_engine


@pytest.fixture
def client(tmp_path, monkeypatch):
    # point the console at a throwaway DB
    monkeypatch.setattr(console, "get_engine", lambda: get_engine(tmp_path / "t.db"))
    return TestClient(console.app)


def test_page_serves(client):
    r = client.get("/")
    assert r.status_code == 200 and "call console" in r.text.lower()


def test_text_call_flow_and_midsession_mode_toggle(client):
    sid = client.post("/call/start").json()["session_id"]

    # turn 1: text mode; no ANTHROPIC key in CI -> deterministic fallback, disclosure first
    r1 = client.post("/call/turn", data={"session_id": sid, "mode": "text", "text": "Hello?"})
    assert r1.status_code == 200
    assert r1.json()["agent_text"].startswith(DISCLOSURE)
    assert r1.json()["agent_audio_b64"] is None

    # turn 2: toggle to audio mid-session with typed text. With a SARVAM key the
    # agent speaks (real TTS audio); without one it degrades to text — either way
    # the text keeps flowing and the session survives the toggle (NFR-7).
    r2 = client.post("/call/turn", data={"session_id": sid, "mode": "audio", "text": "haan boliye"})
    body = r2.json()
    assert body["agent_text"]
    if os.getenv("SARVAM_API_KEY"):
        assert body["agent_audio_b64"] and body["degraded"] is None
    else:
        assert body["agent_audio_b64"] is None and body["degraded"] == "text"

    # turn 3: back to text mode, same session continues
    r3 = client.post(
        "/call/turn", data={"session_id": sid, "mode": "text", "text": "call mat karo"}
    )
    assert r3.json()["ended"] is True

    # opt-out mid-call made the case terminal: post-call processing must stand down
    finish = client.post("/call/finish", data={"session_id": sid}).json()
    assert finish["outcome"] == "case_terminal"
