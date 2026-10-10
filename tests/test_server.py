import asyncio
import threading

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from factory import server
from factory.llm import LLMProvider, LLMResponse, MockProvider, ToolCall

CHAT_SPEC = """name: demo-agent
goal: "Demo agent for the tests"
mode: conversational
tools:
  - fs.list
permissions:
  fs_read: ["./sandbox"]
"""

TASK_SPEC = """name: task-agent
goal: "A task agent for the tests"
mode: task
"""


def say(text):
    return LLMResponse(content=text)


def use(name, **args):
    return LLMResponse(tool_calls=[ToolCall(name, args)])


@pytest.fixture
def world(tmp_path, monkeypatch):
    (tmp_path / "specs").mkdir()
    (tmp_path / "sandbox").mkdir()
    (tmp_path / "sandbox" / "a.txt").write_text("hello")
    (tmp_path / "specs" / "demo.yaml").write_text(CHAT_SPEC)
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server, "SPECS_DIR", tmp_path / "specs")
    monkeypatch.setattr(server, "STATIC_DIR", tmp_path / "static")
    monkeypatch.setattr(server, "ollama_models", lambda: ["qwen3:8b"])
    monkeypatch.setattr(server, "MODEL_LOCK", asyncio.Lock())
    return tmp_path


@pytest.fixture
def client(world):
    return TestClient(server.app, base_url="http://127.0.0.1")


def script(monkeypatch, *responses):
    """Every new session gets a fresh provider with these scripted replies."""
    monkeypatch.setattr(server, "make_provider", lambda cfg: MockProvider(list(responses)))


def talk(ws, text):
    """Send one message and collect events up to and including the reply or an error."""
    ws.send_json({"type": "message", "text": text})
    events = []
    while True:
        msg = ws.receive_json()
        events.append(msg)
        if msg["event"] in ("reply", "error"):
            return events


# ---------- http ----------


def test_agent_list_has_the_summary_fields(client):
    data = client.get("/api/agents").json()
    assert data["problems"] == []
    agent = data["agents"][0]
    assert agent["name"] == "demo-agent"
    assert agent["mode"] == "conversational"
    assert agent["tools"] == ["fs.list"]
    assert agent["runnable"] is True
    assert agent["model_installed"] is True
    assert agent["has_notes"] is False
    assert agent["permissions"]["fs_read"] == ["./sandbox"]


def test_missing_model_and_unbuilt_tools_are_flagged(client, world, monkeypatch):
    monkeypatch.delitem(server.IMPLEMENTED, "code.run")  # pretend this tool is not built
    monkeypatch.setattr(server, "ollama_models", lambda: ["llama3.2:latest"])
    (world / "specs" / "code.yaml").write_text(
        'name: code-agent\ngoal: "Needs a tool that does not exist yet"\n'
        "tools: [code.run]\npermissions: {shell: true}\n"
    )
    agents = {a["name"]: a for a in client.get("/api/agents").json()["agents"]}
    assert agents["demo-agent"]["model_installed"] is False
    assert agents["code-agent"]["runnable"] is False
    assert agents["code-agent"]["missing_tools"] == ["code.run"]


def test_unreachable_ollama_means_unknown_model_state(client, monkeypatch):
    monkeypatch.setattr(server, "ollama_models", lambda: None)
    assert client.get("/api/agents").json()["agents"][0]["model_installed"] is None
    assert client.get("/api/config").json()["ollama_up"] is False


def test_broken_and_duplicate_specs_are_reported_not_fatal(client, world):
    (world / "specs" / "bad.yaml").write_text("name: Bad Name\ngoal: short\n")
    (world / "specs" / "garbage.yaml").write_text("- just\n- a list\n")
    (world / "specs" / "zcopy.yaml").write_text(CHAT_SPEC)
    data = client.get("/api/agents").json()
    assert [a["name"] for a in data["agents"]] == ["demo-agent"]
    files = {p["file"]: p["error"] for p in data["problems"]}
    assert set(files) == {"bad.yaml", "garbage.yaml", "zcopy.yaml"}
    assert "already defines" in files["zcopy.yaml"]


