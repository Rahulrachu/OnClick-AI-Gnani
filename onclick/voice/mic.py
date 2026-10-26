"""Microphone capture with a small noise-robust voice activity detector.

Recording starts when you press the mic button (or Ctrl+Space) and stops by itself after you stop
talking. The noise floor is measured in the first 300 ms, so a fan or a noisy hostel room raises the
speech threshold instead of being sent as speech. Audio is high-passed (removes hum), peak-normalised
and trimmed of silence before it goes to Prisma, which keeps clips short and credits low.
"""
from __future__ import annotations

import io
import wave
from typing import Callable

import numpy as np

RATE = 16000
FRAME = 480  # 30 ms


def _highpass(x: np.ndarray, rate: int = RATE, cutoff: float = 90.0) -> np.ndarray:
    # One-pole high-pass: removes mains hum and desk thumps below ~90 Hz.
    rc = 1.0 / (2 * np.pi * cutoff)
    a = rc / (rc + 1.0 / rate)
    y = np.empty_like(x)
    prev_x = prev_y = 0.0
    for i, v in enumerate(x):
        prev_y = a * (prev_y + v - prev_x)
        prev_x = v
        y[i] = prev_y
    return y


def clean(samples: np.ndarray, rate: int = RATE) -> np.ndarray:
    """Float32 mono in [-1, 1] -> cleaned float32: high-pass, trim silence, normalise."""
    x = samples.astype(np.float32)
    if x.size == 0:
        return x
    x = _highpass(x - x.mean(), rate)
    frames = x[: len(x) // FRAME * FRAME].reshape(-1, FRAME)
    if len(frames):
        energy = np.sqrt((frames ** 2).mean(axis=1))
        floor = np.percentile(energy, 20)
        voiced = np.where(energy > max(floor * 3.0, 0.004))[0]
        if voiced.size:
            start = max(voiced[0] - 8, 0) * FRAME          # keep 240 ms before speech
            end = min(voiced[-1] + 12, len(frames)) * FRAME  # and 360 ms after
            x = x[start:end]
    peak = float(np.abs(x).max()) if x.size else 0.0
    if peak > 1e-4:
        x = x * (0.9 / peak)
    return x


def to_wav(samples: np.ndarray, rate: int = RATE) -> bytes:
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def record(max_seconds: float = 15.0, silence_ms: int = 900, on_level: Callable[[float], None] | None = None,
           should_stop: Callable[[], bool] | None = None) -> bytes:
    """Record until the speaker goes quiet (or max_seconds). Returns cleaned 16 kHz WAV bytes."""
    import sounddevice as sd

    chunks: list[np.ndarray] = []
    noise: list[float] = []
    heard_speech = False
    quiet_frames = 0
    need_quiet = silence_ms // 30
    with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=FRAME) as stream:
        for i in range(int(max_seconds * 1000 / 30)):
            block, _ = stream.read(FRAME)
            block = block[:, 0].copy()
            chunks.append(block)
            rms = float(np.sqrt((block ** 2).mean()))
            if on_level:
                on_level(min(rms * 12, 1.0))
            if i < 10:                      # first 300 ms: learn the room's noise floor
                noise.append(rms)
                continue
            threshold = max(np.median(noise) * 3.0, 0.006)
            if rms > threshold:
                heard_speech, quiet_frames = True, 0
            elif heard_speech:
                quiet_frames += 1
                if quiet_frames >= need_quiet:
                    break
            if should_stop and should_stop():
                break
            if not heard_speech and i > 200:  # 6 s of nothing: give up
                break
    audio = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
    return to_wav(clean(audio))


def play(wav_bytes: bytes) -> None:
    import sounddevice as sd

    with wave.open(io.BytesIO(wav_bytes)) as w:
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1)
    sd.play(data, rate)
    sd.wait()
