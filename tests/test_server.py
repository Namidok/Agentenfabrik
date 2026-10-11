import asyncio
import threading

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from factory import server
from factory.scheduler import ModelScheduler
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
    monkeypatch.setattr(server, "SCHEDULER", ModelScheduler(1))
    monkeypatch.setattr(server, "loaded_models", lambda host=None: None)  # never call the real Ollama
    monkeypatch.setattr(server, "warm_up", lambda configs: None)
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


class BlockThenTool(LLMProvider):
    """First call: waits for the test, then asks for a tool (so the turn would go on). Later calls answer."""

    def __init__(self, started: threading.Event, release: threading.Event):
        self.started, self.release, self.calls = started, release, 0

    def chat(self, messages, tools=None, schema=None):
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            assert self.release.wait(10), "test never released the model"
            return use("fs_list", path="./sandbox")
        return say("back again")


def test_stop_ends_the_turn_after_the_current_step_and_the_chat_goes_on(client, monkeypatch):
    started, release = threading.Event(), threading.Event()
    provider = BlockThenTool(started, release)
    monkeypatch.setattr(server, "make_provider", lambda cfg: provider)
    with client.websocket_connect("ws://127.0.0.1/ws/chat/demo-agent") as ws:
        ws.receive_json()
        ws.send_json({"type": "message", "text": "list the files"})
        assert ws.receive_json()["event"] == "started"
        assert started.wait(5)
        ws.send_json({"type": "stop"})
        ws.send_json({"type": "message", "text": "too early"})  # refused while the turn runs
        release.set()
        events = []
        while not events or events[-1]["event"] != "reply":
            events.append(ws.receive_json())
        reply = events[-1]["payload"]
        assert reply["stop_reason"] == "stopped" and reply["ok"] is False
        assert "stopped me" in reply["text"]
        assert any(e["event"] == "error" and "still working" in e["payload"]["message"] for e in events)
        assert provider.calls == 1  # the tool ran, but no further model call was made
        assert talk(ws, "hello again")[-1]["payload"]["text"] == "back again"


def test_stop_without_a_running_turn_is_ignored(client, monkeypatch):
    script(monkeypatch, say("hi"))
    with client.websocket_connect("ws://127.0.0.1/ws/chat/demo-agent") as ws:
        ws.receive_json()
        ws.send_json({"type": "stop"})
        assert talk(ws, "hello")[-1]["payload"]["text"] == "hi"


CARD_SPEC = """name: card-agent
goal: "An agent with a flashcard box"
tools: [srs.add, srs.due]
memory: {srs: true}
"""


def test_cards_endpoint_lists_the_box_and_refuses_agents_without_one(client, world):
    from factory import srs
    from factory.tools import ToolContext
    (world / "specs" / "cards.yaml").write_text(CARD_SPEC)
    assert client.get("/api/agents/card-agent/cards").json()["cards"] == []
    spec = server.find_spec("card-agent")
    srs.srs_add(ToolContext(spec, world), {"front": "the dog", "back": "der Hund"})
    data = client.get("/api/agents/card-agent/cards").json()
    assert data["total"] == 1 and data["cards"][0]["back"] == "der Hund"
    assert client.get("/api/agents/demo-agent/cards").status_code == 404


# ---------- settings: per-agent model and parallel agents ----------

LIGHT_SPEC = """name: light-agent
goal: "A light agent on a small model"
model:
  name: llama3.2
"""


def test_agents_report_their_real_model_and_where_it_comes_from(client, world, monkeypatch):
    from factory.settings import Settings
    monkeypatch.setattr(server, "SETTINGS", Settings(default_model="qwen3:4b-instruct"))
    (world / "specs" / "light.yaml").write_text(LIGHT_SPEC)
    agents = {a["name"]: a for a in client.get("/api/agents").json()["agents"]}
    assert (agents["demo-agent"]["model"], agents["demo-agent"]["model_source"]) == ("qwen3:4b-instruct", "default")
    assert (agents["light-agent"]["model"], agents["light-agent"]["model_source"]) == ("llama3.2", "spec")
    assert agents["light-agent"]["model_installed"] is False  # only qwen3:8b is installed in this world
    assert agents["demo-agent"]["model_installed"] is False


