"""Desktop window: type a prompt, watch the agent work, approve risky steps."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, simpledialog, ttk

from . import __version__
from .agent import Agent
from .config import PROVIDERS, Config
from .context import Context

BG, PANEL, FG, MUTED, ACCENT, WARN = "#0f1115", "#171a21", "#e8e8ea", "#8b8f98", "#4f8cff", "#ffb547"


class Worker(threading.Thread):
    """One long-lived thread runs every task, so the browser session survives between prompts."""

    def __init__(self, app: "App"):
        super().__init__(daemon=True)
        self.app = app
        self.jobs: queue.Queue = queue.Queue()
        self.agent: Agent | None = None
        self.ctx: Context | None = None

    def run(self):
        while True:
            job = self.jobs.get()
            if job is None:
                break
            kind, payload = job
            try:
                if kind == "reset":
                    if self.ctx:
                        self.ctx.close()
                    self.agent = self.ctx = None
                    continue
                if self.agent is None:
                    cfg = Config.load()
                    self.ctx = Context(cfg=cfg, ask_user=self.app.ask_user_blocking, log=lambda s: self.app.post("log", {"text": s}))
                    self.agent = Agent(self.ctx, on_event=self.app.post, approve=self.app.approve_blocking)
                self.agent.run(payload)
            except Exception as e:
                self.app.post("error", {"text": f"{type(e).__name__}: {e}"})
                self.app.post("done", {"text": ""})


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"OnClick AI {__version__}")
        self.root.geometry("920x680")
        self.root.configure(bg=BG)
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self._build()
        self.worker = Worker(self)
        self.worker.start()
        self.root.after(100, self._drain)
        if not Config.load().is_ready():
            self.root.after(300, self.open_settings)

    # ---------- layout ----------
    def _build(self):
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(top, text="OnClick AI", fg=FG, bg=BG, font=("Segoe UI", 16, "bold")).pack(side="left")
        self.status = tk.Label(top, text="Ready", fg=MUTED, bg=BG, font=("Segoe UI", 10))
        self.status.pack(side="left", padx=12)
        for text, cmd in (("Settings", self.open_settings), ("New chat", self.new_chat)):
            tk.Button(top, text=text, command=cmd, bg=PANEL, fg=FG, relief="flat", padx=10, activebackground=ACCENT).pack(side="right", padx=4)

        self.log = scrolledtext.ScrolledText(self.root, bg=PANEL, fg=FG, insertbackground=FG, relief="flat",
                                             font=("Consolas", 10), wrap="word", padx=10, pady=10)
        self.log.pack(fill="both", expand=True, padx=14, pady=6)
        for tag, color in (("user", ACCENT), ("say", FG), ("tool", MUTED), ("result", "#6b7280"), ("warn", WARN), ("done", "#5fd38d"), ("err", "#ff6b6b")):
            self.log.tag_config(tag, foreground=color)
        self.log.configure(state="disabled")

        bottom = tk.Frame(self.root, bg=BG)
        bottom.pack(fill="x", padx=14, pady=(6, 14))
        self.prompt = tk.Text(bottom, height=3, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=("Segoe UI", 11), wrap="word")
        self.prompt.pack(side="left", fill="x", expand=True)
        self.prompt.bind("<Return>", self._enter)
        btns = tk.Frame(bottom, bg=BG)
        btns.pack(side="right", padx=(8, 0))
        self.run_btn = tk.Button(btns, text="Run ▶", command=self.submit, bg=ACCENT, fg="white", relief="flat", width=10, font=("Segoe UI", 10, "bold"))
        self.run_btn.pack(pady=(0, 4))
        tk.Button(btns, text="Stop ■", command=self.stop, bg=PANEL, fg=FG, relief="flat", width=10).pack()
        self.write("Tell me what to do. Examples:\n  • Find the cheapest Bengaluru → Delhi flight next Friday and take me to checkout\n"
                   "  • Build a modern two-storey house in Blender and render it at sunset\n  • Make a Python script that renames my photos by date\n"
                   "Move the mouse hard into a screen corner to emergency-stop desktop control.\n\n", "tool")

    def write(self, text: str, tag: str = "say"):
        self.log.configure(state="normal")
        self.log.insert("end", text, tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---------- actions ----------
    def _enter(self, e):
        if not (e.state & 0x1):  # Shift+Enter = newline
            self.submit()
            return "break"

    def submit(self):
        text = self.prompt.get("1.0", "end").strip()
        if not text or self.busy:
            return
        if not Config.load().is_ready():
            self.open_settings()
            return
        self.prompt.delete("1.0", "end")
        self.write(f"\nYou: {text}\n", "user")
        self.busy = True
        self.status.config(text="Working…")
        self.worker.jobs.put(("run", text))

    def stop(self):
        if self.worker.agent:
            self.worker.agent.stop()
            self.status.config(text="Stopping after this step…")

    def new_chat(self):
        if self.busy:
            return
        self.worker.jobs.put(("reset", None))
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.write("New chat.\n", "tool")

    # ---------- events from the worker thread ----------
    def post(self, kind: str, data: dict):
        self.events.put((kind, data))

    def _drain(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                self._show(kind, data)
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    def _show(self, kind: str, data: dict):
        if kind == "thinking":
            self.status.config(text=f"Working… step {data['step']}")
        elif kind == "say" and data["text"].strip():
            self.write(f"AI: {data['text'].strip()}\n", "say")
        elif kind == "tool":
            args = ", ".join(f"{k}={str(v)[:70]!r}" for k, v in data["args"].items() if k != "script")
            self.write(f"  → {data['name']}({args})\n", "tool")
        elif kind == "result":
            first = data["text"].strip().splitlines()[0][:160] if data["text"].strip() else ""
            extra = " [image]" if data.get("has_image") else ""
            self.write(f"    {first}{extra}\n", "result")
            for f in data.get("files") or []:
                self.write(f"    saved: {f}\n", "done")
        elif kind == "approval":
            self.write(f"  ⚠ needs approval: {data['reason']}\n", "warn")
        elif kind == "error":
            self.write(f"Error: {data['text']}\n", "err")
        elif kind == "done":
            self.busy = False
            self.status.config(text="Ready")
            self.write("✓ Done\n", "done")
        elif kind == "log":
            self.write(data["text"] + "\n", "tool")

    # ---------- blocking prompts called from the worker ----------
    def _ask_main(self, fn):
        box = {}
        ev = threading.Event()

        def run():
            box["v"] = fn()
            ev.set()

        self.root.after(0, run)
        ev.wait()
        return box.get("v")

    def ask_user_blocking(self, question: str) -> str:
        return self._ask_main(lambda: simpledialog.askstring("OnClick AI asks", question, parent=self.root) or "")

    def approve_blocking(self, name: str, args: dict, reason: str) -> bool:
        detail = "\n".join(f"{k}: {str(v)[:300]}" for k, v in args.items())
        return bool(self._ask_main(lambda: messagebox.askyesno("Approve this step?", f"{reason}\n\n{name}\n{detail}", parent=self.root)))

    # ---------- settings ----------
    def open_settings(self):
        cfg = Config.load()
        win = tk.Toplevel(self.root)
        win.title("Settings")
        win.configure(bg=BG)
        win.geometry("560x420")
        win.transient(self.root)

        def row(r, label, widget):
            tk.Label(win, text=label, fg=FG, bg=BG, anchor="w").grid(row=r, column=0, sticky="w", padx=12, pady=6)
            widget.grid(row=r, column=1, sticky="ew", padx=12, pady=6)

        win.columnconfigure(1, weight=1)
        provider = tk.StringVar(value=cfg.provider)
        model = tk.StringVar(value=cfg.model)
        key = tk.StringVar(value=cfg.api_key)
        base = tk.StringVar(value=cfg.base_url)
        blender = tk.StringVar(value=cfg.blender_path or cfg.resolved_blender())
        steps = tk.IntVar(value=cfg.max_steps)
        auto = tk.BooleanVar(value=cfg.auto_approve_risky)
        note = tk.Label(win, fg=MUTED, bg=BG, anchor="w", justify="left")

        combo = ttk.Combobox(win, textvariable=provider, values=list(PROVIDERS), state="readonly")
        row(0, "AI provider", combo)
        row(1, "Model (blank = default)", tk.Entry(win, textvariable=model))
        row(2, "API key", tk.Entry(win, textvariable=key, show="•"))
        row(3, "Base URL (optional)", tk.Entry(win, textvariable=base))
        row(4, "Blender path", tk.Entry(win, textvariable=blender))
        row(5, "Max steps per task", tk.Spinbox(win, from_=5, to=200, textvariable=steps))
        tk.Checkbutton(win, text="Don't ask before paying, sending, or deleting (not recommended)", variable=auto,
                       fg=FG, bg=BG, selectcolor=PANEL, activebackground=BG).grid(row=6, column=0, columnspan=2, sticky="w", padx=12)
        note.grid(row=7, column=0, columnspan=2, sticky="w", padx=12, pady=8)

        def refresh(*_):
            p = PROVIDERS[provider.get()]
            note.config(text=f"Default model: {p['model']}\nKey: {p['note']}")

        combo.bind("<<ComboboxSelected>>", refresh)
        refresh()

        def save():
            new = Config(provider=provider.get(), model=model.get().strip(), api_key=key.get().strip(), base_url=base.get().strip(),
                         blender_path=blender.get().strip(), max_steps=int(steps.get()), auto_approve_risky=auto.get(),
                         browser_channel=cfg.browser_channel, headless_browser=cfg.headless_browser, extra=cfg.extra)
            new.save()
            self.worker.jobs.put(("reset", None))
            win.destroy()
            self.write(f"Settings saved: {new.provider} / {new.resolved_model()}\n", "tool")

        tk.Button(win, text="Save", command=save, bg=ACCENT, fg="white", relief="flat", width=12).grid(row=8, column=1, sticky="e", padx=12, pady=10)

    def mainloop(self):
        self.root.mainloop()


def main():
    App().mainloop()
