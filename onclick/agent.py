"""The agent loop: think, call tools, look at results, repeat until done."""
from __future__ import annotations

import json
import platform
import traceback
from datetime import datetime
from typing import Callable

from .context import Context
from .llm import LLMError, make_client
from .tools import ToolResult, build_registry

SYSTEM_PROMPT = """You are OnClick AI, an agent running directly on the user's {os} computer. You complete tasks end to end by calling tools, not by explaining how.

How you work:
- Make a short plan, then act. After each action, look at the result and adjust. Keep going until the task is truly done or impossible.
- Prefer the cheapest reliable tool: windows_settings for Windows look/theme/taskbar, web_search/fetch_url for information, browser_* tools for websites (bookings, forms, shopping), run_command for scripts/installs/files, blender_run_script for 3D, screenshot + mouse/keyboard only for desktop apps with no better route.
- Websites: read the snapshot's numbered elements and act by ref. Only the newest page snapshot is kept in full; older ones are trimmed, so act on the latest refs and call browser_snapshot if you need the page again. Use browser_screenshot when layout matters (date pickers, seat maps).
- If a site needs a login, ask_user whether they want to sign in themselves in the open browser window; then wait and continue.
- Missing details only the user knows (dates, passenger names, budget, choices): ask_user once, briefly, with your best suggestion.
- Money and commitments: never enter card numbers yourself. Before the final pay/book/order button, summarize what will be bought and the total; the app will ask the user to approve that click.
- 3D/Blender: write complete bpy scripts, render, inspect the image, and refine until it looks right. Save outputs in the workspace.
- Code projects: write files in the workspace, run them, fix errors.
- Never claim something was done unless a tool result shows it.

Voice requests: a message that starts with [voice:<language>] was spoken and transcribed by Gnani Prisma, so it may contain
code-mixed Kannada/Hindi/English, mis-heard app names or missing punctuation. Infer the intent generously (e.g. "Chrome open maadi"
= open Chrome, "volume kam karo" = lower the volume). If the intent is truly unclear, ask_user one short question. Your final reply
to a voice request is read aloud by Gnani Timbre: write it in that same language and script, at most two short sentences, no
markdown, no file paths.

When finished, reply with no tool calls: a short summary of what you did, where outputs are saved, and anything the user must do next.

Workspace folder: {workspace}
Now: {now}
"""

Event = Callable[[str, dict], None]
Approve = Callable[[str, dict, str], bool]


