"""Measure how well Gnani Prisma hears OnClick AI commands, on your own recordings.

Put clips in eval/clips/ and a manifest eval/manifest.csv with columns:
    file,language,reference,condition
    kn_01.wav,kannada,Chrome open maadi,quiet
    kn_01_fan.wav,kannada,Chrome open maadi,fan noise

Run:  GNANI_API_KEY=... python tools/eval_voice.py
It prints word error rate (WER) per language and per condition, plus latency, and writes
eval/results.csv and eval/REPORT.md for the submission.
"""
from __future__ import annotations

import csv
import os
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from onclick.voice import gnani  # noqa: E402
from onclick.voice import mic  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "eval"


def norm(s: str) -> list[str]:
    s = re.sub(r"[^\w\s]", " ", s.lower())
    return s.split()


def wer(ref: str, hyp: str) -> float:
    r, h = norm(ref), norm(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(len(r), 1)


def load_clip(path: Path, clean: bool) -> bytes:
    import wave
    import numpy as np
    with wave.open(str(path)) as w:
        rate, ch = w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype("float32") / 32768
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return mic.to_wav(mic.clean(x, rate) if clean else x, rate)


def main():
    key = os.environ.get("GNANI_API_KEY", "")
    rows = list(csv.DictReader(open(ROOT / "manifest.csv", encoding="utf-8")))
    out = []
    for row in rows:
        for cleaned in (False, True):
            t = gnani.transcribe(load_clip(ROOT / "clips" / row["file"], cleaned), row["language"], key)
            out.append({**row, "cleaned": cleaned, "hypothesis": t.text,
                        "wer": round(wer(row["reference"], t.text), 3), "latency_ms": t.latency_ms})
            print(f"{row['file']:<22} {'clean' if cleaned else 'raw  '} WER {out[-1]['wer']:.2f}  {t.text}")
    with open(ROOT / "results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    groups = defaultdict(list)
    for o in out:
        groups[(o["language"], o["condition"], "cleaned" if o["cleaned"] else "raw")].append(o)
    lines = ["# Gnani Prisma v2.5 on OnClick AI voice commands", "",
             "| Language | Condition | Audio | Clips | Mean WER | Median latency |", "|---|---|---|---|---|---|"]
    for (lang, cond, audio), g in sorted(groups.items()):
        lines.append(f"| {lang} | {cond} | {audio} | {len(g)} | {statistics.mean(x['wer'] for x in g):.1%} | "
                     f"{statistics.median(x['latency_ms'] for x in g):.0f} ms |")
    (ROOT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
