import json

from onclick.agent import Agent
from onclick.config import Config
from onclick.context import Context
from onclick.llm import AnthropicClient, LLMReply, ToolCall
from onclick.safety import click_risk, command_risk


class ScriptedClient:
    """Plays back a fixed list of replies, like a model would."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def chat(self, messages, tools):
        self.seen.append([dict(m) for m in messages])
        r = self.replies.pop(0)
        raw = {"role": "assistant", "content": r.text}
        if r.tool_calls:
            raw["tool_calls"] = [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}} for c in r.tool_calls]
        r.raw_assistant = raw
        return r


def make(tmp_path, replies, approve=lambda *a: True, **cfg):
    ctx = Context(cfg=Config(api_key="x", **cfg), workspace=tmp_path)
    events = []
    agent = Agent(ctx, on_event=lambda k, d: events.append((k, d)), approve=approve, client=ScriptedClient(replies))
    return agent, events


def test_agent_writes_file_and_finishes(tmp_path):
    agent, events = make(tmp_path, [
        LLMReply(tool_calls=[ToolCall("1", "write_file", {"path": "hello.txt", "content": "hi"})]),
        LLMReply(text="Done: wrote hello.txt"),
    ])
    out = agent.run("make a file")
    assert out == "Done: wrote hello.txt"
    assert (tmp_path / "hello.txt").read_text() == "hi"
    assert any(k == "result" for k, _ in events)


def test_shell_runs(tmp_path):
    agent, _ = make(tmp_path, [
        LLMReply(tool_calls=[ToolCall("1", "run_command", {"command": "echo onclick"})]),
        LLMReply(text="ok"),
    ])
    agent.run("echo")
    tool_msg = [m for m in agent.messages if m["role"] == "tool"][0]
    assert "onclick" in tool_msg["content"]


def test_risky_command_declined(tmp_path):
    victim = tmp_path / "keep.txt"
    victim.write_text("x")
    agent, events = make(tmp_path, [
        LLMReply(tool_calls=[ToolCall("1", "run_command", {"command": f"rm -rf {tmp_path}/keep.txt"})]),
        LLMReply(text="stopped"),
    ], approve=lambda *a: False)
    agent.run("delete")
    assert victim.exists()
    assert any(k == "approval" for k, _ in events)


def test_unknown_tool_recovers(tmp_path):
    agent, _ = make(tmp_path, [LLMReply(tool_calls=[ToolCall("1", "fly", {})]), LLMReply(text="ok")])
    assert agent.run("x") == "ok"


def test_step_limit(tmp_path):
    loop = [LLMReply(tool_calls=[ToolCall(str(i), "list_dir", {})]) for i in range(3)]
    agent, _ = make(tmp_path, loop, max_steps=3)
    assert "step limit" in agent.run("x")


def test_safety_rules():
    assert click_risk('[5] button "Proceed to Pay"')
    assert click_risk('[9] button "Book now"')
    assert click_risk('[2] a "Flights"') is None
    assert command_risk({"command": "Remove-Item C:\\x -Recurse"})
    assert command_risk({"command": "winget install Blender"}) is None


def test_anthropic_conversion():
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "screenshot", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "shot"},
        {"role": "user", "content": [{"type": "text", "text": "img"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]},
    ]
    system, out = AnthropicClient._convert(msgs)
    assert system == "sys"
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert out[2]["content"][0]["type"] == "tool_result"
    assert out[2]["content"][-1]["type"] == "image"
