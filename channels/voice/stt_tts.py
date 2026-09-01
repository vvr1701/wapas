"""Sarvam speech layer (FR-7.1) — the one-file swap point for voice vendors.

Single responsibility: speech_to_text / text_to_speech against Sarvam AI
(Saarika STT, Bulbul TTS — 11 Indian languages + English, auto-detected; see
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


# bulbul:v3 voices, per docs.sarvam.ai — TTS falls back to hi-IN off this list
TTS_LANGS = frozenset(
    f"{c}-IN" for c in ("bn", "en", "gu", "hi", "kn", "ml", "mr", "od", "pa", "ta", "te")
)


def speech_to_text(audio_bytes: bytes, *, mime: str = "audio/wav") -> tuple[str, str]:
    """One utterance in → (transcript, detected language_code). Saarika
    auto-detects the language (code-mixed Hinglish included)."""
    try:
        resp = requests.post(
            STT_URL,
            headers={"api-subscription-key": _key()},
            files={"file": ("utterance.wav", audio_bytes, mime)},
            data={"model": STT_MODEL, "language_code": "unknown"},
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
        body = resp.json()
        return body["transcript"], body.get("language_code") or "hi-IN"
    except SpeechUnavailable:
        raise
    except Exception as e:  # noqa: BLE001 — any vendor failure degrades identically
        raise SpeechUnavailable(f"STT failed: {e}") from e


def text_to_speech(text: str, *, lang: str = "hi-IN") -> bytes:
    """Agent line in, WAV bytes out — spoken in the caller's language."""
    try:
        resp = requests.post(
            TTS_URL,
            headers={"api-subscription-key": _key(), "Content-Type": "application/json"},
            json={
                "text": text,
                "target_language_code": lang if lang in TTS_LANGS else "hi-IN",
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
