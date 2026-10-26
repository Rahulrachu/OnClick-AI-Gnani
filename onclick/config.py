"""User settings, stored as JSON in the user's app-data folder."""
from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


def app_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "OnClickAI"
    d.mkdir(parents=True, exist_ok=True)
    return d


def workspace_dir() -> Path:
    d = Path.home() / "OnClickAI"
    d.mkdir(parents=True, exist_ok=True)
    return d


# Defaults per provider. All but Anthropic speak the OpenAI chat-completions dialect.
PROVIDERS: dict[str, dict] = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3.8-flash",
        "key_env": "GEMINI_API_KEY",
        "note": "Free tier key at aistudio.google.com/apikey",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1",
        "key_env": "OPENAI_API_KEY",
        "note": "platform.openai.com/api-keys",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-sonnet-4-5",
        "key_env": "ANTHROPIC_API_KEY",
        "note": "console.anthropic.com",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "google/gemini-2.5-flash",
        "key_env": "OPENROUTER_API_KEY",
        "note": "openrouter.ai/keys",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key_env": "GROQ_API_KEY",
        "note": "console.groq.com/keys (no vision)",
    },
    "evon": {
        "base_url": "http://localhost:8000/v1",
        "model": "gnani/gnani-evon-v3.3-30B-A3B",
        "key_env": "",
        "note": "Gnani Evon v3.3 served locally with vLLM or llama.cpp (OpenAI-compatible). See docs/EVON.md",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5:7b",
        "key_env": "",
        "note": "Runs locally, no key. Install from ollama.com",
    },
}


def find_blender() -> str:
    found = shutil.which("blender")
    if found:
        return found
    if sys.platform == "win32":
        roots = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Blender Foundation"]
        steam = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe")
        if steam.exists():
            return str(steam)
        for root in roots:
            if root.exists():
                exes = sorted(root.glob("Blender*/blender.exe"), reverse=True)
                if exes:
                    return str(exes[0])
    elif sys.platform == "darwin":
        mac = Path("/Applications/Blender.app/Contents/MacOS/Blender")
        if mac.exists():
            return str(mac)
    return ""


@dataclass
class Config:
    provider: str = "gemini"
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    blender_path: str = ""
    max_steps: int = 40
    # Actions that spend money, send messages, or delete things always ask first unless this is on.
    auto_approve_risky: bool = False
    browser_channel: str = "msedge" if sys.platform == "win32" else "chromium"
    headless_browser: bool = False
    # Voice (Gnani AI): Prisma v2.5 speech-to-text, Timbre v2.5 text-to-speech.
    gnani_api_key: str = ""
    voice_language: str = "kannada"
    speak_replies: bool = True
    extra: dict = field(default_factory=dict)

    def resolved_model(self) -> str:
        return self.model or PROVIDERS.get(self.provider, {}).get("model", "")

    def resolved_base_url(self) -> str:
        return self.base_url or PROVIDERS.get(self.provider, {}).get("base_url", "")

    def resolved_key(self) -> str:
        if self.api_key:
            return self.api_key
        env = PROVIDERS.get(self.provider, {}).get("key_env")
        return os.environ.get(env, "") if env else ""

    def resolved_blender(self) -> str:
        return self.blender_path or find_blender()

    @classmethod
    def path(cls) -> Path:
        return app_dir() / "config.json"

    @classmethod
    def load(cls) -> "Config":
        p = cls.path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
                return cls(**known)
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def save(self) -> None:
        self.path().write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    def is_ready(self) -> bool:
        return bool(self.resolved_key()) or self.provider in ("ollama", "evon")

    def resolved_gnani_key(self) -> str:
        return self.gnani_api_key or os.environ.get("GNANI_API_KEY", "")
