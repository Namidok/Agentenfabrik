import pytest

from factory import sandbox
from factory.llm import LLMResponse, MockProvider, ToolCall
from factory.runtime import AgentSession
from factory.sandbox import SandboxError, run_cpp
from factory.schema import AgentSpec
from factory.tools import IMPLEMENTED, ToolContext, ToolError


def _compiler_works() -> bool:
    try:
        return "Compiled successfully" in run_cpp("int main(){}")
    except Exception:
        return False


needs_compiler = pytest.mark.skipif(not _compiler_works(), reason="no working C++ compiler")


@needs_compiler
def test_hello_world():
    out = run_cpp('#include <iostream>\nint main(){ std::cout << "hello"; }')
    assert "Compiled successfully" in out
    assert "exit code 0" in out
    assert "Output:\nhello" in out


@needs_compiler
def test_compile_error_is_reported_without_temp_paths():
    out = run_cpp("#include <iostream>\nint main(){ std::getopt(1, nullptr, \"\"); }")
    assert out.startswith("Compilation failed")
    assert "getopt" in out
    assert "agent-cpp-" not in out


@needs_compiler
def test_warnings_are_shown():
    out = run_cpp("int main(){ int unused; }")
    assert "Compiled successfully" in out
    assert "Compiler warnings" in out


@needs_compiler
def test_stdin_reaches_the_program():
    code = "#include <iostream>\n#include <string>\nint main(){ std::string s; std::cin >> s; std::cout << s << s; }"
    assert "Output:\nabab" in run_cpp(code, stdin="ab")


@needs_compiler
def test_exit_code_is_reported():
    assert "exit code 3" in run_cpp("int main(){ return 3; }")


@needs_compiler
def test_stderr_is_reported():
    out = run_cpp('#include <iostream>\nint main(){ std::cerr << "oops"; }')
    assert "Error output:\noops" in out


@needs_compiler
def test_infinite_loop_is_stopped():
    out = run_cpp("int main(){ while(true){} }", run_timeout=1)
    assert "stopped after 1 seconds" in out


@needs_compiler
def test_crash_is_explained():
    out = run_cpp("int main(){ int* p = nullptr; *p = 1; }")
    assert "crashed with" in out
    assert "invalid memory access" in out


@needs_compiler
def test_long_output_is_cut():
    code = '#include <iostream>\nint main(){ for(int i=0;i<10000;i++) std::cout << "x"; }'
    out = run_cpp(code)
    assert "output cut" in out
    assert len(out) < 6000


@needs_compiler
def test_program_does_not_see_secret_environment_variables(monkeypatch):
    monkeypatch.setenv("MY_SECRET_TOKEN", "hunter2")
    code = '#include <cstdlib>\n#include <iostream>\nint main(){ const char* v = std::getenv("MY_SECRET_TOKEN"); std::cout << (v ? v : "unset"); }'
    out = run_cpp(code)
    assert "Output:\nunset" in out
    assert "hunter2" not in out


def test_empty_and_oversized_code_are_rejected():
    with pytest.raises(SandboxError, match="No code"):
        run_cpp("   ")
    with pytest.raises(SandboxError, match="too long"):
        run_cpp("x" * 20_001)


def make_spec():
    return AgentSpec.model_validate({
        "name": "cpp-agent",
        "goal": "Teach C++ with examples",
        "tools": ["code.run"],
        "permissions": {"shell": True},
    })


def test_tool_passes_code_and_stdin_through(monkeypatch, tmp_path):
    seen = {}

    def fake(code, stdin=""):
        seen.update(code=code, stdin=stdin)
        return "fake result"

    monkeypatch.setattr(sandbox, "run_cpp", fake)
    ctx = ToolContext(make_spec(), tmp_path)
    out = IMPLEMENTED["code.run"].func(ctx, {"code": "int main(){}", "stdin": "5"})
    assert out == "fake result"
    assert seen == {"code": "int main(){}", "stdin": "5"}


def test_tool_needs_code(tmp_path):
    ctx = ToolContext(make_spec(), tmp_path)
    with pytest.raises(ToolError, match="code"):
        IMPLEMENTED["code.run"].func(ctx, {})


def test_tool_turns_sandbox_errors_into_tool_errors(monkeypatch, tmp_path):
    def boom(code, stdin=""):
        raise SandboxError("No C++ compiler was found.")

    monkeypatch.setattr(sandbox, "run_cpp", boom)
    ctx = ToolContext(make_spec(), tmp_path)
    with pytest.raises(ToolError, match="compiler"):
        IMPLEMENTED["code.run"].func(ctx, {"code": "int main(){}"})


def test_agent_can_use_code_run_in_a_session(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "run_cpp", lambda code, stdin="": "Compiled successfully.\nOutput:\n15")
    provider = MockProvider([
        LLMResponse(tool_calls=[ToolCall("code_run", {"code": "int main(){}"})]),
        LLMResponse(content="It prints 15."),
    ])
    r = AgentSession(make_spec(), provider, base_dir=tmp_path).send("Sum 1..5")
    assert r.ok and "15" in r.final_text
    tool_msgs = [m["content"] for m in provider.calls[-1]["messages"] if m["role"] == "tool"]
    assert tool_msgs == ["Compiled successfully.\nOutput:\n15"]