def test_a_chat_runs_on_the_agents_own_model(client, world, monkeypatch):
    (world / "specs" / "light.yaml").write_text(LIGHT_SPEC)
    asked = []
    monkeypatch.setattr(server, "make_provider", lambda cfg: asked.append(cfg.name) or MockProvider([say("hi")]))
    with client.websocket_connect("ws://127.0.0.1/ws/chat/light-agent") as ws:
        ws.receive_json()
        assert talk(ws, "hello")[-1]["payload"]["text"] == "hi"
    assert asked and set(asked) == {"llama3.2"}  # a task agent starts a session per message, each on its own model


def test_config_reports_the_settings(client, monkeypatch):
    from factory.settings import Settings
    monkeypatch.setattr(server, "SETTINGS", Settings(max_parallel=2))
    data = client.get("/api/config").json()
    assert data["max_parallel"] == 2 and data["default_model"] == "qwen3:8b" and data["settings_error"] == ""


def test_with_two_slots_two_agents_think_at_once_and_a_third_waits(client, world, monkeypatch):
    monkeypatch.setattr(server, "SCHEDULER", ModelScheduler(2))
    started = [threading.Event(), threading.Event()]
    release = threading.Event()
    providers = iter([Blocking(started[0], release), Blocking(started[1], release), MockProvider([say("third")])])
    monkeypatch.setattr(server, "make_provider", lambda cfg: next(providers))
    url = "ws://127.0.0.1/ws/chat/demo-agent"
    with client.websocket_connect(url) as one, client.websocket_connect(url) as two, client.websocket_connect(url) as three:
        for ws in (one, two, three):
            ws.receive_json()
        one.send_json({"type": "message", "text": "a"})
        assert one.receive_json()["event"] == "started"
        two.send_json({"type": "message", "text": "b"})
        assert two.receive_json()["event"] == "started"  # no queue for the second agent
        assert started[0].wait(5) and started[1].wait(5)  # both are inside the model at the same time
        three.send_json({"type": "message", "text": "c"})
        assert three.receive_json()["event"] == "queued"  # the third waits for a free slot
        release.set()
        for ws in (one, two):
            while ws.receive_json()["event"] != "reply":
                pass
        events = []
        while not events or events[-1]["event"] != "reply":
            events.append(three.receive_json())
        assert events[0]["event"] == "started" and events[-1]["payload"]["text"] == "third"


def test_stop_works_per_agent_while_two_think_at_once(client, world, monkeypatch):
    monkeypatch.setattr(server, "SCHEDULER", ModelScheduler(2))
    started = [threading.Event(), threading.Event()]
    release = threading.Event()
    stopped, kept = BlockThenTool(started[0], release), BlockThenTool(started[1], release)
    providers = iter([stopped, kept])
    monkeypatch.setattr(server, "make_provider", lambda cfg: next(providers))
    url = "ws://127.0.0.1/ws/chat/demo-agent"
    with client.websocket_connect(url) as one, client.websocket_connect(url) as two:
        for ws in (one, two):
            ws.receive_json()
        one.send_json({"type": "message", "text": "a"})
        two.send_json({"type": "message", "text": "b"})
        assert started[0].wait(5) and started[1].wait(5)
        one.send_json({"type": "stop"})
        release.set()
        replies = {}
        for name, ws in (("one", one), ("two", two)):
            msg = ws.receive_json()
            while msg["event"] != "reply":
                msg = ws.receive_json()
            replies[name] = msg["payload"]
        assert replies["one"]["stop_reason"] == "stopped" and stopped.calls == 1
        assert replies["two"]["stop_reason"] == "done" and replies["two"]["text"] == "back again" and kept.calls == 2


