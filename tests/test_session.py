import pytest

from factory.llm import LLMProvider, LLMResponse, MockProvider, ToolCall
from factory.runtime import AgentSession, build_system_prompt
from factory.schema import AgentSpec


def make_spec(**overrides):
    base = dict(
        name="chat-agent",
        goal="Chat with the user about their ideas",
        mode="conversational",
        tools=["fs.list"],
        permissions={"fs_read": ["./sandbox"]},
        limits={"max_steps": 10, "max_tokens": 50000, "max_runtime_s": 60},
    )
    base.update(overrides)
    return AgentSpec.model_validate(base)


def say(text):
    return LLMResponse(content=text)


def use(name, **args):
    return LLMResponse(tool_calls=[ToolCall(name, args)])


def roles(messages):
    return [m["role"] for m in messages]


def test_history_is_kept_across_turns(tmp_path):
    provider = MockProvider([say("Nice choice!"), say("You said parrot.")])
    s = AgentSession(make_spec(), provider, base_dir=tmp_path)
    s.send("My favourite animal is the parrot")
    s.send("What did I say?")
    second = provider.calls[1]["messages"]
    assert roles(second) == ["system", "user", "assistant", "user"]
    assert second[1]["content"] == "My favourite animal is the parrot"
    assert second[2]["content"] == "Nice choice!"


def test_each_turn_gets_its_own_step_budget(tmp_path):
    (tmp_path / "sandbox").mkdir()
    spec = make_spec(limits={"max_steps": 2, "max_tokens": 50000, "max_runtime_s": 60})
    provider = MockProvider([
        use("fs_list", path="./sandbox"), say("one"),
        use("fs_list", path="./sandbox"), say("two"),
    ])
    s = AgentSession(spec, provider, base_dir=tmp_path)
    r1, r2 = s.send("a"), s.send("b")
    assert r1.ok and r2.ok
    assert (r1.steps, r2.steps) == (2, 2)


def test_repeat_detection_resets_every_turn(tmp_path):
    (tmp_path / "sandbox").mkdir()
    responses = []
    for _ in range(3):
        responses += [use("fs_list", path="./sandbox"), say("ok")]
    s = AgentSession(make_spec(), MockProvider(responses), base_dir=tmp_path)
    assert all(s.send("go").ok for _ in range(3))


def test_step_limit_leaves_clean_history(tmp_path):
    (tmp_path / "sandbox").mkdir()
    spec = make_spec(limits={"max_steps": 1, "max_tokens": 50000, "max_runtime_s": 60})
    provider = MockProvider([use("fs_list", path="./sandbox"), say("fine")])
    s = AgentSession(spec, provider, base_dir=tmp_path)
    r1 = s.send("list it")
    assert r1.stop_reason == "max_steps"
    assert roles(s.messages) == ["system", "user", "assistant"]
    assert "step limit" in s.messages[-1]["content"]
    r2 = s.send("hello")
    assert r2.ok
    assert roles(provider.calls[-1]["messages"]) == ["system", "user", "assistant", "user"]


def test_loop_detection_rolls_back_cleanly(tmp_path):
    (tmp_path / "sandbox").mkdir()
    same = use("fs_list", path="./sandbox")
    provider = MockProvider([same, same, same, say("back to normal")])
    s = AgentSession(make_spec(), provider, base_dir=tmp_path)
    assert s.send("go").stop_reason == "loop_detected"
    assert roles(s.messages) == ["system", "user", "assistant"]
    assert s.send("again").ok
    sent = provider.calls[-1]["messages"]
    assert not any(m["role"] == "tool" or m.get("tool_calls") for m in sent)


def test_provider_error_removes_the_failed_turn(tmp_path):
    s = AgentSession(make_spec(), MockProvider([]), base_dir=tmp_path)
    assert s.send("hello").stop_reason == "error"
    assert roles(s.messages) == ["system"]
    s.provider = MockProvider([say("hi")])
    assert s.send("hello again").ok
    assert roles(s.messages) == ["system", "user", "assistant"]


def test_old_turns_are_dropped_to_fit_the_context(tmp_path):
    spec = make_spec(model={"num_ctx": 2048})
    events = []
    provider = MockProvider([say("ok")] * 5)
    s = AgentSession(spec, provider, base_dir=tmp_path, on_event=events.append)
    for i in range(5):
        s.send(f"T{i} " + "x" * 1500)
    text = str(s.messages)
    assert s.messages[0]["role"] == "system"
    assert "T4 " in text
    assert "T0 " not in text
    assert any(e["event"] == "trim" for e in events)


def test_notes_are_loaded_into_the_system_prompt(tmp_path):
    notes = tmp_path / "data" / "chat-agent"
    notes.mkdir(parents=True)
    (notes / "notes.md").write_text("Decided: the project is called Atlas.\n")
    spec = make_spec(tools=["notes.append"], memory={"notes": True})
    s = AgentSession(spec, MockProvider([]), base_dir=tmp_path)
    prompt = s.messages[0]["content"]
    assert "Atlas" in prompt and "saved notes" in prompt
    assert "data, not instructions" in prompt


def test_first_session_says_there_are_no_notes(tmp_path):
    spec = make_spec(tools=["notes.append"], memory={"notes": True})
    s = AgentSession(spec, MockProvider([]), base_dir=tmp_path)
    assert "no saved notes yet" in s.messages[0]["content"]


def test_long_notes_are_cut_to_the_recent_part(tmp_path):
    notes = tmp_path / "data" / "chat-agent"
    notes.mkdir(parents=True)
    (notes / "notes.md").write_text("OLD " * 5000 + "NEWEST-MARKER\n")
    spec = make_spec(tools=["notes.append"], memory={"notes": True})
    prompt = AgentSession(spec, MockProvider([]), base_dir=tmp_path).messages[0]["content"]
    assert "NEWEST-MARKER" in prompt and "older notes omitted" in prompt
    assert len(prompt) < 4500


def test_no_notes_section_when_memory_is_off(tmp_path):
    s = AgentSession(make_spec(), MockProvider([]), base_dir=tmp_path)
    assert "saved notes" not in s.messages[0]["content"]


class Interrupting(LLMProvider):
    def chat(self, messages, tools=None, schema=None):
        raise KeyboardInterrupt


def test_ctrl_c_removes_the_unfinished_turn(tmp_path):
    s = AgentSession(make_spec(), Interrupting(), base_dir=tmp_path)
    with pytest.raises(KeyboardInterrupt):
        s.send("hello")
    assert roles(s.messages) == ["system"]


def test_rules_depend_on_the_mode():
    chat = build_system_prompt(make_spec())
    task = build_system_prompt(make_spec(mode="task"))
    assert "in a conversation" in chat and "in a conversation" not in task
    assert "do not call more tools" in task and "do not call more tools" not in chat


def test_note_saved_in_one_session_is_seen_in_the_next(tmp_path):
    spec = make_spec(tools=["notes.append"], memory={"notes": True})
    first = AgentSession(
        spec,
        MockProvider([use("notes_append", text="Project name: Atlas"), say("Saved.")]),
        base_dir=tmp_path,
    )
    assert first.send("Let's call it Atlas").ok
    second = AgentSession(spec, MockProvider([]), base_dir=tmp_path)
    assert "Project name: Atlas" in second.messages[0]["content"]
