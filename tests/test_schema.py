from pathlib import Path

import pytest
from pydantic import ValidationError

from factory.schema import AgentSpec, load_spec

BASE = dict(
    name="hello-agent",
    goal="List files in a folder and summarize them",
    tools=["fs.list", "fs.read"],
    permissions={"fs_read": ["./sandbox"]},
)


def make(**overrides):
    return AgentSpec.model_validate({**BASE, **overrides})


def test_valid_minimal():
    spec = make()
    assert spec.model.name == "qwen3:8b"
    assert spec.mode == "task"


def test_hello_yaml_loads():
    path = Path(__file__).parent.parent / "specs" / "hello.yaml"
    if not path.exists():
        import pytest
        pytest.skip("specs/hello.yaml was removed by the user")
    spec = load_spec(path)
    assert spec.name == "hello-agent"
    assert spec.tools == ["fs.list", "fs.read"]


def test_bad_name():
    with pytest.raises(ValidationError, match="lowercase slug"):
        make(name="Hello Agent!")


def test_unknown_tool():
    with pytest.raises(ValidationError, match="unknown tool"):
        make(tools=["fs.read", "teleport.home"])


def test_duplicate_tools():
    with pytest.raises(ValidationError, match="duplicate"):
        make(tools=["fs.read", "fs.read"])


def test_too_many_tools():
    with pytest.raises(ValidationError, match="at most"):
        make(
            tools=["fs.read", "fs.list", "fs.write", "fs.move",
                   "http.fetch", "code.run", "notes.read"],
            permissions={"fs_read": ["./a"], "fs_write": ["./b"],
                         "network": ["example.com"], "shell": True},
            memory={"notes": True},
        )


def test_tool_needs_permission():
    with pytest.raises(ValidationError, match="needs permissions.fs_write"):
        make(tools=["fs.write"])


def test_schedule_needs_cron():
    with pytest.raises(ValidationError, match="cron"):
        make(trigger={"type": "schedule"})


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        make(colour="blue")


def test_network_wildcard_rejected():
    with pytest.raises(ValidationError, match="plain domains"):
        make(tools=["http.fetch"], permissions={"network": ["*"]})
