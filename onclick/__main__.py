"""Entry point: `OnClickAI.exe` opens the window; `OnClickAI.exe --cli "prompt"` runs in the terminal."""
from __future__ import annotations

import argparse
import sys


def run_cli(prompt: str | None) -> int:
    from .agent import Agent
    from .config import Config
    from .context import Context

    cfg = Config.load()
    if not cfg.is_ready():
        print(f"No API key set. Edit {Config.path()} or open the app's Settings.")
        return 1

    def on_event(kind, data):
        if kind == "say" and data["text"].strip():
            print(f"\nAI: {data['text'].strip()}")
        elif kind == "tool":
            print(f"  -> {data['name']} {str({k: v for k, v in data['args'].items() if k != 'script'})[:160]}")
        elif kind == "result":
            print(f"     {data['text'].strip().splitlines()[0][:160] if data['text'].strip() else ''}")
        elif kind == "error":
            print(f"Error: {data['text']}")

    def approve(name, args, reason):
        return input(f"\n[!] {reason}\n    Allow {name}? [y/N] ").strip().lower() in ("y", "yes")

    ctx = Context(cfg=cfg, ask_user=lambda q: input(f"\n[?] {q}\n> "))
    agent = Agent(ctx, on_event=on_event, approve=approve)
    try:
        if prompt:
            agent.run(prompt)
        else:
            while True:
                text = input("\nYou> ").strip()
                if text in ("exit", "quit"):
                    break
                if text:
                    agent.run(text)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        ctx.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="OnClickAI")
    ap.add_argument("--cli", action="store_true", help="run in the terminal instead of the window")
    ap.add_argument("prompt", nargs="*", help="task to run (CLI mode)")
    args = ap.parse_args()
    if args.cli or args.prompt:
        return run_cli(" ".join(args.prompt) or None)
    try:
        from .webapp import main as web_main

        web_main()
    except Exception:  # no WebView2 runtime: fall back to the classic window
        from .gui import main as gui_main

        gui_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
