from pathlib import Path

import pytest

from factory.llm import LLMResponse, MockProvider, ToolCall
from factory.runtime import run_agent
from factory.schema import AgentSpec
from factory.tools import IMPLEMENTED, ToolContext, ToolError


@pytest.fixture
def world(tmp_path):
    (tmp_path / "sandbox").mkdir()
    (tmp_path / "out").mkdir()
    (tmp_path / "secret.txt").write_text("TOP SECRET")
    return tmp_path


def make_spec(name="writer-agent", **overrides):
    base = dict(
        name=name,
        goal="Write and remember things",
        tools=["fs.write", "notes.read", "notes.append"],
        permissions={"fs_read": ["./sandbox"], "fs_write": ["./out"]},
        memory={"notes": True},
    )
    base.update(overrides)
    return AgentSpec.model_validate(base)


def run_tool(world, tool_id, spec=None, **args):
    ctx = ToolContext(spec or make_spec(), world)
    return IMPLEMENTED[tool_id].func(ctx, args)


def test_write_creates_file_and_parent_folders(world):
    out = run_tool(world, "fs.write", path="./out/sub/a.txt", content="hi")
    assert "Wrote" in out
    assert (world / "out" / "sub" / "a.txt").read_text() == "hi"


def test_write_refuses_to_overwrite_by_default(world):
    (world / "out" / "a.txt").write_text("old")
    with pytest.raises(ToolError, match="already exists"):
        run_tool(world, "fs.write", path="./out/a.txt", content="new")
    assert (world / "out" / "a.txt").read_text() == "old"


def test_write_ignores_overwrite_argument_from_the_model(world):
    f = world / "out" / "a.txt"
    f.write_text("old")
    with pytest.raises(ToolError, match="a-2.txt"):
        run_tool(world, "fs.write", path="./out/a.txt", content="new", overwrite=True)
    assert f.read_text() == "old"


def test_write_suggestion_skips_taken_names(world):
    (world / "out" / "a.txt").write_text("1")
    (world / "out" / "a-2.txt").write_text("2")
    with pytest.raises(ToolError, match="a-3.txt"):
        run_tool(world, "fs.write", path="./out/a.txt", content="x")


def test_write_replaces_when_spec_allows_overwrite(world):
    spec = make_spec(permissions={
        "fs_read": ["./sandbox"], "fs_write": ["./out"], "allow_overwrite": True,
    })
    f = world / "out" / "a.txt"
    f.write_text("old")
    run_tool(world, "fs.write", spec=spec, path="./out/a.txt", content="new")
    assert f.read_text() == "new"


def test_write_outside_allowed_folders_is_denied(world):
    # ./sandbox is readable but not writable
    with pytest.raises(ToolError, match="Permission denied"):
        run_tool(world, "fs.write", path="./sandbox/x.txt", content="x")
    assert not (world / "sandbox" / "x.txt").exists()


def test_write_dotdot_traversal_is_denied(world):
    with pytest.raises(ToolError, match="Permission denied"):
        run_tool(world, "fs.write", path="out/../secret.txt", content="pwned", overwrite=True)
    assert (world / "secret.txt").read_text() == "TOP SECRET"


def test_write_symlink_escape_is_denied(world):
    (world / "out" / "link.txt").symlink_to(world / "secret.txt")
    with pytest.raises(ToolError, match="Permission denied"):
        run_tool(world, "fs.write", path="./out/link.txt", content="pwned", overwrite=True)
    assert (world / "secret.txt").read_text() == "TOP SECRET"


def test_write_needs_text_content(world):
    with pytest.raises(ToolError, match="content"):
        run_tool(world, "fs.write", path="./out/a.txt")
    with pytest.raises(ToolError, match="content"):
        run_tool(world, "fs.write", path="./out/a.txt", content=5)


def test_write_rejects_huge_content(world):
    with pytest.raises(ToolError, match="too large"):
        run_tool(world, "fs.write", path="./out/a.txt", content="x" * 100_001)