def test_config_reports_models(client):
    data = client.get("/api/config").json()
    assert data["ollama_up"] is True
    assert data["models"] == ["qwen3:8b"]


def test_notes_endpoint(client, world):
    assert client.get("/api/agents/demo-agent/notes").json()["notes"] == ""
    folder = world / "data" / "demo-agent"
    folder.mkdir(parents=True)
    (folder / "notes.md").write_text("Project: Atlas\n")
    assert client.get("/api/agents/demo-agent/notes").json()["notes"] == "Project: Atlas\n"
    assert client.get("/api/agents").json()["agents"][0]["has_notes"] is True


@pytest.mark.parametrize("name", ["nobody-here", "Bad_Name", "..%2F..%2Fetc"])
def test_notes_for_unknown_agent_is_404(client, name):
    assert client.get(f"/api/agents/{name}/notes").status_code == 404


def test_index_page_is_served_without_caching(client, world):
    (world / "static").mkdir()
    (world / "static" / "index.html").write_text("<h1>AgentFactory</h1>")
    r = client.get("/")
    assert r.status_code == 200 and "AgentFactory" in r.text
    assert r.headers["cache-control"] == "no-cache"


def test_foreign_host_header_is_rejected(client):
    assert client.get("/api/agents", headers={"host": "evil.example"}).status_code == 400


# ---------- websocket ----------


def test_chat_round_trip_streams_trace_then_reply(client, monkeypatch):
    script(monkeypatch, use("fs_list", path="./sandbox"), say("One file: a.txt."))
    with client.websocket_connect("ws://127.0.0.1/ws/chat/demo-agent") as ws:
        ready = ws.receive_json()
        assert ready["event"] == "ready"
        assert ready["payload"] == {"agent": "demo-agent", "mode": "conversational"}
        events = talk(ws, "What is in my sandbox?")
    names = [e["event"] for e in events]
    assert names[0] == "started"
    assert names[-1] == "reply"
    assert names.count("trace") >= 2
    tool = [e["payload"] for e in events if e["event"] == "trace" and e["payload"]["event"] == "tool"]
    assert tool[0]["name"] == "fs_list" and "a.txt" in tool[0]["output"]
    reply = events[-1]["payload"]
    assert reply["text"] == "One file: a.txt."
    assert reply["ok"] is True and reply["steps"] == 2


def test_chat_agent_keeps_one_session_across_messages(client, monkeypatch):
    script(monkeypatch, say("first"), say("second"))
    with client.websocket_connect("ws://127.0.0.1/ws/chat/demo-agent") as ws:
        ws.receive_json()
        assert talk(ws, "one")[-1]["payload"]["text"] == "first"
        assert talk(ws, "two")[-1]["payload"]["text"] == "second"


def test_task_agent_starts_fresh_for_every_message(client, world, monkeypatch):
    (world / "specs" / "task.yaml").write_text(TASK_SPEC)
    script(monkeypatch, say("done"))  # only one scripted reply per session
    with client.websocket_connect("ws://127.0.0.1/ws/chat/task-agent") as ws:
        assert ws.receive_json()["payload"]["mode"] == "task"
        assert talk(ws, "task one")[-1]["payload"]["text"] == "done"
        assert talk(ws, "task two")[-1]["payload"]["text"] == "done"


def test_model_error_arrives_as_a_failed_reply(client, monkeypatch):
    script(monkeypatch)  # nothing scripted: the provider raises
    with client.websocket_connect("ws://127.0.0.1/ws/chat/demo-agent") as ws:
        ws.receive_json()
        reply = talk(ws, "hello")[-1]["payload"]
        assert reply["ok"] is False and reply["stop_reason"] == "error"
        assert "ran out" in reply["text"]


