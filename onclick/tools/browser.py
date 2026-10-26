"""A real, visible browser the agent drives with Playwright.

Uses the Microsoft Edge already installed on Windows (or Chrome), with a persistent
profile, so logins the user makes once are remembered for later tasks.
"""
from __future__ import annotations

import io

from ..config import app_dir
from ..safety import click_risk
from . import Tool, ToolResult, params, png_bytes

SNAPSHOT_JS = r"""
() => {
  const sel = 'a,button,input,select,textarea,[role=button],[role=link],[role=tab],[role=option],[role=menuitem],[role=checkbox],[role=radio],[role=combobox],[contenteditable=true],[onclick],label,summary';
  const out = [];
  let i = 0;
  document.querySelectorAll('[data-oc-ref]').forEach(e => e.removeAttribute('data-oc-ref'));
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || st.visibility === 'hidden' || st.display === 'none') continue;
    if (r.bottom < 0 || r.top > innerHeight * 2.5) continue;
    i += 1;
    el.setAttribute('data-oc-ref', String(i));
    const tag = el.tagName.toLowerCase();
    const label = (el.getAttribute('aria-label') || el.innerText || el.value || el.placeholder || el.title || el.name || el.alt || '').replace(/\s+/g,' ').trim().slice(0, 80);
    const type = el.type ? `:${el.type}` : '';
    out.push(`[${i}] ${tag}${type} "${label}"`);
    if (i >= 250) break;
  }
  const text = document.body ? document.body.innerText.replace(/\n{3,}/g, '\n\n').slice(0, 8000) : '';
  return {title: document.title, url: location.href, elements: out.join('\n'), text};
}
"""


class BrowserSession:
    def __init__(self, cfg):
        from playwright.sync_api import sync_playwright

        self.pw = sync_playwright().start()
        profile = app_dir() / "browser-profile"
        kwargs = dict(headless=cfg.headless_browser, viewport={"width": 1366, "height": 860}, accept_downloads=True)
        try:
            self.context = self.pw.chromium.launch_persistent_context(str(profile), channel=cfg.browser_channel, **kwargs)
        except Exception:
            try:
                self.context = self.pw.chromium.launch_persistent_context(str(profile), channel="chrome", **kwargs)
            except Exception:
                self.context = self.pw.chromium.launch_persistent_context(str(profile), **kwargs)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.context.on("page", self._on_new_page)

    def _on_new_page(self, page):
        self.page = page

    def close(self):
        try:
            self.context.close()
        finally:
            self.pw.stop()


def tools(ctx):
    def session() -> BrowserSession:
        s = ctx.state.get("browser")
        if s is None:
            s = BrowserSession(ctx.cfg)
            ctx.state["browser"] = s
        return s

    def snapshot(note: str = "") -> ToolResult:
        page = session().page
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        snap = page.evaluate(SNAPSHOT_JS)
        ctx.state["browser_labels"] = {
            line.split("]", 1)[0][1:]: line for line in snap["elements"].splitlines()
        }
        return ToolResult(
            f"{note}\nTitle: {snap['title']}\nURL: {snap['url']}\n\nInteractive elements (use the number as ref):\n"
            f"{snap['elements']}\n\nPage text:\n{snap['text']}"
        )

    def locator(ref: str):
        return session().page.locator(f'[data-oc-ref="{ref}"]').first

    def browser_open(url: str) -> ToolResult:
        if "://" not in url:
            url = "https://" + url
        session().page.goto(url, wait_until="domcontentloaded", timeout=45000)
        return snapshot(f"Opened {url}")

    def browser_click(ref: str) -> ToolResult:
        loc = locator(str(ref))
        loc.scroll_into_view_if_needed(timeout=5000)
        loc.click(timeout=8000)
        session().page.wait_for_timeout(1200)
        return snapshot(f"Clicked [{ref}]")

    def browser_type(ref: str, text: str, submit: bool = False) -> ToolResult:
        loc = locator(str(ref))
        loc.click(timeout=8000)
        try:
            loc.fill(text, timeout=5000)
        except Exception:
            session().page.keyboard.type(text, delay=30)
        if submit:
            session().page.keyboard.press("Enter")
        session().page.wait_for_timeout(1200)
        return snapshot(f"Typed into [{ref}]")

    def browser_select(ref: str, option: str) -> ToolResult:
        locator(str(ref)).select_option(label=option, timeout=8000)
        return snapshot(f"Selected {option}")

    def browser_press(key: str) -> ToolResult:
        session().page.keyboard.press(key)
        session().page.wait_for_timeout(800)
        return snapshot(f"Pressed {key}")

    def browser_scroll(direction: str = "down") -> ToolResult:
        session().page.mouse.wheel(0, 700 if direction == "down" else -700)
        session().page.wait_for_timeout(600)
        return snapshot(f"Scrolled {direction}")

    def browser_back() -> ToolResult:
        session().page.go_back()
        return snapshot("Went back")

    def browser_screenshot() -> ToolResult:
        from PIL import Image

        raw = session().page.screenshot()
        data, _ = png_bytes(Image.open(io.BytesIO(raw)))
        return ToolResult("Screenshot of the current browser tab.", image_png=data)

    def click_reason(args: dict):
        label = ctx.state.get("browser_labels", {}).get(str(args.get("ref")), "")
        return click_risk(label)

    return [
        Tool("browser_open", "Open a URL in the visible browser. Returns the page text and numbered interactive elements.",
             params(["url"], url={"type": "string"}), browser_open),
        Tool("browser_snapshot", "Re-read the current browser page (text + numbered elements).", params(), lambda: snapshot()),
        Tool("browser_click", "Click the element with this ref number from the latest snapshot.",
             params(["ref"], ref={"type": "string"}), browser_click, risk=click_reason),
        Tool("browser_type", "Type text into the input with this ref. Set submit=true to press Enter after.",
             params(["ref", "text"], ref={"type": "string"}, text={"type": "string"}, submit={"type": "boolean"}), browser_type),
        Tool("browser_select", "Choose an option in a <select> dropdown by its visible label.",
             params(["ref", "option"], ref={"type": "string"}, option={"type": "string"}), browser_select),
        Tool("browser_press", "Press a key in the browser, e.g. Enter, Escape, Tab, ArrowDown.",
             params(["key"], key={"type": "string"}), browser_press),
        Tool("browser_scroll", "Scroll the page up or down.", params([], direction={"type": "string", "enum": ["up", "down"]}), browser_scroll),
        Tool("browser_back", "Go back one page.", params(), browser_back),
        Tool("browser_screenshot", "See the browser tab as an image (for date pickers, seat maps, captchas, layouts).", params(), browser_screenshot),
    ]
