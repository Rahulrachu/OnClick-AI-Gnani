"""Rules for what the agent must ask before doing."""
from __future__ import annotations

import re

MONEY_WORDS = re.compile(
    r"\b(pay|payment|purchase|buy now|place (your )?order|confirm (booking|order|payment)|book now|complete booking|"
    r"checkout|check out|proceed to pay|subscribe|donate|transfer|send money|submit order)\b",
    re.I,
)
SEND_WORDS = re.compile(r"\b(send|post|publish|tweet|reply all|submit application)\b", re.I)

DESTRUCTIVE_CMD = re.compile(
    r"(\brm\s+-[a-z]*r|\brmdir\b|\bdel\b|\berase\b|remove-item|\bformat\b|diskpart|\bshutdown\b|\breg\s+delete|"
    r"stop-computer|restart-computer|clear-disk|\bmkfs|\bdd\s+if=|git\s+push\s+.*--force|git\s+reset\s+--hard|"
    r"set-executionpolicy|bcdedit|cipher\s+/w|takeown|icacls)",
    re.I,
)


def command_risk(args: dict) -> str | None:
    cmd = str(args.get("command", ""))
    if DESTRUCTIVE_CMD.search(cmd):
        return "This command can delete or change system data."
    return None


def click_risk(label: str) -> str | None:
    if MONEY_WORDS.search(label or ""):
        return f"Clicking \"{label.strip()[:60]}\" may spend money or confirm a booking."
    if SEND_WORDS.search(label or ""):
        return f"Clicking \"{label.strip()[:60]}\" may send or publish something in your name."
    return None
