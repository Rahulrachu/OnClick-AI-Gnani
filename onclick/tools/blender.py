"""Build 3D scenes and renders in Blender by writing and running bpy scripts."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from . import Tool, ToolResult, params, png_bytes

PREAMBLE = '''
import bpy, os, sys, math
OUT_DIR = r"{out_dir}"
os.makedirs(OUT_DIR, exist_ok=True)
'''

EPILOGUE = '''
# --- added by OnClick AI ---
try:
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT_DIR, "{name}.blend"))
    print("ONCLICK_SAVED", os.path.join(OUT_DIR, "{name}.blend"))
except Exception as e:
    print("ONCLICK_SAVE_FAILED", e)
if {render}:
    scn = bpy.context.scene
    if scn.camera is None:
        print("ONCLICK_NO_CAMERA")
    else:
        scn.render.filepath = os.path.join(OUT_DIR, "{name}.png")
        scn.render.image_settings.file_format = "PNG"
        bpy.ops.render.render(write_still=True)
        print("ONCLICK_RENDERED", scn.render.filepath)
'''


def tools(ctx):
    def blender_exe() -> str | None:
        return ctx.cfg.resolved_blender() or None

    def blender_run_script(script: str, name: str = "", render: bool = True, timeout: int = 900) -> ToolResult:
        exe = blender_exe()
        if not exe:
            return ToolResult("Blender not found. Install it (run_command: winget install -e --id BlenderFoundation.Blender) "
                              "or set its path in Settings, then try again.")
        out_dir = ctx.workspace / "blender"
        out_dir.mkdir(parents=True, exist_ok=True)
        name = "".join(c for c in (name or f"scene_{int(time.time())}") if c.isalnum() or c in "-_") or "scene"
        script_path = out_dir / f"{name}.py"
        script_path.write_text(PREAMBLE.format(out_dir=out_dir) + "\n" + script + "\n" +
                               EPILOGUE.format(name=name, render=bool(render)), encoding="utf-8")
        try:
            p = subprocess.run([exe, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(script_path)],
                               capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace",
                               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        except subprocess.TimeoutExpired:
            return ToolResult(f"Blender timed out after {timeout}s. Lower samples/resolution or simplify the scene.")
        log = (p.stdout or "") + (p.stderr or "")
        errors = [l for l in log.splitlines() if "Error" in l or "Traceback" in l or l.startswith("  File")]
        tail = "\n".join(log.splitlines()[-40:])
        files = [str(out_dir / f"{name}.blend")]
        image = None
        png = out_dir / f"{name}.png"
        if render and png.exists() and png.stat().st_mtime > time.time() - timeout - 5:
            from PIL import Image

            image, _ = png_bytes(Image.open(png), max_width=1024)
            files.append(str(png))
        status = "OK" if p.returncode == 0 else f"FAILED (exit {p.returncode})"
        msg = f"Blender {status}. Script: {script_path}\nFiles: {files}\n"
        if errors:
            msg += "Errors:\n" + "\n".join(errors[-20:]) + "\n"
        msg += "Log tail:\n" + tail
        if image:
            msg += "\nThe render is attached; check it matches the request and fix the script if not."
        return ToolResult(msg, image_png=image, files=files)

    def blender_open(path: str) -> ToolResult:
        exe = blender_exe()
        if not exe:
            return ToolResult("Blender not found.")
        p = Path(path)
        if not p.is_absolute():
            p = ctx.workspace / "blender" / p
        subprocess.Popen([exe, str(p)])
        return ToolResult(f"Opened {p} in Blender.")

    return [
        Tool("blender_run_script",
             "Run a Blender Python (bpy) script headlessly to build a 3D scene. The script runs in a fresh default scene; "
             "delete the default cube first if unwanted. OUT_DIR is predefined. The .blend is saved automatically and, if render=true "
             "and the scene has a camera, a PNG render is made and shown to you. Build with real geometry (bmesh/primitives/modifiers), "
             "materials (Principled BSDF), lights, and a camera aimed at the subject. Prefer BLENDER_EEVEE_NEXT (or 'BLENDER_EEVEE' on "
             "older versions) for speed; use CYCLES with low samples for realism. Iterate: inspect the render and rerun with fixes.",
             params(["script"], script={"type": "string"}, name={"type": "string", "description": "file name, no extension"},
                    render={"type": "boolean"}, timeout={"type": "integer"}), blender_run_script),
        Tool("blender_open", "Open a .blend file in the Blender window so the user can see it.",
             params(["path"], path={"type": "string"}), blender_open),
    ]
