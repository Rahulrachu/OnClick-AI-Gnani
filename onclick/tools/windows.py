"""Reliable one-call Windows personalization, instead of clicking through Settings."""
from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path

from . import Tool, ToolResult, params

IS_WIN = sys.platform == "win32"
PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
ADVANCED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"

# Known-good packages for a macOS-style desktop (winget ids).
MAC_LOOK_APPS = {
    "dock": "WinStep.Nexus",
    "transparent_taskbar": "CharlesMilette.TranslucentTB",
    "quick_look": "QL-Win.QuickLook",
    "spotlight_search": "Microsoft.PowerToys",
    "mac_cursor_and_ui_suite": "Seelen.SeelenUI",
}


def _set_dword(path: str, name: str, value: int) -> None:
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, value)


def _broadcast() -> None:
    # Tell open windows the theme changed so it applies without signing out.
    HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x1A, 0x2
    ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "ImmersiveColorSet", SMTO_ABORTIFHUNG, 3000, None)


def tools(ctx):
    def windows_settings(action: str, value: str = "") -> ToolResult:
        if not IS_WIN:
            return ToolResult("windows_settings only works on Windows.")
        a = action.lower()
        v = value.lower()
        if a == "theme":
            dark = v != "light"
            _set_dword(PERSONALIZE, "AppsUseLightTheme", 0 if dark else 1)
            _set_dword(PERSONALIZE, "SystemUsesLightTheme", 0 if dark else 1)
            _broadcast()
            return ToolResult(f"Switched Windows to {'dark' if dark else 'light'} mode.")
        if a == "transparency":
            _set_dword(PERSONALIZE, "EnableTransparency", 0 if v in ("off", "false", "0") else 1)
            _broadcast()
            return ToolResult(f"Transparency {'off' if v in ('off', 'false', '0') else 'on'}.")
        if a == "taskbar_alignment":
            _set_dword(ADVANCED, "TaskbarAl", 0 if v == "left" else 1)
            return ToolResult(f"Taskbar aligned {'left' if v == 'left' else 'center'}.")
        if a == "taskbar_autohide":
            on = v not in ("off", "false", "0")
            ps = ("$p='HKCU:SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StuckRects3';$v=(Get-ItemProperty -Path $p).Settings;"
                  f"$v[8]={'3' if on else '2'};Set-ItemProperty -Path $p -Name Settings -Value $v;Stop-Process -Name explorer -Force")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
            return ToolResult(f"Taskbar auto-hide {'on' if on else 'off'}.")
        if a == "wallpaper":
            path = Path(value).expanduser()
            if not path.exists():
                return ToolResult(f"No image at {path}. Download one first (e.g. with run_command Invoke-WebRequest).")
            ctypes.windll.user32.SystemParametersInfoW(20, 0, str(path.resolve()), 3)
            return ToolResult(f"Wallpaper set to {path}.")
        if a == "accent_color":
            hexv = value.lstrip("#")
            if len(hexv) != 6:
                return ToolResult("accent_color needs a hex value like #0A84FF.")
            r, g, b = int(hexv[0:2], 16), int(hexv[2:4], 16), int(hexv[4:6], 16)
            abgr = (0xFF << 24) | (b << 16) | (g << 8) | r
            _set_dword(r"Software\Microsoft\Windows\DWM", "AccentColor", abgr)
            _set_dword(r"Software\Microsoft\Windows\DWM", "ColorPrevalence", 1)
            _broadcast()
            return ToolResult(f"Accent color set to #{hexv}.")
        if a == "install_mac_look":
            ids = [MAC_LOOK_APPS[k] for k in (v.split(",") if v else MAC_LOOK_APPS) if k.strip() in MAC_LOOK_APPS]
            out = []
            for pkg in ids:
                p = subprocess.run(["winget", "install", "-e", "--id", pkg, "--accept-source-agreements", "--accept-package-agreements", "--silent"],
                                   capture_output=True, text=True, errors="replace")
                out.append(f"{pkg}: {'installed' if p.returncode == 0 else 'failed ' + p.stdout[-200:]}")
            return ToolResult("\n".join(out) + "\nOpen each app once to finish its setup.")
        return ToolResult("Unknown action.")

    return [
        Tool("windows_settings",
             "Change Windows look and feel reliably in one call. actions: theme (dark|light), transparency (on|off), "
             "taskbar_alignment (center|left), taskbar_autohide (on|off), wallpaper (image file path), accent_color (#RRGGBB), "
             f"install_mac_look (comma list of {', '.join(MAC_LOOK_APPS)}; blank = all). For a macOS look: dark theme, transparency on, "
             "centered auto-hide taskbar, accent #0A84FF, a macOS-style wallpaper, then install_mac_look.",
             params(["action"], action={"type": "string", "enum": ["theme", "transparency", "taskbar_alignment", "taskbar_autohide",
                                                                   "wallpaper", "accent_color", "install_mac_look"]},
                    value={"type": "string"}), windows_settings,
             risk=lambda a: "Installs desktop apps with winget." if a.get("action") == "install_mac_look" else None),
    ]
