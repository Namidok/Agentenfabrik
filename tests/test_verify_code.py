import pytest

from factory import sandbox
from factory.llm import LLMResponse, MockProvider, ToolCall
from factory.runtime import CODE_NUDGE, AgentSession, has_untested_code
from factory.schema import AgentSpec

F = "`" * 3
CPP = F + "cpp\nint main(){}\n" + F


def make_spec(**overrides):
    base = dict(
        name="teach-agent",
        goal="Teach C++ with examples",
        mode="conversational",
        tools=["code.run"],
        permissions={"shell": True},
        verify_code_blocks=True,
    )
    base.update(overrides)
    return AgentSpec.model_validate(base)


@pytest.fixture(autouse=True)
def fake_compiler(monkeypatch):
    monkeypatch.setattr(sandbox, "run_cpp", lambda code, stdin="": "Compiled successfully.")


def say(text):
    return LLMResponse(content=text)


def use(name, **args):
    return LLMResponse(tool_calls=[ToolCall(name, args)])


def user_messages(call):
    return [m["content"] for m in call["messages"] if m["role"] == "user"]


def test_flag_defaults_to_off():
    spec = AgentSpec.model_validate({"name": "plain-agent", "goal": "Do something useful"})
    assert spec.verify_code_blocks is False


def test_untested_code_is_sent_back_to_be_run(tmp_path):
    provider = MockProvider([
        say("Draft lesson:\n" + CPP),
        use("code_run", code="int main(){}"),
        say("Verified lesson. It compiles."),
    ])
    events = []
    s = AgentSession(make_spec(), provider, base_dir=tmp_path, on_event=events.append)
    r = s.send("Teach me something")
    assert r.ok
    assert r.final_text == "Verified lesson. It compiles."
    assert len(provider.calls) == 3
    assert CODE_NUDGE in user_messages(provider.calls[1])
    assert any(e["event"] == "nudge" for e in events)
    assert "Draft lesson" not in str(s.messages)
    assert not any(m.get("content") == CODE_NUDGE for m in s.messages)


def test_code_nudge_happens_only_once(tmp_path):
    provider = MockProvider([say("first draft\n" + CPP), say("second draft\n" + CPP)])
    r = AgentSession(make_spec(), provider, base_dir=tmp_path).send("Teach me")
    assert r.ok and r.final_text.startswith("second draft")
    assert len(provider.calls) == 2


def test_no_nudge_when_code_was_already_run(tmp_path):
    provider = MockProvider([use("code_run", code="int main(){}"), say("Here:\n" + CPP)])
    r = AgentSession(make_spec(), provider, base_dir=tmp_path).send("Teach me")
    assert r.ok and len(provider.calls) == 2


def test_no_nudge_without_a_code_block(tmp_path):
    provider = MockProvider([say("Just words, no code.")])
    AgentSession(make_spec(), provider, base_dir=tmp_path).send("Hi")
    assert len(provider.calls) == 1


def test_no_nudge_when_the_flag_is_off(tmp_path):
    provider = MockProvider([say(CPP)])
    AgentSession(make_spec(verify_code_blocks=False), provider, base_dir=tmp_path).send("Hi")
    assert len(provider.calls) == 1


def test_no_nudge_without_the_code_tool(tmp_path):
    spec = make_spec(tools=["fs.list"], permissions={"fs_read": ["./sandbox"]})
    provider = MockProvider([say(CPP)])
    AgentSession(spec, provider, base_dir=tmp_path).send("Hi")
    assert len(provider.calls) == 1


@pytest.mark.parametrize("text", [
    F + "cpp\nint main(){}\n" + F,
    "Try this:\n" + F + "c++\nint x;\n" + F,
    F + "C\nint x;\n" + F,
    F + " cpp \nint x;\n" + F,
])
def test_detects_c_and_cpp_blocks(text):
    assert has_untested_code(text)


@pytest.mark.parametrize("text", [
    F + "python\nprint(1)\n" + F,
    F + "csharp\nint x;\n" + F,
    "No code here, just `inline` words.",
    "",
])
def test_ignores_other_text(text):
    assert not has_untested_code(text)