def test_waiting_agents_are_told_their_place_and_a_stop_while_waiting_leaves_the_line(client, world, monkeypatch):
    started, release = threading.Event(), threading.Event()
    providers = iter([Blocking(started, release), MockProvider([say("never")]), MockProvider([say("third")])])
    monkeypatch.setattr(server, "make_provider", lambda cfg: next(providers))
    url = "ws://127.0.0.1/ws/chat/demo-agent"
    with client.websocket_connect(url) as one, client.websocket_connect(url) as two, client.websocket_connect(url) as three:
        for ws in (one, two, three):
            ws.receive_json()
        one.send_json({"type": "message", "text": "a"})
        assert one.receive_json()["event"] == "started" and started.wait(5)
        two.send_json({"type": "message", "text": "b"})
        assert two.receive_json() == {"event": "queued", "payload": {"position": 1, "reason": "slots"}}
        three.send_json({"type": "message", "text": "c"})
        assert three.receive_json()["payload"]["position"] == 2
        two.send_json({"type": "stop"})
        reply = two.receive_json()
        assert reply["event"] == "reply" and reply["payload"]["stop_reason"] == "stopped" and reply["payload"]["steps"] == 0
        assert three.receive_json()["payload"]["position"] == 1  # moved up
        release.set()
        while one.receive_json()["event"] != "reply":
            pass
        events = []
        while not events or events[-1]["event"] != "reply":
            events.append(three.receive_json())
        assert events[-1]["payload"]["text"] == "third"


def test_a_failing_agent_does_not_block_the_next_one(client, world, monkeypatch):
    from factory.llm import ProviderError

    class Broken(LLMProvider):
        def chat(self, messages, tools=None, schema=None):
            raise ProviderError("Ollama returned 500")
    providers = iter([Broken(), MockProvider([say("fine")])])
    monkeypatch.setattr(server, "make_provider", lambda cfg: next(providers))
    url = "ws://127.0.0.1/ws/chat/demo-agent"
    with client.websocket_connect(url) as one, client.websocket_connect(url) as two:
        one.receive_json(), two.receive_json()
        assert talk(one, "a")[-1]["payload"]["ok"] is False
        assert talk(two, "b")[-1]["payload"]["text"] == "fine"
    assert server.SCHEDULER.running == 0


def test_a_cold_model_is_announced_as_loading_before_thinking(client, monkeypatch):
    script(monkeypatch, say("hi"))
    monkeypatch.setattr(server, "loaded_models", lambda host=None: {"qwen3:8b": 4096})  # loaded, but another size
    with client.websocket_connect("ws://127.0.0.1/ws/chat/demo-agent") as ws:
        ws.receive_json()
        events = [e["event"] for e in talk(ws, "hello")]
    assert events[:2] == ["loading", "started"]
    monkeypatch.setattr(server, "loaded_models", lambda host=None: {"qwen3:8b": 8192})
    with client.websocket_connect("ws://127.0.0.1/ws/chat/demo-agent") as ws:
        ws.receive_json()
        assert talk(ws, "hello")[0]["event"] == "started"


def test_replies_stream_over_the_websocket(client, monkeypatch):
    script(monkeypatch, say("Hello there, this streams."))
    with client.websocket_connect("ws://127.0.0.1/ws/chat/demo-agent") as ws:
        ws.receive_json()
        events = talk(ws, "hello")
    deltas = [e["payload"]["text"] for e in events if e["event"] == "trace" and e["payload"]["event"] == "delta"]
    assert "".join(deltas) == "Hello there, this streams." and events[-1]["payload"]["text"] == "Hello there, this streams."


def test_hiring_warms_the_new_agents_model(client, world, monkeypatch):
    warmed = []
    monkeypatch.setattr(server, "warm_up", lambda configs: warmed.extend(c.name for c in configs))
    form = {"name": "warm-agent", "goal": "Say hello to people nicely", "mode": "conversational"}
    assert client.post("/api/hire", json=form, headers={"X-AgentFactory": "1"}).status_code == 200
    assert warmed == ["qwen3:8b"]
