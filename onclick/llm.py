"""LLM clients with tool calling.

Internally every conversation is kept in the OpenAI chat-completions format:
  {"role": "system"|"user"|"assistant"|"tool", "content": str|list, "tool_calls": [...], "tool_call_id": str}
Images ride in user messages as {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}.
The Anthropic client converts to and from its own format.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import requests

from .config import Config


class LLMError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_assistant: dict = field(default_factory=dict)  # message to append to history


def _post(url: str, headers: dict, body: dict, timeout: int = 180) -> dict:
    last = None
    for attempt in range(4):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=timeout)
        except requests.RequestException as e:
            last = str(e)
            time.sleep(2 ** attempt)
            continue
        if r.status_code in (429, 500, 502, 503, 529):
            last = f"HTTP {r.status_code}: {r.text[:300]}"
            time.sleep(2 ** attempt * 2)
            continue
        if r.status_code >= 400:
            raise LLMError(f"HTTP {r.status_code}: {r.text[:800]}")
        return r.json()
    raise LLMError(f"Model request failed after retries: {last}")


class OpenAICompatClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.url = cfg.resolved_base_url().rstrip("/") + "/chat/completions"
        self.model = cfg.resolved_model()
        self.key = cfg.resolved_key()

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        body = {
            "model": self.model,
            "messages": messages,
            "tools": [{"type": "function", "function": t} for t in tools],
            "tool_choice": "auto",
        }
        data = _post(self.url, headers, body)
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError):
            raise LLMError(f"Unexpected response: {json.dumps(data)[:500]}")
        calls = []
        kept = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            # Keep the provider's dict verbatim: Gemini 3 puts a thought signature in
            # tc["extra_content"]["google"]["thought_signature"] and rejects the next
            # request (HTTP 400) if it is not sent back exactly as received.
            tc = json.loads(json.dumps(tc))
            fn = tc.setdefault("function", {})
            tc.setdefault("type", "function")
            if not tc.get("id"):
                tc["id"] = f"call_{i}"
            raw_args = fn.get("arguments")
            if isinstance(raw_args, dict):  # some servers (ollama) send an object
                args = raw_args
                fn["arguments"] = json.dumps(raw_args)
            else:
                try:
                    args = json.loads(raw_args or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": raw_args}
                if not isinstance(args, dict):
                    args = {"_raw": raw_args}
                fn["arguments"] = raw_args or "{}"
            calls.append(ToolCall(id=tc["id"], name=fn.get("name", ""), arguments=args))
            kept.append(tc)
        raw = {"role": "assistant", "content": msg.get("content") or ""}
        if kept:
            raw["tool_calls"] = kept
        # Gemini can also sign a plain text turn; pass any message-level extras back too.
        if msg.get("extra_content"):
            raw["extra_content"] = msg["extra_content"]
        return LLMReply(text=msg.get("content") or "", tool_calls=calls, raw_assistant=raw)


class AnthropicClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.url = cfg.resolved_base_url().rstrip("/") + "/messages"
        self.model = cfg.resolved_model()
        self.key = cfg.resolved_key()

    @staticmethod
    def _convert(messages: list[dict]) -> tuple[str, list[dict]]:
        system = ""
        out: list[dict] = []

        def push(role: str, blocks: list[dict]):
            if out and out[-1]["role"] == role:
                out[-1]["content"].extend(blocks)
            else:
                out.append({"role": role, "content": list(blocks)})

        for m in messages:
            role = m["role"]
            if role == "system":
                system += (m["content"] if isinstance(m["content"], str) else "") + "\n"
            elif role == "user":
                blocks = []
                content = m["content"]
                if isinstance(content, str):
                    blocks.append({"type": "text", "text": content})
                else:
                    for part in content:
                        if part.get("type") == "text":
                            blocks.append({"type": "text", "text": part["text"]})
                        elif part.get("type") == "image_url":
                            url = part["image_url"]["url"]
                            media, b64 = url.split(";base64,", 1)
                            blocks.append({"type": "image", "source": {"type": "base64", "media_type": media.replace("data:", ""), "data": b64}})
                push("user", blocks)
            elif role == "assistant":
                blocks = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls") or []:
                    blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"],
                                   "input": json.loads(tc["function"]["arguments"] or "{}")})
                push("assistant", blocks or [{"type": "text", "text": "."}])
            elif role == "tool":
                push("user", [{"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}])
        return system.strip(), out

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        system, msgs = self._convert(messages)
        body = {
            "model": self.model,
            "max_tokens": 4096,
            "system": system,
            "messages": msgs,
            "tools": [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools],
        }
        headers = {"x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        data = _post(self.url, headers, body)
        text, calls = "", []
        for block in data.get("content", []):
            if block["type"] == "text":
                text += block["text"]
            elif block["type"] == "tool_use":
                calls.append(ToolCall(id=block["id"], name=block["name"], arguments=block.get("input") or {}))
        raw = {"role": "assistant", "content": text}
        if calls:
            raw["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                for c in calls
            ]
        return LLMReply(text=text, tool_calls=calls, raw_assistant=raw)


def make_client(cfg: Config):
    if cfg.provider == "anthropic":
        return AnthropicClient(cfg)
    return OpenAICompatClient(cfg)
