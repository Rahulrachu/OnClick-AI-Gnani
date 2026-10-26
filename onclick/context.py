"""Shared state passed to every tool."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import Config, workspace_dir


@dataclass
class Context:
    cfg: Config
    ask_user: Callable[[str], str] = lambda q: ""
    log: Callable[[str], None] = print
    workspace: Path = field(default_factory=workspace_dir)
    state: dict[str, Any] = field(default_factory=dict)  # long-lived handles (browser, counters)

    def close(self) -> None:
        sess = self.state.pop("browser", None)
        if sess:
            sess.close()
