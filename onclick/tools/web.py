"""Quick web search and page reading without opening a browser."""
from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, unquote, urlparse

import requests

from . import Tool, ToolResult, params

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def tools(ctx):
    def web_search(query: str, max_results: int = 8) -> ToolResult:
        r = requests.post("https://html.duckduckgo.com/html/", data={"q": query}, headers=UA, timeout=20)
        results = []
        for m in re.finditer(r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>', r.text, re.S):
            href, title, snip = m.groups()
            if "uddg=" in href:
                href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
            results.append(f"- {html_to_text(title)}\n  {href}\n  {html_to_text(snip)}")
            if len(results) >= max_results:
                break
        return ToolResult("\n".join(results) or "No results.")

    def fetch_url(url: str) -> ToolResult:
        try:
            r = requests.get(url, headers=UA, timeout=25)
        except requests.RequestException as e:
            return ToolResult(f"Fetch failed: {e}")
        text = html_to_text(r.text) if "html" in r.headers.get("content-type", "") else r.text
        return ToolResult(f"HTTP {r.status_code}\n{text[:15000]}")

    return [
        Tool("web_search", "Search the web and get titles, links, and snippets. Fast; use before opening a browser.",
             params(["query"], query={"type": "string"}, max_results={"type": "integer"}), web_search),
        Tool("fetch_url", "Download a web page and return its text (no JavaScript). Good for articles, docs, APIs.",
             params(["url"], url={"type": "string"}), fetch_url),
    ]
