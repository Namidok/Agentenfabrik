import pytest
from pydantic import ValidationError

from factory import sandbox
from factory.runtime import CODE_NUDGE
from factory.sandbox import SandboxError, check_cpp_name, run_cpp
from factory.schema import AgentSpec
from factory.tools import IMPLEMENTED, ToolContext, ToolError


def _compiler_works() -> bool:
    try:
        return "Compiled successfully" in run_cpp("int main(){}")
    except Exception:
        return False


needs_compiler = pytest.mark.skipif(not _compiler_works(), reason="no working C++ compiler")


@needs_compiler
def test_std_names_that_exist_are_found():
    assert check_cpp_name("std::vector").startswith("FOUND")
    assert check_cpp_name("std::string_view").startswith("FOUND")


@needs_compiler
def test_std_getopt_is_not_found():
    out = check_cpp_name("std::getopt")
    assert out.startswith("NOT FOUND")
    assert "getopt" in out
    assert "agent-cpp-" not in out


@needs_compiler
def test_posix_name_is_found_with_its_header():
    assert check_cpp_name("::getopt", "unistd.h").startswith("FOUND")
    assert check_cpp_name("::getopt", "<unistd.h>").startswith("FOUND")


@needs_compiler
def test_missing_header_is_reported():
    out = check_cpp_name("::foo", "definitely_not_a_header.h")
    assert out.startswith("HEADER MISSING")


@pytest.mark.parametrize("name", ["vector", "std::", "std::vec tor", "std::a; int x", "", "std::vector<int>"])
def test_bad_names_are_rejected(name):
    with pytest.raises(SandboxError, match="qualified"):
        check_cpp_name(name)


@pytest.mark.parametrize("header", ["../secret.h", "a/../b.h", "x>\n#include <y", "x.h;rm", "a b.h"])
def test_unsafe_headers_are_rejected(header):
    with pytest.raises(SandboxError, match="plain file name"):
        check_cpp_name("std::vector", header)


def make_spec():
    return AgentSpec.model_validate({
        "name": "cpp-agent",
        "goal": "Check whether C++ names exist",
        "tools": ["code.check_name"],
        "permissions": {"shell": True},
    })


def test_tool_passes_arguments_through(monkeypatch, tmp_path):
    seen = {}

    def fake(name, header=""):
        seen.update(name=name, header=header)
        return "FOUND: fake"

    monkeypatch.setattr(sandbox, "check_cpp_name", fake)
    ctx = ToolContext(make_spec(), tmp_path)
    out = IMPLEMENTED["code.check_name"].func(ctx, {"name": "std::vector", "header": "vector"})
    assert out == "FOUND: fake"
    assert seen == {"name": "std::vector", "header": "vector"}


def test_tool_needs_a_name(tmp_path):
    ctx = ToolContext(make_spec(), tmp_path)
    with pytest.raises(ToolError, match="name"):
        IMPLEMENTED["code.check_name"].func(ctx, {})


def test_tool_header_must_be_text(tmp_path):
    ctx = ToolContext(make_spec(), tmp_path)
    with pytest.raises(ToolError, match="header"):
        IMPLEMENTED["code.check_name"].func(ctx, {"name": "std::vector", "header": 5})


def test_tool_turns_sandbox_errors_into_tool_errors(monkeypatch, tmp_path):
    def boom(name, header=""):
        raise SandboxError("No C++ compiler was found.")

    monkeypatch.setattr(sandbox, "check_cpp_name", boom)
    ctx = ToolContext(make_spec(), tmp_path)
    with pytest.raises(ToolError, match="compiler"):
        IMPLEMENTED["code.check_name"].func(ctx, {"name": "std::vector"})


def test_tool_needs_the_shell_permission():
    with pytest.raises(ValidationError, match="permissions.shell"):
        AgentSpec.model_validate({
            "name": "cpp-agent",
            "goal": "Check whether C++ names exist",
            "tools": ["code.check_name"],
        })


def test_code_reminder_says_it_is_automatic():
    assert "not a message from the student" in CODE_NUDGE.lower()


@needs_compiler
def test_header_check_does_not_credit_other_headers():
    out = check_cpp_name("std::vector", "unistd.h")
    assert out.startswith("NOT FOUND")
    assert "unistd.h" in out.splitlines()[0]
    assert "Standard library headers alone: FOUND" in out


@needs_compiler
def test_header_check_reports_both_verdicts():
    out = check_cpp_name("::getopt", "unistd.h")
    assert out.splitlines()[0].startswith("FOUND")
    assert "Standard library headers alone:" in out
