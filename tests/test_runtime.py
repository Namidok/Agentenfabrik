import pytest

from factory.llm import LLMResponse, MockProvider, ToolCall
from factory.runtime import run_agent
from factory.schema import AgentSpec


@pytest.fixture
def world(tmp_path):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "readme.txt").write_text("Hello from the sandbox.")
    (sandbox / "todo.txt").write_text("Buy milk.")
    (tmp_path / "secret.txt").write_text("TOP SECRET")
    return tmp_path


def make_spec(**overrides):
    base = dict(
        name="test-agent",
        goal="List and summarize the files",
        tools=["fs.list", "fs.read"],
        permissions={"fs_read": ["./sandbox"]},
        limits={"max_steps": 10, "max_tokens": 20000, "max_runtime_s": 60},
    )
    base.update(overrides)
    return AgentSpec.model_validate(base)


def call(name, **args):
    return ToolCall(name=name, arguments=args)


def resp(content="", calls=None, tokens=0):
    return LLMResponse(content=content, tool_calls=calls or [], prompt_tokens=tokens)


def tool_outputs(provider):
    msgs = provider.calls[-1]["messages"]
    return [m["content"] for m in msgs if m["role"] == "tool"]


def test_list_read_and_answer(world):
    provider = MockProvider([
        resp(calls=[call("fs_list", path="./sandbox")]),
        resp(calls=[call("fs_read", path="./sandbox/readme.txt")]),
        resp("Two files: readme.txt and todo.txt."),
    ])
    result = run_agent(make_spec(), "go", provider, base_dir=world)
    assert result.ok
    assert result.steps == 3
    assert "readme.txt" in result.final_text
    outputs = tool_outputs(provider)
    assert "todo.txt (file" in outputs[0]
    assert outputs[1] == "Hello from the sandbox."


def test_path_outside_allowed_folder_is_denied(world):
    provider = MockProvider([
        resp(calls=[call("fs_read", path="./secret.txt")]),
        resp("I could not read it."),
    ])
    result = run_agent(make_spec(), "go", provider, base_dir=world)
    assert result.ok
    assert "Permission denied" in tool_outputs(provider)[0]
    assert "TOP SECRET" not in str(provider.calls[-1]["messages"])


def test_dotdot_traversal_is_denied(world):
    provider = MockProvider([
        resp(calls=[call("fs_read", path="sandbox/../secret.txt")]),
        resp("done"),
    ])
    run_agent(make_spec(), "go", provider, base_dir=world)
    assert "Permission denied" in tool_outputs(provider)[0]
    assert "TOP SECRET" not in str(provider.calls[-1]["messages"])


def test_symlink_escape_is_denied(world):
    (world / "sandbox" / "link.txt").symlink_to(world / "secret.txt")
    provider = MockProvider([
        resp(calls=[call("fs_read", path="./sandbox/link.txt")]),
        resp("done"),
    ])
    run_agent(make_spec(), "go", provider, base_dir=world)
    assert "Permission denied" in tool_outputs(provider)[0]
    assert "TOP SECRET" not in str(provider.calls[-1]["messages"])


def test_tool_not_in_spec_is_refused(world):
    spec = make_spec(tools=["fs.list"])
    provider = MockProvider([
        resp(calls=[call("fs_read", path="./sandbox/readme.txt")]),
        resp("done"),
    ])
    run_agent(spec, "go", provider, base_dir=world)
    assert "unknown or disallowed tool" in tool_outputs(provider)[0]


def test_missing_file_is_an_error_message_not_a_crash(world):
    provider = MockProvider([
        resp(calls=[call("fs_read", path="./sandbox/nope.txt")]),
        resp("It does not exist."),
    ])
    result = run_agent(make_spec(), "go", provider, base_dir=world)
    assert result.ok
    assert tool_outputs(provider)[0].startswith("ERROR")


def test_max_steps_stops_the_run(world):
    spec = make_spec(limits={"max_steps": 2, "max_tokens": 20000, "max_runtime_s": 60})
    provider = MockProvider([
        resp(calls=[call("fs_list", path="./sandbox")]),
        resp(calls=[call("fs_read", path="./sandbox/readme.txt")]),
    ])
    result = run_agent(spec, "go", provider, base_dir=world)
    assert result.stop_reason == "max_steps"
    assert result.steps == 2


def test_token_budget_stops_the_run(world):
    spec = make_spec(limits={"max_steps": 10, "max_tokens": 1000, "max_runtime_s": 60})
    provider = MockProvider([
        resp(calls=[call("fs_list", path="./sandbox")], tokens=1500),
    ])
    result = run_agent(spec, "go", provider, base_dir=world)
    assert result.stop_reason == "max_tokens"


