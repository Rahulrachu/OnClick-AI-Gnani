"""Shell, files, apps, and asking the user."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from ..safety import command_risk
from . import Tool, ToolResult, params

IS_WIN = sys.platform == "win32"


def _trim(s: str, n: int = 6000) -> str:
    return s if len(s) <= n else s[: n // 2] + "\n...[trimmed]...\n" + s[-n // 2 :]


def tools(ctx):
    def resolve(p: str) -> Path:
        path = Path(os.path.expandvars(os.path.expanduser(p)))
        return path if path.is_absolute() else ctx.workspace / path

    def run_command(command: str, timeout: int = 120, cwd: str = "") -> ToolResult:
        workdir = resolve(cwd) if cwd else ctx.workspace
        argv = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command] if IS_WIN else ["bash", "-lc", command]
        try:
            p = subprocess.run(argv, cwd=workdir, capture_output=True, text=True, timeout=timeout,
                               encoding="utf-8", errors="replace",
                               creationflags=subprocess.CREATE_NO_WINDOW if IS_WIN else 0)
        except subprocess.TimeoutExpired:
            return ToolResult(f"Timed out after {timeout}s.")
        out = (p.stdout or "") + (("\n[stderr]\n" + p.stderr) if p.stderr else "")
        return ToolResult(f"exit code {p.returncode}\n{_trim(out)}")

    def open_app(target: str) -> ToolResult:
        """Open an app, file, folder, or URL the way double-clicking would."""
        try:
            if IS_WIN:
                if os.path.exists(os.path.expandvars(target)):
                    os.startfile(os.path.expandvars(target))  # type: ignore[attr-defined]
                else:
                    subprocess.Popen(["cmd", "/c", "start", "", target], creationflags=subprocess.CREATE_NO_WINDOW)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-a", target] if not os.path.exists(target) else ["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
        except OSError as e:
            return ToolResult(f"Could not open {target}: {e}")
        time.sleep(2)
        return ToolResult(f"Opened {target}. Take a screenshot to see it.")

    def read_file(path: str) -> ToolResult:
        p = resolve(path)
        if not p.exists():
            return ToolResult(f"No such file: {p}")
        return ToolResult(_trim(p.read_text(encoding="utf-8", errors="replace"), 20000))

    def write_file(path: str, content: str) -> ToolResult:
        p = resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return ToolResult(f"Wrote {len(content)} chars to {p}", files=[str(p)])

    def list_dir(path: str = ".") -> ToolResult:
        p = resolve(path)
        if not p.exists():
            return ToolResult(f"No such folder: {p}")
        rows = [f"{'[dir] ' if c.is_dir() else ''}{c.name}" for c in sorted(p.iterdir())[:300]]
        return ToolResult(f"{p}\n" + "\n".join(rows))

    def ask_user(question: str) -> ToolResult:
        answer = ctx.ask_user(question)
        return ToolResult(f"User answered: {answer}" if answer else "User gave no answer.")

    def write_risk(args: dict):
        p = resolve(args.get("path", ""))
        try:
            p.resolve().relative_to(ctx.workspace.resolve())
            return None
        except ValueError:
            return f"Writes outside the OnClickAI folder: {p}" if p.exists() else None

    shell = "PowerShell" if IS_WIN else "bash"
    return [
        Tool("run_command", f"Run a {shell} command on the user's computer and return its output. Default folder is the OnClickAI workspace. Use for installing packages (winget, pip), scripts, git, file operations.",
             params(["command"], command={"type": "string"}, timeout={"type": "integer", "description": "seconds, default 120"},
                    cwd={"type": "string"}), run_command, risk=command_risk),
        Tool("open_app", "Open an application by name or path (e.g. 'notepad', 'blender', 'C:/path/file.blend'), a file, a folder, or a URL in the default program.",
             params(["target"], target={"type": "string"}), open_app),
        Tool("read_file", "Read a text file. Relative paths are inside the OnClickAI workspace.", params(["path"], path={"type": "string"}), read_file),
        Tool("write_file", "Create or overwrite a text file. Relative paths are inside the OnClickAI workspace.",
             params(["path", "content"], path={"type": "string"}, content={"type": "string"}), write_file, risk=write_risk),
        Tool("list_dir", "List a folder's contents.", params([], path={"type": "string"}), list_dir),
        Tool("ask_user", "Ask the user a question and wait for their answer. Use for missing details (dates, names, budget, which option), one-time codes, and choices only they can make.",
             params(["question"], question={"type": "string"}), ask_user),
    ]