class Agent:
    def __init__(self, ctx: Context, on_event: Event | None = None, approve: Approve | None = None, client=None):
        self.ctx = ctx
        self.on_event = on_event or (lambda kind, data: None)
        self.approve = approve or (lambda name, args, reason: False)
        self.client = client or make_client(ctx.cfg)
        self.registry = build_registry(ctx)
        self.stop_requested = False
        self._tool_names: dict[int, str] = {}  # id(tool message) -> tool name, for compaction (ids can repeat across turns)
        self._compacted: set[int] = set()  # id(tool message) already trimmed (kept off the messages so providers never see extra keys)
        self.messages: list[dict] = [{
            "role": "system",
            "content": SYSTEM_PROMPT.format(os=f"{platform.system()} {platform.release()}", workspace=ctx.workspace,
                                            now=datetime.now().strftime("%A %d %B %Y, %H:%M")),
        }]

    def stop(self) -> None:
        self.stop_requested = True

    def _execute(self, name: str, args: dict) -> ToolResult:
        tool = self.registry.get(name)
        if tool is None:
            return ToolResult(f"Unknown tool {name}. Available: {', '.join(self.registry.tools)}")
        reason = tool.risk_reason(args)
        if reason and not self.ctx.cfg.auto_approve_risky:
            self.on_event("approval", {"tool": name, "args": args, "reason": reason})
            if not self.approve(name, args, reason):
                return ToolResult("The user declined this action. Do not retry it; ask what they want instead or stop.")
        try:
            return tool.func(**{k: v for k, v in args.items() if not k.startswith("_")})
        except TypeError as e:
            return ToolResult(f"Bad arguments for {name}: {e}")
        except Exception as e:  # tool failures go back to the model so it can recover
            return ToolResult(f"{name} failed: {type(e).__name__}: {e}\n{traceback.format_exc(limit=2)}")

    def run(self, prompt: str) -> str:
        self.stop_requested = False
        self.messages.append({"role": "user", "content": prompt})
        tools = self.registry.schemas()
        for step in range(1, self.ctx.cfg.max_steps + 1):
            if self.stop_requested:
                self.on_event("done", {"text": "Stopped."})
                return "Stopped."
            self.on_event("thinking", {"step": step})
            try:
                reply = self.client.chat(self.messages, tools)
            except LLMError as e:
                self.on_event("error", {"text": str(e)})
                return f"Model error: {e}"
            self.messages.append(reply.raw_assistant)
            if reply.text:
                self.on_event("say", {"text": reply.text})
            if not reply.tool_calls:
                self.on_event("done", {"text": reply.text})
                return reply.text
            images = []
            for call in reply.tool_calls:
                self.on_event("tool", {"name": call.name, "args": call.arguments})
                result = self._execute(call.name, call.arguments)
                self.on_event("result", {"name": call.name, "text": result.text[:600], "files": result.files,
                                         "has_image": bool(result.image_png),
                                         "image": result.image_data_url() if call.name in ("blender_run_script", "browser_screenshot", "screenshot") else None})
                tool_msg = {"role": "tool", "tool_call_id": call.id, "content": result.text}
                self.messages.append(tool_msg)
                self._tool_names[id(tool_msg)] = call.name
                if result.image_png:
                    images.append((call.name, result.image_data_url()))
            if images:
                parts = [{"type": "text", "text": "Images from: " + ", ".join(n for n, _ in images)}]
                parts += [{"type": "image_url", "image_url": {"url": url}} for _, url in images]
                self.messages.append({"role": "user", "content": parts})
            self._prune_images()
            self._compact_tool_results()
        msg = f"Reached the {self.ctx.cfg.max_steps}-step limit. Say 'continue' to keep going."
        self.on_event("done", {"text": msg})
        return msg

    def _prune_images(self, keep: int = 2) -> None:
        """Old screenshots are huge; keep only the most recent few."""
        seen = 0
        for m in reversed(self.messages):
            if m["role"] == "user" and isinstance(m["content"], list) and any(p.get("type") == "image_url" for p in m["content"]):
                seen += 1
                if seen > keep:
                    m["content"] = [p for p in m["content"] if p.get("type") == "text"] + [{"type": "text", "text": "(older image removed)"}]

    KEEP_FULL = 4          # most recent tool results kept verbatim
    OLD_LIMIT = 600        # older non-browser results are cut to this many chars
    OLD_SNAPSHOT_LIMIT = 300  # older browser page snapshots are cut harder

    def _compact_tool_results(self) -> None:
        """Keep the context small on long tasks.

        Every browser action returns a full page snapshot (up to ~8k chars). Only the latest
        one describes the page as it is now, so older snapshots shrink to their first lines
        (what was done, title, URL). Other tool results stay whole for the last KEEP_FULL
        calls and are trimmed after that.
        """
        tool_idx = [i for i, m in enumerate(self.messages) if m["role"] == "tool"]
        if not tool_idx:
            return
        latest_snapshot = None
        for i in reversed(tool_idx):
            if self._is_snapshot(self.messages[i]):
                latest_snapshot = i
                break
        recent = set(tool_idx[-self.KEEP_FULL:])
        for i in tool_idx:
            m = self.messages[i]
            text = m["content"] if isinstance(m["content"], str) else str(m["content"])
            if id(m) in self._compacted or i == latest_snapshot:
                continue
            if self._is_snapshot(m):
                limit = self.OLD_SNAPSHOT_LIMIT
                note = "[older page snapshot trimmed; call browser_snapshot for the current page]"
            elif i in recent:
                continue
            else:
                limit = self.OLD_LIMIT
                note = "[older tool output trimmed]"
            if len(text) > limit + len(note):
                m["content"] = text[:limit].rstrip() + "\n" + note
            self._compacted.add(id(m))

    def _is_snapshot(self, m: dict) -> bool:
        name = self._tool_names.get(id(m), "")
        return name.startswith("browser_") and name != "browser_screenshot"

    def transcript(self) -> str:
        return json.dumps([m for m in self.messages if m["role"] != "system"], indent=1)[:200000]