def test_repeated_identical_calls_are_stopped(world):
    same = call("fs_list", path="./sandbox")
    provider = MockProvider([resp(calls=[same]), resp(calls=[same]), resp(calls=[same])])
    result = run_agent(make_spec(), "go", provider, base_dir=world)
    assert result.stop_reason == "loop_detected"


def test_provider_error_is_reported_not_raised(world):
    result = run_agent(make_spec(), "go", MockProvider([]), base_dir=world)
    assert result.stop_reason == "error"
    assert "ran out" in result.final_text


def test_unimplemented_tool_fails_before_running(world):
    spec = make_spec(tools=["fs.move"], permissions={"fs_write": ["./sandbox"]})
    with pytest.raises(NotImplementedError, match="fs.move"):
        run_agent(spec, "go", MockProvider([]), base_dir=world)


def test_a_cancelled_session_stops_before_the_next_model_call_and_stays_usable(world):
    from factory.runtime import AgentSession
    provider = MockProvider([resp(calls=[call("fs_list", path="./sandbox")]), resp("hello again")])
    session = AgentSession(make_spec(mode="conversational"), provider, base_dir=world)
    session.cancel.set()
    result = session.send("go")
    assert result.stop_reason == "stopped" and result.steps == 0
    assert result.final_text == "(You stopped me before I could finish.)"
    assert [m["role"] for m in session.messages] == ["system", "user", "assistant"]
    session.cancel.clear()
    assert session.send("again").stop_reason == "done"


def test_replies_stream_to_the_listener_but_not_into_the_trace(world):
    from factory.runtime import AgentSession
    events = []
    provider = MockProvider([resp("Hello there, nice to meet you.")], piece=6)
    session = AgentSession(make_spec(mode="conversational"), provider, base_dir=world, on_event=events.append)
    result = session.send("hi")
    deltas = [e for e in events if e["event"] == "delta"]
    assert "".join(e["text"] for e in deltas) == "Hello there, nice to meet you." and len(deltas) > 3
    assert all(e["step"] == 1 for e in deltas)
    assert not [e for e in result.trace if e["event"] == "delta"]


def test_stop_while_the_model_is_writing_keeps_no_partial_reply(world):
    from factory.runtime import AgentSession
    session = None
    pieces = []

    def listen(entry):
        if entry["event"] == "delta":
            pieces.append(entry["text"])
            if len(pieces) == 2:
                session.cancel.set()  # the Stop button, mid-sentence
    provider = MockProvider([resp("This answer is long and will be cut off halfway through.")], piece=5)
    session = AgentSession(make_spec(mode="conversational"), provider, base_dir=world, on_event=listen)
    result = session.send("tell me something")
    assert result.stop_reason == "stopped" and len(pieces) == 2
    assert result.final_text == "(You stopped me before I could finish.)"
    assert not any("cut off" in str(m.get("content")) for m in session.messages)
    assert [m["role"] for m in session.messages] == ["system", "user", "assistant"]


# ---------- folding long chats into a summary ----------

def test_long_chats_keep_the_last_turns_and_fold_older_ones_into_a_summary(world):
    from factory.runtime import FOLD_AT, KEEP_TURNS, SUMMARY_HEAD, AgentSession
    n = FOLD_AT + 1
    provider = MockProvider([resp(f"answer {i}") for i in range(n + 3)])
    events = []
    session = AgentSession(make_spec(mode="conversational"), provider, base_dir=world, on_event=events.append)
    system = session.messages[0]["content"]
    for i in range(n):
        session.send(f"question {i}")
    users = [m for m in session.messages if m["role"] == "user"]
    assert users[0]["content"].startswith(SUMMARY_HEAD)  # the summary sits right after the system prompt
    assert "- User: question 0" in users[0]["content"] and "- You: answer 0" in users[0]["content"]
    assert [m["content"] for m in users[1:]] == [f"question {i}" for i in range(n - KEEP_TURNS, n)]  # the last ones, word for word
    assert session.messages[0]["content"] == system  # byte-stable prefix
    folds = [e for e in events if e["event"] == "summary"]
    assert len(folds) == 1 and folds[0]["turns"] == n - KEEP_TURNS
    # the next turns do not fold again until the chat passes FOLD_AT turns once more
    session.send("one more")
    assert len([e for e in events if e["event"] == "summary"]) == 1
    assert provider.calls[-1]["messages"][1]["content"].startswith(SUMMARY_HEAD)


def test_the_summary_records_tools_and_stays_short():
    from factory.runtime import summarize_turns
    lines = summarize_turns([
        {"role": "user", "content": "add a card for dog"},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "srs_add", "arguments": {}}}]},
        {"role": "tool", "content": "Card added as id 1"},
        {"role": "assistant", "content": "Done: der Hund. " + "x" * 400},
    ])
    assert lines[0] == "- User: add a card for dog"
    assert lines[1].startswith("- You: Done: der Hund.") and lines[1].endswith("(used srs_add)") and len(lines[1]) < 200
