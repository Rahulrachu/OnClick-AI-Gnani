import io
import json
import wave

import numpy as np
import pytest

from onclick.voice import gnani
from onclick.voice import mic


class FakeResp:
    def __init__(self, status=200, body=None, content=b""):
        self.status_code = status
        self._body = body or {}
        self.content = content
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


def _tone(seconds=1.0, rate=16000, amp=0.3):
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_transcribe_sends_language_bias_and_itn(monkeypatch):
    seen = {}

    def fake_post(url, headers=None, data=None, files=None, timeout=None):
        seen.update(url=url, headers=headers, data=data, files=files)
        return FakeResp(body={"success": True, "request_id": "r1", "transcript": " Chrome open maadi "})

    monkeypatch.setattr(gnani.requests, "post", fake_post)
    t = gnani.transcribe(b"RIFF....", "kannada", "KEY")
    assert t.text == "Chrome open maadi"
    assert seen["url"] == gnani.STT_URL
    assert seen["headers"]["X-API-Key-ID"] == "KEY"
    assert seen["data"]["language_code"] == "kn-IN"
    assert seen["data"]["format"] == "transcribe"
    assert "Chrome" in json.loads(seen["data"]["bias_list"])


def test_bias_words_follow_prisma_rules():
    assert len(gnani.BIAS_WORDS) <= 100
    assert all(w.isalpha() for w in gnani.BIAS_WORDS)


def test_transcribe_retries_then_raises(monkeypatch):
    calls = []
    monkeypatch.setattr(gnani.time, "sleep", lambda s: None)
    monkeypatch.setattr(gnani.requests, "post", lambda *a, **k: calls.append(1) or FakeResp(503, {"error": {"type": "SERVICE_UNAVAILABLE", "message": "down"}}))
    with pytest.raises(gnani.GnaniError, match="SERVICE_UNAVAILABLE"):
        gnani.transcribe(b"x", "hindi", "KEY")
    assert len(calls) == 3


def test_missing_key_is_a_clear_error():
    with pytest.raises(gnani.GnaniError, match="API key"):
        gnani.transcribe(b"x", "english", "")


def test_synthesize_uses_native_voice(monkeypatch):
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(url=url, payload=json)
        return FakeResp(content=b"WAVDATA")

    monkeypatch.setattr(gnani.requests, "post", fake_post)
    out = gnani.synthesize("**Done.** Saved to C:\\Users\\rahul\\OnClickAI\\a.pdf", "kannada", "KEY")
    assert out == b"WAVDATA"
    p = seen["payload"]
    assert (p["language"], p["voice"], p["model"]) == ("kn-IN", "Saanvi", "timbre-v2.5")
    assert "*" not in p["text"] and "C:\\" not in p["text"]


def test_speakable_shortens_long_text():
    s = gnani.speakable("This is a sentence. " * 60)
    assert len(s) <= 460 and s.endswith(".")


def test_clean_trims_silence_and_normalises():
    rate = 16000
    noise = (np.random.default_rng(0).normal(0, 0.002, rate)).astype(np.float32)
    audio = np.concatenate([noise, _tone(1.0) + noise[:rate], noise])
    out = mic.clean(audio, rate)
    assert len(out) < len(audio) * 0.7          # leading/trailing room noise removed
    assert 0.85 < np.abs(out).max() <= 0.91     # peak-normalised


def test_to_wav_roundtrip():
    wav = mic.to_wav(_tone(0.5))
    with wave.open(io.BytesIO(wav)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
        assert w.getnframes() == 8000
