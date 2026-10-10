import json

import pytest

from factory.interviewer import (
    TURN_SCHEMA,
    SpecBuildError,
    build_spec,
    draft_schema,
    interview_turn,
    permission_warnings,
    save_spec,
)
from factory.llm import LLMResponse, MockProvider
from factory.schema import AgentSpec, load_spec
from factory.tools import IMPLEMENTED

GOOD = {
    "name": "note-summarizer",
    "goal": "Summarize the text files in the notes folder.",
    "system_prompt": "You summarize notes. Never modify files.",
    "mode": "task",
    "tools": ["fs.list", "fs.read"],
    "fs_read": ["./notes"],
    "trigger_type": "manual",
}
TRANSCRIPT = [{"role": "user", "content": "I want a notes summarizer"}]


def jr(d) -> LLMResponse:
    return LLMResponse(content=json.dumps(d))


def spec_with(fs_read, fs_write=None) -> AgentSpec:
    return AgentSpec.model_validate({
        "name": "test-agent",
        "goal": "A goal that is long enough",
        "tools": ["fs.list"],
        "permissions": {"fs_read": fs_read, "fs_write": fs_write or []},
    })


def test_interview_turn_parses_reply_and_ready():
    mock = MockProvider([jr({"reply": "Which folder?", "ready": True})])
    assert interview_turn(mock, TRANSCRIPT) == ("Which folder?", True)


def test_interview_turn_survives_non_json():
    mock = MockProvider([LLMResponse(content="Which folder should it read?")])
    reply, ready = interview_turn(mock, TRANSCRIPT)
    assert reply == "Which folder should it read?"
    assert ready is False


def test_interview_turn_sends_schema_and_transcript():
    mock = MockProvider([jr({"reply": "ok", "ready": False})])
    interview_turn(mock, TRANSCRIPT)
    call = mock.calls[0]
    assert call["schema"] == TURN_SCHEMA
    assert call["messages"][0]["role"] == "system"
    assert call["messages"][-1]["content"] == "I want a notes summarizer"


def test_build_spec_valid():
    spec = build_spec(MockProvider([jr(GOOD)]), TRANSCRIPT)
    assert spec.name == "note-summarizer"
    assert spec.tools == ["fs.list", "fs.read"]
    assert spec.permissions.fs_read == ["./notes"]


def test_build_spec_retries_with_error_feedback():
    bad = {**GOOD, "fs_read": []}
    mock = MockProvider([jr(bad), jr(GOOD)])
    spec = build_spec(mock, TRANSCRIPT)
    assert spec.name == "note-summarizer"
    assert len(mock.calls) == 2
    assert "needs permissions.fs_read" in str(mock.calls[1]["messages"])


def test_build_spec_retries_on_bad_json():
    mock = MockProvider([LLMResponse(content="not json at all"), jr(GOOD)])
    assert build_spec(mock, TRANSCRIPT).name == "note-summarizer"
    assert "not valid JSON" in str(mock.calls[1]["messages"])


def test_build_spec_gives_up_after_three_attempts():
    bad = {**GOOD, "name": "Bad Name!"}
    mock = MockProvider([jr(bad), jr(bad), jr(bad)])
    with pytest.raises(SpecBuildError, match="3 attempts"):
        build_spec(mock, TRANSCRIPT)


def test_schedule_trigger_is_mapped():
    draft = {**GOOD, "trigger_type": "schedule", "cron": "0 8 * * *"}
    spec = build_spec(MockProvider([jr(draft)]), TRANSCRIPT)
    assert spec.trigger.type == "schedule"
    assert spec.trigger.cron == "0 8 * * *"


def test_draft_schema_offers_only_implemented_tools():
    enum = draft_schema()["properties"]["tools"]["items"]["enum"]
    assert enum == sorted(IMPLEMENTED)


def test_warning_for_whole_disk(tmp_path):
    warnings = permission_warnings(spec_with(["/"]), tmp_path)
    assert any("whole disk" in w for w in warnings)


def test_warning_for_home_folder(tmp_path):
    warnings = permission_warnings(spec_with(["~"]), tmp_path)
    assert any("home folder" in w for w in warnings)


