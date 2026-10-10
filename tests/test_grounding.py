import pytest

from factory.llm import LLMResponse, MockProvider, ToolCall
from factory.runtime import READ_NUDGE, AgentSession, needs_file_grounding
from factory.schema import AgentSpec

REVIEW = "Look at the files in ./sandbox and tell me one thing to improve"


def make_spec(**overrides):
    base = dict(
        name="review-agent",
        goal="Review files for the user",
        mode="conversational",
        tools=["fs.list", "fs.read"],
        permissions={"fs_read": ["./sandbox"]},
        read_before_answer=True,
    )
    base.update(overrides)
    return AgentSpec.model_validate(base)


@pytest.fixture
def world(tmp_path):
    (tmp_path / "sandbox").mkdir()
    (tmp_path / "sandbox" / "a.py").write_text("print(1)")
    return tmp_path


def say(text):
    return LLMResponse(content=text)


def use(name, **args):
    return LLMResponse(tool_calls=[ToolCall(name, args)])


def test_flag_defaults_to_off():
    spec = AgentSpec.model_validate({"name": "plain-agent", "goal": "Do something useful"})
    assert spec.read_before_answer is False


def test_nudge_forces_a_read_before_a_review(world):
    provider = MockProvider([
        use("fs_list", path="./sandbox"),
        say("Add comments to a.py."),
        use("fs_read", path="./sandbox/a.py"),
        say("a.py only prints 1; add a docstring."),
    ])
    events = []
    s = AgentSession(make_spec(), provider, base_dir=world, on_event=events.append)
    r = s.send(REVIEW)
    assert r.ok
    assert r.final_text == "a.py only prints 1; add a docstring."
    assert any(e["event"] == "nudge" for e in events)
    assert len(provider.calls) == 4
    assert "read the relevant file" in str(provider.calls[2]["messages"])
    assert not any(m.get("content") == READ_NUDGE for m in s.messages)
    assert "Add comments" not in str(s.messages)


def test_nudge_happens_only_once(world):
    provider = MockProvider([
        use("fs_list", path="./sandbox"),
        say("first guess"),
        say("second guess"),
    ])
    r = AgentSession(make_spec(), provider, base_dir=world).send(REVIEW)
    assert r.ok and r.final_text == "second guess"
    assert len(provider.calls) == 3


def test_no_nudge_when_a_file_was_already_read(world):
    provider = MockProvider([
        use("fs_list", path="./sandbox"),
        use("fs_read", path="./sandbox/a.py"),
        say("Grounded answer."),
    ])
    events = []
    AgentSession(make_spec(), provider, base_dir=world, on_event=events.append).send(REVIEW)
    assert len(provider.calls) == 3
    assert not any(e["event"] == "nudge" for e in events)


def test_failed_read_does_not_count(world):
    provider = MockProvider([
        use("fs_read", path="./sandbox/nope.py"),
        say("a guess"),
        use("fs_read", path="./sandbox/a.py"),
        say("Now grounded."),
    ])
    r = AgentSession(make_spec(), provider, base_dir=world).send(REVIEW)
    assert r.final_text == "Now grounded."
    assert len(provider.calls) == 4


def test_no_nudge_for_a_general_question(world):
    provider = MockProvider([say("Start small.")])
    AgentSession(make_spec(), provider, base_dir=world).send("Where should I start with my idea?")
    assert len(provider.calls) == 1


def test_no_nudge_when_the_flag_is_off(world):
    provider = MockProvider([use("fs_list", path="./sandbox"), say("fine")])
    AgentSession(make_spec(read_before_answer=False), provider, base_dir=world).send(REVIEW)
    assert len(provider.calls) == 2


def test_no_nudge_without_a_read_tool(world):
    provider = MockProvider([use("fs_list", path="./sandbox"), say("fine")])
    AgentSession(make_spec(tools=["fs.list"]), provider, base_dir=world).send(REVIEW)
    assert len(provider.calls) == 2


@pytest.mark.parametrize("text", [
    "Look at the files in ./factory and tell me one thing you would improve.",
    "Review notes.md please",
    "Is there a bug in main.py?",
    "Check ./sandbox and suggest changes",
])
def test_review_requests_need_grounding(text):
    assert needs_file_grounding(text)


@pytest.mark.parametrize("text", [
    "Where do I start?",
    "What were we working on?",
    "I want a better idea for my project",
    "List the files in ./sandbox",
])
def test_other_requests_do_not(text):
    assert not needs_file_grounding(text)
