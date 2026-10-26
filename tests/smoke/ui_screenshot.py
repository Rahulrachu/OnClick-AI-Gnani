"""Render the UI with a fake backend and save screenshots to docs/ (used by CI and the README)."""
import base64
import io
from pathlib import Path

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ui = Path("onclick/ui/index.html").resolve()
out = Path("docs"); out.mkdir(exist_ok=True)

img = Image.new("RGB", (640, 360), (120, 170, 230))
d = ImageDraw.Draw(img)
d.rectangle([0, 250, 640, 360], fill=(40, 110, 50))
d.rectangle([220, 150, 420, 270], fill=(235, 225, 205))
d.polygon([(200, 150), (320, 80), (440, 150)], fill=(150, 40, 30))
buf = io.BytesIO(); img.save(buf, "PNG")
render = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

STUB = """
window.pywebview = {api: {
  get_config: async () => ({ready: true, provider: 'gemini', api_key: '', model: '', blender_path: '', max_steps: 40, auto_approve_risky: false,
                             providers: {gemini: {model: 'gemini-3.8-flash', note: 'Free key at aistudio.google.com'}}}),
  submit: async () => 'ok', stop: async () => {}, new_chat: async () => {}, answer: async () => {}, open_path: async () => {}, save_config: async () => true }};
"""

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1080, "height": 760}, device_scale_factor=1)
    page.add_init_script(STUB)
    page.goto(ui.as_uri())
    page.wait_for_timeout(400)
    page.screenshot(path=str(out / "ui-home.png"))
    page.evaluate("""(render) => {
      addUser('Build a small cottage in Blender and render it');
      onEvent('thinking', {step: 1});
      onEvent('say', {text: "I'll build the cottage with a gabled roof, then render it."});
      onEvent('tool', {name: 'blender_run_script', args: {name: 'cottage', render: true, script: '...'}});
      onEvent('result', {name: 'blender_run_script', text: 'Blender OK. Script saved', files: ['C:/Users/rahul/OnClickAI/blender/cottage.blend', 'C:/Users/rahul/OnClickAI/blender/cottage.png'], image: render});
      onEvent('say', {text: 'Done. Your cottage is saved as cottage.blend, and the render is cottage.png in your OnClickAI folder.'});
      onEvent('done', {text: ''});
      addUser('Switch Windows to dark mode');
      onEvent('tool', {name: 'windows_settings', args: {action: 'theme', value: 'dark'}});
      onEvent('result', {name: 'windows_settings', text: 'Switched Windows to dark mode.'});
      document.querySelectorAll('.steps').forEach(s => s.open = true);
    }""", render)
    page.wait_for_timeout(300)
    page.screenshot(path=str(out / "ui-task.png"))
    page.evaluate("askApproval('Clicking \"Proceed to Pay\" may spend money or confirm a booking.', 'browser_click\\nref: 42')")
    page.wait_for_timeout(200)
    page.screenshot(path=str(out / "ui-approve.png"))
    b.close()
print("saved", list(out.iterdir()))
