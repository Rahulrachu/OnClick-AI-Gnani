"""Gemini 3 thought signatures survive the round trip, and long tasks keep the context small."""
import json

from onclick.agent import Agent
from onclick.config import Config
from onclick.context import Context
from onclick.llm import LLMReply, OpenAICompatClient, ToolCall
from onclick.tools import Tool, ToolResult, params


class FakeResponse:
    def __init__(self, data):
        self.status_code = 200
        self._data = data
        self.text = json.dumps(data)

    def json(self):
        return self._data


def gemini_tool_turn(call_id, name, args, signature):
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{
        "id": call_id, "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
        "extra_content": {"google": {"thought_signature": signature}},
    }]}}]}


def test_gemini_thought_signature_is_sent_back(tmp_path, monkeypatch):
    responses = [
        gemini_tool_turn("fc-1", "write_file", {"path": "a.txt", "content": "one"}, "SIG_ONE"),
        gemini_tool_turn("fc-2", "read_file", {"path": "a.txt"}, "SIG_TWO"),
        {"choices": [{"message": {"role": "assistant", "content": "All done."}}]},
    ]
    bodies = []

    def fake_post(url, headers=None, json=None, timeout=None):
        bodies.append(__import__("json").loads(__import__("json").dumps(json)))
        # A real Gemini 3 endpoint answers 400 when a signed call comes back without its signature.
        for m in json["messages"]:
            for tc in m.get("tool_calls") or []:
                assert tc["extra_content"]["google"]["thought_signature"].startswith("SIG_")
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr("onclick.llm.requests.post", fake_post)
    cfg = Config(provider="gemini", api_key="k")
    ctx = Context(cfg=cfg, workspace=tmp_path)
    agent = Agent(ctx, client=OpenAICompatClient(cfg), approve=lambda *a: True)
    assert agent.run("write then read a file") == "All done."
    assert (tmp_path / "a.txt").read_text() == "one"
    sent = [tc for m in bodies[-1]["messages"] for tc in m.get("tool_calls") or []]
    assert [tc["extra_content"]["google"]["thought_signature"] for tc in sent] == ["SIG_ONE", "SIG_TWO"]
    assert [tc["id"] for tc in sent] == ["fc-1", "fc-2"]


def test_object_arguments_and_missing_ids(monkeypatch):
    data = {"choices": [{"message": {"content": "", "tool_calls": [
        {"function": {"name": "list_dir", "arguments": {"path": "."}}}]}}]}
    monkeypatch.setattr("onclick.llm.requests.post", lambda *a, **k: FakeResponse(data))
    reply = OpenAICompatClient(Config(provider="ollama")).chat([{"role": "user", "content": "x"}], [])
    assert reply.tool_calls[0].arguments == {"path": "."}
    tc = reply.raw_assistant["tool_calls"][0]
    assert tc["id"] == reply.tool_calls[0].id == "call_0"
    assert json.loads(tc["function"]["arguments"]) == {"path": "."}


class Scripted:
    def __init__(self, replies):
        self.replies = list(replies)
        self.sizes = []

    def chat(self, messages, tools):
        self.sizes.append(sum(len(json.dumps(m)) for m in messages))
        r = self.replies.pop(0)
        r.raw_assistant = {"role": "assistant", "content": r.text}
        if r.tool_calls:
            r.raw_assistant["tool_calls"] = [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}} for c in r.tool_calls]
        return r


def test_long_browser_task_keeps_context_bounded(tmp_path):
    pages = iter(range(100))

    def fake_snapshot(**_):
        n = next(pages)
        return ToolResult(f"Clicked\nTitle: Page {n}\nURL: https://x/{n}\n\n" + ("element line\n" * 600))

    steps = 30
    replies = [LLMReply(tool_calls=[ToolCall(str(i), "browser_click", {"ref": "1"})]) for i in range(steps)]
    replies += [LLMReply(tool_calls=[ToolCall("r", "run_command", {"command": "echo " + "y" * 3000})])]
    replies += [LLMReply(text="done")]
    client = Scripted(replies)
    ctx = Context(cfg=Config(api_key="x", max_steps=60), workspace=tmp_path)
    agent = Agent(ctx, client=client, approve=lambda *a: True)
    agent.registry.tools["browser_click"] = Tool("browser_click", "click", params(ref="ref"), fake_snapshot)
    assert agent.run("click around") == "done"

    tools = [m for m in agent.messages if m["role"] == "tool"]
    snaps = tools[:steps]
    assert len(snaps[-1]["content"]) > 7000           # newest page stays whole
    assert all(len(m["content"]) < 500 for m in snaps[:-1])  # older pages shrink
    assert "Title: Page 0" in snaps[0]["content"]      # but keep what/where
    assert len(tools[-1]["content"]) > 3000            # latest non-browser output stays whole
    # Context stops growing with the number of pages visited.
    # Without trimming 30 pages would be ~240k chars; each extra page now costs well under 1k.
    assert client.sizes[-1] < 45000
    assert (client.sizes[30] - client.sizes[10]) / 20 < 1000
