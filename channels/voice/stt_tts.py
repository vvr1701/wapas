"""Sarvam speech layer (FR-7.1) — the one-file swap point for voice vendors.

Single responsibility: speech_to_text / text_to_speech against Sarvam AI
(Saarika STT, Bulbul TTS — chosen for native Hinglish code-switching; see
BUILD_LOG research note). Any failure raises SpeechUnavailable; the console
degrades to text mode (FR-7.4, NFR-7) rather than dying. Endpoint shapes
verified against docs.sarvam.ai at the Day-8 spike; swap vendors by editing
only this file.
"""

from __future__ import annotations

import base64
import os

import requests

STT_URL = "https://api.sarvam.ai/speech-to-text"
TTS_URL = "https://api.sarvam.ai/text-to-speech"
STT_MODEL = "saarika:v2.5"
TTS_MODEL = "bulbul:v3"
TTS_SPEAKER = "priya"
TIMEOUT_S = 15


class SpeechUnavailable(Exception):
    """STT/TTS failed or unconfigured — degrade to text mode, never crash."""


def _key() -> str:
    key = os.getenv("SARVAM_API_KEY", "")
    if not key:
        raise SpeechUnavailable("SARVAM_API_KEY not configured")
    return key


def speech_to_text(audio_bytes: bytes, *, mime: str = "audio/wav") -> str:
    """One utterance in, Hinglish transcript out (code-mixed natively)."""
    try:
        resp = requests.post(
            STT_URL,
            headers={"api-subscription-key": _key()},
            files={"file": ("utterance.wav", audio_bytes, mime)},
            data={"model": STT_MODEL, "language_code": "unknown"},
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
        return resp.json()["transcript"]
    except SpeechUnavailable:
        raise
    except Exception as e:  # noqa: BLE001 — any vendor failure degrades identically
        raise SpeechUnavailable(f"STT failed: {e}") from e


def text_to_speech(text: str) -> bytes:
    """Agent line in, WAV bytes out."""
    try:
        resp = requests.post(
            TTS_URL,
            headers={"api-subscription-key": _key(), "Content-Type": "application/json"},
            json={
                "text": text,
                "target_language_code": "hi-IN",
                "model": TTS_MODEL,
                "speaker": TTS_SPEAKER,
            },
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
        return base64.b64decode(resp.json()["audios"][0])
    except SpeechUnavailable:
        raise
    except Exception as e:  # noqa: BLE001
        raise SpeechUnavailable(f"TTS failed: {e}") from e
