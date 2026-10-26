"""Modern window: an HTML chat UI hosted in Edge WebView2 via pywebview."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from dataclasses import asdict
from pathlib import Path

from .agent import Agent
from .config import PROVIDERS, Config
from .context import Context
from . import voice as gvoice


def ui_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "onclick" / "ui" / "index.html"


class Bridge:
    """Methods here are callable from JavaScript as window.pywebview.api.<name>()."""

    def __init__(self):
        self._window = None
        self._jobs: queue.Queue = queue.Queue()
        self._answer: queue.Queue = queue.Queue()
        self._agent: Agent | None = None
        self._voice_lang: str | None = None
        self._ctx: Context | None = None
        threading.Thread(target=self._worker, daemon=True).start()

    # ---- called from JS ----
    def get_config(self):
        c = Config.load()
        d = asdict(c)
        d["blender_path"] = c.blender_path or c.resolved_blender()
        d["providers"] = PROVIDERS
        d["ready"] = c.is_ready()
        return d

    def save_config(self, data: dict):
        c = Config.load()
        for k, v in data.items():
            if k in Config.__dataclass_fields__:
                setattr(c, k, v)
        c.save()
        self._jobs.put(("reset", None))
        return True

    def submit(self, text: str):
        if not Config.load().is_ready():
            self._js("onEvent", "done", {"text": ""})
            return "needs_key"
        self._jobs.put(("run", text))
        return "ok"

    # ---- voice (Gnani Prisma STT + Timbre TTS) ----
    def languages(self):
        return {k: v["label"] for k, v in gvoice.LANGUAGES.items()}

    def listen(self, language: str = ""):
        """Record one utterance, transcribe it with Prisma, and run it as a task."""
        cfg = Config.load()
        if not cfg.resolved_gnani_key():
            return {"error": "Add your Gnani API key in Settings to use voice."}
        lang = language or cfg.voice_language
        threading.Thread(target=self._listen_once, args=(lang,), daemon=True).start()
        return {"ok": True}

    def _listen_once(self, lang: str):
        from .voice import mic
        cfg = Config.load()
        try:
            self._post("listening", {"language": lang})
            wav = mic.record(on_level=lambda lv: self._js("onLevel", round(lv, 3)))
            if len(wav) < 16000:  # under ~0.5 s of audio
                self._post("heard", {"text": "", "error": "I didn't catch that. Tap the mic and try again."})
                return
            self._post("transcribing", {})
            t = gvoice.transcribe(wav, lang, cfg.resolved_gnani_key())
            self._post("heard", {"text": t.text, "language": lang, "latency_ms": t.latency_ms})
            if t.text:
                self._voice_lang = lang
                self._jobs.put(("run", f"[voice:{lang}] {t.text}"))
        except Exception as e:
            self._post("heard", {"text": "", "error": f"{type(e).__name__}: {e}"})

    def speak(self, text: str, language: str = ""):
        threading.Thread(target=self._speak, args=(text, language), daemon=True).start()
        return True

    def _speak(self, text: str, language: str = ""):
        from .voice import mic
        cfg = Config.load()
        if not text or not cfg.resolved_gnani_key():
            return
        try:
            self._post("speaking", {})
            mic.play(gvoice.synthesize(text, language or cfg.voice_language, cfg.resolved_gnani_key()))
        except Exception as e:
            self._post("error", {"text": f"Voice reply failed: {e}"})
        finally:
            self._post("spoken", {})

    def stop(self):
        if self._agent:
            self._agent.stop()

    def new_chat(self):
        self._jobs.put(("reset", None))

    def answer(self, value):
        self._answer.put(value)

    def open_path(self, path: str):
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except OSError:
            pass

    # ---- internals ----
    def _js(self, fn: str, *args):
        if self._window:
            self._window.evaluate_js(f"{fn}({', '.join(json.dumps(a) for a in args)})")

    def _post(self, kind: str, data: dict):
        self._js("onEvent", kind, data)
        # Read the final answer of a spoken request aloud in the language it was asked in.
        if kind == "done" and self._voice_lang and data.get("text"):
            lang, self._voice_lang = self._voice_lang, None
            if Config.load().speak_replies:
                self.speak(data["text"], lang)

    def _ask_user(self, question: str) -> str:
        self._js("askUser", question)
        return str(self._answer.get() or "")

    def _approve(self, name: str, args: dict, reason: str) -> bool:
        detail = name + "\n" + "\n".join(f"{k}: {str(v)[:300]}" for k, v in args.items())
        self._js("askApproval", reason, detail)
        return self._answer.get() is True

    def _worker(self):
        # One thread runs every task so the browser session survives between prompts.
        while True:
            kind, payload = self._jobs.get()
            try:
                if kind == "reset":
                    if self._ctx:
                        self._ctx.close()
                    self._agent = self._ctx = None
                    continue
                if self._agent is None:
                    self._ctx = Context(cfg=Config.load(), ask_user=self._ask_user)
                    self._agent = Agent(self._ctx, on_event=self._post, approve=self._approve)
                self._agent.run(payload)
            except Exception as e:
                self._post("error", {"text": f"{type(e).__name__}: {e}"})
                self._post("done", {"text": ""})


def main():
    import webview

    bridge = Bridge()
    window = webview.create_window("OnClick AI", url=str(ui_path()), js_api=bridge, width=1080, height=760,
                                   min_size=(720, 520), background_color="#0b0c10")
    bridge._window = window
    webview.start()
