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
    spec = make_spec(tools=["srs.add"], memory={"srs": True})
    with pytest.raises(NotImplementedError, match="srs.add"):
        run_agent(spec, "go", MockProvider([]), base_dir=world)
