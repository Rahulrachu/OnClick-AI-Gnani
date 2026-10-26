"""Gnani AI speech: Prisma v2.5 (speech-to-text) and Timbre v2.5 (text-to-speech).

Docs: https://docs.gnani.ai/api/introduction/quick-start
"""
from __future__ import annotations

import io
import json
import re
import time
import wave
from dataclasses import dataclass

import requests

STT_URL = "https://api.vachana.ai/stt/v3"
TTS_URL = "https://api.vachana.ai/api/v1/tts/inference"

# Language choices shown in the app. stt = Prisma language code, tts = (Timbre language, voice).
LANGUAGES: dict[str, dict] = {
    "kannada":  {"label": "ಕನ್ನಡ Kannada",       "stt": "kn-IN", "tts": ("kn-IN", "Saanvi")},
    "hinglish": {"label": "Hinglish",            "stt": "hi-IN", "tts": ("hi-en", "Poorvi")},
    "hindi":    {"label": "हिन्दी Hindi",          "stt": "hi-IN", "tts": ("hi-IN", "Nalini")},
    "english":  {"label": "English (India)",     "stt": "en-IN", "tts": ("en-IN", "Kaveri")},
    "tamil":    {"label": "தமிழ் Tamil",          "stt": "ta-IN", "tts": ("ta-IN", "Trisha")},
    "telugu":   {"label": "తెలుగు Telugu",        "stt": "te-IN", "tts": ("te-IN", "Lavanya")},
}

# App and PC words people say in English inside Kannada/Hindi sentences. Prisma's word boosting
# takes single letter-only words, so these help it keep "Chrome" as Chrome instead of a guess.
BIAS_WORDS = [
    "Chrome", "Edge", "Notepad", "Excel", "Word", "PowerPoint", "Spotify", "YouTube", "WhatsApp",
    "Gmail", "Explorer", "Downloads", "Desktop", "Documents", "Blender", "screenshot", "folder",
    "file", "volume", "brightness", "Bluetooth", "WiFi", "dark", "mode", "taskbar", "Settings",
    "open", "close", "search", "download", "PDF", "Google", "Amazon", "Flipkart", "Swiggy", "Zomato",
]


class GnaniError(RuntimeError):
    pass


@dataclass
class Transcript:
    text: str
    language: str
    latency_ms: int
    request_id: str = ""


def _err(r: requests.Response) -> str:
    try:
        e = r.json().get("error", {})
        return f"{r.status_code} {e.get('type', '')}: {e.get('message', r.text[:200])}"
    except ValueError:
        return f"{r.status_code}: {r.text[:200]}"


def transcribe(wav_bytes: bytes, language: str, api_key: str, *, boost: bool = True,
               timeout: float = 30.0) -> Transcript:
    """Send a WAV clip (<= 60 s) to Prisma v2.5 and return the transcript."""
    if not api_key:
        raise GnaniError("Add your Gnani API key in Settings (app.gnani.ai → API keys).")
    lang = LANGUAGES.get(language, LANGUAGES["english"])
    data = {"language_code": lang["stt"], "format": "transcribe"}  # ITN: "five hundred" -> 500
    if boost:
        data["bias_list"] = json.dumps(BIAS_WORDS)
        data["bias_score"] = "1.0"
    t0 = time.perf_counter()
    for attempt in range(3):
        r = requests.post(STT_URL, headers={"X-API-Key-ID": api_key}, data=data,
                          files={"audio_file": ("speech.wav", wav_bytes, "audio/wav")}, timeout=timeout)
        if r.status_code in (429, 500, 503) and attempt < 2:
            time.sleep(1.5 * (attempt + 1))
            continue
        break
    if r.status_code != 200:
        raise GnaniError("Speech-to-text failed: " + _err(r))
    body = r.json()
    if not body.get("success", True):
        raise GnaniError("Speech-to-text failed: " + json.dumps(body.get("error", body))[:300])
    return Transcript(text=(body.get("transcript") or "").strip(), language=language,
                      latency_ms=int((time.perf_counter() - t0) * 1000), request_id=body.get("request_id", ""))


_MD = re.compile(r"[*_`#>\[\]()|]")


def speakable(text: str, limit: int = 450) -> str:
    """Strip markdown and paths so Timbre reads a clean sentence, and keep it short."""
    text = re.sub(r"[A-Za-z]:\\[^\s]+|/[\w./-]{12,}", "the file", text)
    text = _MD.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        cut = text[:limit]
        text = cut[: max(cut.rfind("."), cut.rfind("।"), cut.rfind("?"), 120)] + "."
    return text


def synthesize(text: str, language: str, api_key: str, *, speed: float = 1.0, timeout: float = 30.0) -> bytes:
    """Return WAV bytes of `text` spoken by Timbre v2.5 in the language's native voice."""
    if not api_key:
        raise GnaniError("Add your Gnani API key in Settings.")
    tts_lang, voice = LANGUAGES.get(language, LANGUAGES["english"])["tts"]
    payload = {
        "text": speakable(text), "voice": voice, "model": "timbre-v2.5", "language": tts_lang, "speed": speed,
        "audio_config": {"sample_rate": 24000, "num_channels": 1, "sample_width": 2,
                         "encoding": "linear_pcm", "container": "wav"},
    }
    r = requests.post(TTS_URL, headers={"X-API-Key-ID": api_key, "Content-Type": "application/json"},
                      json=payload, timeout=timeout)
    if r.status_code != 200:
        raise GnaniError("Text-to-speech failed: " + _err(r))
    return r.content


def wav_duration(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        rate, width, ch = w.getframerate(), w.getsampwidth(), w.getnchannels()
        frames = w.getnframes()
    # Streamed WAVs (e.g. Timbre) carry a placeholder size; fall back to the real payload length.
    idx = wav_bytes.find(b"data")
    real = (len(wav_bytes) - (idx + 8)) // (width * ch) if idx >= 0 else frames
    return min(frames, real) / float(rate)