def test_write_to_a_folder_is_an_error(world):
    with pytest.raises(ToolError, match="folder"):
        run_tool(world, "fs.write", path="./out", content="x", overwrite=True)


def test_notes_roundtrip_and_location(world):
    assert run_tool(world, "notes.read") == "(no notes yet)"
    run_tool(world, "notes.append", text="Learner knows pointers.")
    run_tool(world, "notes.append", text="Next: smart pointers.")
    out = run_tool(world, "notes.read")
    assert "Learner knows pointers." in out
    assert "Next: smart pointers." in out
    assert (world / "data" / "writer-agent" / "notes.md").exists()


def test_notes_are_separate_per_agent(world):
    run_tool(world, "notes.append", spec=make_spec("agent-one"), text="one")
    assert run_tool(world, "notes.read", spec=make_spec("agent-two")) == "(no notes yet)"


def test_notes_append_needs_text(world):
    with pytest.raises(ToolError, match="text"):
        run_tool(world, "notes.append")


def test_notes_have_a_size_cap(world):
    run_tool(world, "notes.append", text="x" * 40_000)
    with pytest.raises(ToolError, match="full"):
        run_tool(world, "notes.append", text="y" * 20_000)


def test_notes_read_shows_the_most_recent_part(world):
    run_tool(world, "notes.append", text="OLD " * 3000)
    run_tool(world, "notes.append", text="LATEST-MARKER")
    out = run_tool(world, "notes.read")
    assert "LATEST-MARKER" in out
    assert "earlier notes omitted" in out


def test_agent_writes_a_file_through_the_runtime(world):
    spec = make_spec(tools=["fs.write"], memory={})
    provider = MockProvider([
        LLMResponse(tool_calls=[ToolCall("fs_write", {"path": "./out/plan.md", "content": "# Plan"})]),
        LLMResponse(content="Saved the plan."),
    ])
    result = run_agent(spec, "go", provider, base_dir=world)
    assert result.ok
    assert (world / "out" / "plan.md").read_text() == "# Plan"


import httpx


def web_ctx(world, handler):
    spec = AgentSpec.model_validate({
        "name": "web-agent",
        "goal": "Read web pages for me",
        "tools": ["http.fetch"],
        "permissions": {"network": ["example.com"]},
    })
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ToolContext(spec, world, http_client=client, resolver=lambda host: ["93.184.216.34"])


def fetch_tool(ctx, **args):
    return IMPLEMENTED["http.fetch"].func(ctx, args)


def ok_page(request):
    return httpx.Response(
        200,
        text="<html><body><p>Hello web</p></body></html>",
        headers={"content-type": "text/html"},
    )


def test_fetch_tool_returns_page_text(world):
    assert "Hello web" in fetch_tool(web_ctx(world, ok_page), url="https://example.com/")


def test_fetch_tool_turns_web_errors_into_tool_errors(world):
    with pytest.raises(ToolError, match="not an allowed website"):
        fetch_tool(web_ctx(world, ok_page), url="https://evil.com/")


def test_fetch_tool_needs_a_url(world):
    with pytest.raises(ToolError, match="url"):
        fetch_tool(web_ctx(world, ok_page))


def test_fetch_tool_rejects_bad_offset(world):
    with pytest.raises(ToolError, match="offset"):
        fetch_tool(web_ctx(world, ok_page), url="https://example.com/", offset="abc")


def test_leading_slash_is_read_as_the_project_folder_when_that_is_allowed(world):
    out = run_tool(world, "fs.write", path="/out/draft.json", content="{}")
    assert "Wrote" in out and (world / "out" / "draft.json").read_text() == "{}"


@pytest.mark.parametrize("path", ["/secret.txt", "/../secret.txt", "/sandbox/../secret.txt", str(Path("/etc/passwd"))])
def test_leading_slash_never_reaches_outside_the_allowed_folders(world, path):
    with pytest.raises(ToolError, match="Permission denied"):
        run_tool(world, "fs.read", path=path)