def test_no_warning_for_a_normal_folder(tmp_path):
    assert permission_warnings(spec_with(["./notes"]), tmp_path) == []


def test_save_spec_roundtrip(tmp_path):
    spec = build_spec(MockProvider([jr(GOOD)]), TRANSCRIPT)
    path = save_spec(spec, tmp_path / "specs")
    assert path.name == "note-summarizer.yaml"
    assert load_spec(path) == spec


from factory.interviewer import capability_notes


def user(*texts):
    return [{"role": "user", "content": t} for t in texts]


def test_notes_flag_write_request():
    notes = capability_notes(user("it can modify files, i don't mind"), spec_with(["./notes"]))
    assert any("write, change or delete files" in n for n in notes)


def test_notes_flag_pdf_and_internet():
    notes = capability_notes(user("summarize my pdf files from the internet"), spec_with(["./notes"]))
    assert any("PDF" in n for n in notes)
    assert any("internet" in n for n in notes)


def test_notes_ignore_negated_mentions():
    text = "it must never access the internet or modify files"
    assert capability_notes(user(text), spec_with(["./notes"])) == []


def test_notes_silent_when_spec_has_the_tool():
    spec = AgentSpec.model_validate({
        "name": "writer-agent",
        "goal": "A goal that is long enough",
        "tools": ["fs.write"],
        "permissions": {"fs_write": ["./out"]},
    })
    assert capability_notes(user("save the results to a file"), spec) == []


def test_draft_maps_write_folders_and_notes():
    draft = {**GOOD, "tools": ["fs.list", "fs.write", "notes.append"], "fs_write": ["./out"]}
    spec = build_spec(MockProvider([jr(draft)]), TRANSCRIPT)
    assert spec.permissions.fs_write == ["./out"]
    assert spec.memory.notes is True


def test_write_tool_without_write_folder_is_retried():
    bad = {**GOOD, "tools": ["fs.list", "fs.write"], "fs_write": []}
    mock = MockProvider([jr(bad), jr({**bad, "fs_write": ["./out"]})])
    spec = build_spec(mock, TRANSCRIPT)
    assert spec.permissions.fs_write == ["./out"]
    assert "needs permissions.fs_write" in str(mock.calls[1]["messages"])


def test_warning_when_overwrite_is_allowed(tmp_path):
    spec = AgentSpec.model_validate({
        "name": "test-agent",
        "goal": "A goal that is long enough",
        "tools": ["fs.list"],
        "permissions": {"fs_read": ["./a"], "fs_write": ["./out"], "allow_overwrite": True},
    })
    assert any("replace existing files" in w for w in permission_warnings(spec, tmp_path))


def test_draft_maps_network_domains():
    draft = {**GOOD, "tools": ["fs.list", "http.fetch"], "network": ["example.com"]}
    spec = build_spec(MockProvider([jr(draft)]), TRANSCRIPT)
    assert spec.permissions.network == ["example.com"]


def test_warning_lists_allowed_websites(tmp_path):
    spec = AgentSpec.model_validate({
        "name": "test-agent",
        "goal": "A goal that is long enough",
        "tools": ["http.fetch"],
        "permissions": {"network": ["example.com"]},
    })
    assert any("example.com" in w for w in permission_warnings(spec, tmp_path))


def test_code_run_tool_turns_on_the_shell_permission():
    draft = {**GOOD, "tools": ["fs.list", "code.run"]}
    spec = build_spec(MockProvider([jr(draft)]), TRANSCRIPT)
    assert spec.permissions.shell is True


def test_shell_warning_says_it_is_not_isolated(tmp_path):
    spec = AgentSpec.model_validate({
        "name": "test-agent",
        "goal": "A goal that is long enough",
        "tools": ["code.run"],
        "permissions": {"shell": True},
    })
    assert any("not isolated" in w for w in permission_warnings(spec, tmp_path))


def test_check_name_tool_turns_on_the_shell_permission():
    draft = {**GOOD, "tools": ["fs.list", "code.check_name"]}
    spec = build_spec(MockProvider([jr(draft)]), TRANSCRIPT)
    assert spec.permissions.shell is True
