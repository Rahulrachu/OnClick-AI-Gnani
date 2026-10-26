"""See the screen and drive mouse and keyboard, for any desktop app."""
from __future__ import annotations

import time

from . import Tool, ToolResult, params, png_bytes


def _gui():
    import pyautogui

    pyautogui.FAILSAFE = True  # slam the mouse into a screen corner to stop the agent
    pyautogui.PAUSE = 0.15
    return pyautogui


def tools(ctx):
    def screenshot() -> ToolResult:
        g = _gui()
        img = g.screenshot()
        data, scale = png_bytes(img)
        ctx.state["screen_scale"] = scale
        w, h = int(img.width / scale), int(img.height / scale)
        return ToolResult(f"Screenshot is {w}x{h}. Give click coordinates in this image's pixels.", image_png=data)

    def to_screen(x: float, y: float) -> tuple[int, int]:
        s = ctx.state.get("screen_scale", 1.0)
        return int(x * s), int(y * s)

    def mouse_click(x: float, y: float, button: str = "left", clicks: int = 1) -> ToolResult:
        sx, sy = to_screen(x, y)
        _gui().click(sx, sy, clicks=clicks, button=button)
        time.sleep(0.6)
        return ToolResult(f"Clicked {button} x{clicks} at ({x},{y}). Take a screenshot to check the result.")

    def mouse_drag(x1: float, y1: float, x2: float, y2: float) -> ToolResult:
        g = _gui()
        a, b = to_screen(x1, y1)
        c, d = to_screen(x2, y2)
        g.moveTo(a, b)
        g.dragTo(c, d, duration=0.5)
        return ToolResult("Dragged.")

    def type_text(text: str) -> ToolResult:
        g = _gui()
        if text.isascii():
            g.write(text, interval=0.02)
        else:
            import pyperclip

            pyperclip.copy(text)
            g.hotkey("ctrl", "v")
        return ToolResult(f"Typed {len(text)} characters.")

    def press_keys(keys: str) -> ToolResult:
        parts = [k.strip().lower() for k in keys.replace("+", " ").split()]
        _gui().hotkey(*parts)
        time.sleep(0.4)
        return ToolResult(f"Pressed {keys}.")

    def scroll(amount: int = -5) -> ToolResult:
        _gui().scroll(amount * 100)
        return ToolResult("Scrolled.")

    def wait(seconds: float = 2) -> ToolResult:
        time.sleep(min(float(seconds), 60))
        return ToolResult(f"Waited {seconds}s.")

    return [
        Tool("screenshot", "Capture the whole screen to see what's open. Use after opening apps or clicking.", params(), screenshot),
        Tool("mouse_click", "Click at a point in the latest screenshot's pixel coordinates.",
             params(["x", "y"], x={"type": "number"}, y={"type": "number"}, button={"type": "string", "enum": ["left", "right", "middle"]},
                    clicks={"type": "integer"}), mouse_click),
        Tool("mouse_drag", "Drag from one point to another (screenshot coordinates).",
             params(["x1", "y1", "x2", "y2"], x1={"type": "number"}, y1={"type": "number"}, x2={"type": "number"}, y2={"type": "number"}), mouse_drag),
        Tool("type_text", "Type text into whatever has keyboard focus.", params(["text"], text={"type": "string"}), type_text),
        Tool("press_keys", "Press a key or shortcut, e.g. 'enter', 'ctrl+s', 'alt+tab', 'win'.", params(["keys"], keys={"type": "string"}), press_keys),
        Tool("scroll", "Scroll the mouse wheel; negative is down.", params([], amount={"type": "integer"}), scroll),
        Tool("wait", "Wait a few seconds for something to load.", params([], seconds={"type": "number"}), wait),
    ]