def test_blank_and_oversized_messages(client, monkeypatch):
    script(monkeypatch, say("fine"))
    with client.websocket_connect("ws://127.0.0.1/ws/chat/demo-agent") as ws:
        ws.receive_json()
        ws.send_json({"type": "message", "text": "   "})  # ignored silently
        too_long = talk(ws, "x" * (server.MAX_MESSAGE_CHARS + 1))
        assert too_long[-1]["event"] == "error" and "too long" in too_long[-1]["payload"]["message"]
        assert talk(ws, "ok now")[-1]["payload"]["text"] == "fine"


def test_unknown_agent_gets_a_fatal_error(client):
    with client.websocket_connect("ws://127.0.0.1/ws/chat/nobody-here") as ws:
        msg = ws.receive_json()
        assert msg["event"] == "error" and msg["payload"]["fatal"] is True
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_agent_with_unbuilt_tools_gets_a_fatal_error(client, world, monkeypatch):
    monkeypatch.delitem(server.IMPLEMENTED, "code.run")  # pretend this tool is not built
    script(monkeypatch, say("unused"))
    (world / "specs" / "code.yaml").write_text(
        'name: code-agent\ngoal: "Needs a tool that does not exist yet"\n'
        "tools: [code.run]\npermissions: {shell: true}\n"
    )
    with client.websocket_connect("ws://127.0.0.1/ws/chat/code-agent") as ws:
        msg = ws.receive_json()
        assert msg["payload"]["fatal"] is True and "code.run" in msg["payload"]["message"]


def test_page_on_another_origin_cannot_connect(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://127.0.0.1/ws/chat/demo-agent", headers={"origin": "http://evil.example"}):
            pass


def test_page_from_this_origin_can_connect(client, monkeypatch):
    script(monkeypatch, say("unused"))
    with client.websocket_connect("ws://127.0.0.1/ws/chat/demo-agent", headers={"origin": "http://127.0.0.1"}) as ws:
        assert ws.receive_json()["event"] == "ready"


class Blocking(LLMProvider):
    """Holds the model busy until the test lets go."""

    def __init__(self, started: threading.Event, release: threading.Event):
        self.started, self.release = started, release

    def chat(self, messages, tools=None, schema=None):
        self.started.set()
        assert self.release.wait(10), "test never released the model"
        return say("slow answer")


def test_second_agent_waits_for_the_model(client, monkeypatch):
    started, release = threading.Event(), threading.Event()
    providers = iter([Blocking(started, release), MockProvider([say("quick answer")])])
    monkeypatch.setattr(server, "make_provider", lambda cfg: next(providers))
    with client.websocket_connect("ws://127.0.0.1/ws/chat/demo-agent") as one:
        one.receive_json()
        one.send_json({"type": "message", "text": "first"})
        assert one.receive_json()["event"] == "started"
        assert started.wait(5)
        with client.websocket_connect("ws://127.0.0.1/ws/chat/demo-agent") as two:
            two.receive_json()
            two.send_json({"type": "message", "text": "second"})
            assert two.receive_json()["event"] == "queued"
            release.set()
            while one.receive_json()["event"] != "reply":
                pass
            seen = []
            while not seen or seen[-1]["event"] != "reply":
                seen.append(two.receive_json())
            assert seen[0]["event"] == "started"
            assert seen[-1]["payload"]["text"] == "quick answer"


def test_provider_failure_is_reported_not_a_crash(client, monkeypatch):
    from factory.llm import ProviderError

    def broken(cfg):
        raise ProviderError("No model backend is available.")

    monkeypatch.setattr(server, "make_provider", broken)
    with client.websocket_connect("ws://127.0.0.1/ws/chat/demo-agent") as ws:
        msg = ws.receive_json()
        assert msg["event"] == "error" and msg["payload"]["fatal"] is True
        assert "No model backend" in msg["payload"]["message"]
