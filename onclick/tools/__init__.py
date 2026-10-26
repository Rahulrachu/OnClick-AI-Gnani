"""Tool registry. Every tool the agent can call is declared here."""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolResult:
    text: str
    image_png: bytes | None = None  # shown to the model as an image when set
    files: list[str] = field(default_factory=list)

    def image_data_url(self) -> str | None:
        if not self.image_png:
            return None
        return "data:image/png;base64," + base64.b64encode(self.image_png).decode()


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable[..., ToolResult]
    # "safe" runs freely; "confirm" always asks; a callable decides per call and returns a reason or None.
    risk: str | Callable[[dict], str | None] = "safe"

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}

    def risk_reason(self, args: dict) -> str | None:
        if self.risk == "safe":
            return None
        if self.risk == "confirm":
            return f"{self.name} needs your OK"
        return self.risk(args)


def params(required: list[str] | None = None, **props: Any) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


def png_bytes(img, max_width: int = 1280) -> tuple[bytes, float]:
    """Encode a PIL image as PNG, downscaled to max_width. Returns (bytes, scale) where scale = original/shown."""
    scale = 1.0
    if img.width > max_width:
        scale = img.width / max_width
        img = img.resize((max_width, int(img.height / scale)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue(), scale


class Registry:
    def __init__(self) -> None:
        self.tools: dict[str, Tool] = {}

    def add(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self.tools.values()]

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)


def build_registry(ctx) -> Registry:
    from . import blender, browser, desktop, system, web, windows

    reg = Registry()
    for module in (system, web, browser, desktop, blender, windows):
        for tool in module.tools(ctx):
            reg.add(tool)
    return reg
