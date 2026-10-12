import json

import pytest

from factory import script_tool
from factory.schema import AgentSpec
from factory.tools import IMPLEMENTED, ToolContext, ToolError


def make_spec(**overrides):
    base = dict(name="job-desk", goal="Run the job search programs", tools=["script.run"],
                permissions={"shell": True})
    base.update(overrides)
    return AgentSpec.model_validate(base)


@pytest.fixture
def world(tmp_path, monkeypatch):
    folder = tmp_path / "scripts" / "jobs"
    folder.mkdir(parents=True)
    (folder / "echo.py").write_text(
        "import json, sys\nargs = json.loads(sys.stdin.read() or '{}')\nprint(json.dumps({'ok': True, 'got': args}))\n")
    (folder / "crash.py").write_text("import sys\nsys.stderr.write('Traceback\\nValueError: bad input\\n')\nsys.exit(2)\n")
    (folder / "slow.py").write_text("import time\ntime.sleep(5)\n")
    (folder / "loud.py").write_text("print('x' * 5000)\n")
    monkeypatch.setattr(script_tool, "SCRIPTS", {
        "echo": ("scripts/jobs/echo.py", 10, "echo"), "crash": ("scripts/jobs/crash.py", 10, "crash"),
        "slow": ("scripts/jobs/slow.py", 1, "slow"), "loud": ("scripts/jobs/loud.py", 10, "loud"),
        "gone": ("scripts/jobs/gone.py", 10, "missing file"),
    })
    return tmp_path


def run(world, **args):
    return IMPLEMENTED["script.run"].func(ToolContext(make_spec(), world), args)


def test_runs_an_allowlisted_script_with_json_arguments_on_stdin(world):
    out = json.loads(run(world, script="echo", args={"top": 3, "ids": ["li-1"]}))
    assert out == {"ok": True, "got": {"top": 3, "ids": ["li-1"]}}


def test_arguments_sent_as_text_are_parsed(world):
    assert json.loads(run(world, script="echo", args='{"top": 2}'))["got"] == {"top": 2}
    assert json.loads(run(world, script="echo"))["got"] == {}


def test_unknown_script_is_refused(world):
    with pytest.raises(ToolError, match="Unknown script"):
        run(world, script="rm -rf /")


def test_arguments_must_be_an_object(world):
    with pytest.raises(ToolError, match="JSON object"):
        run(world, script="echo", args="[1, 2]")
    with pytest.raises(ToolError, match="JSON object"):
        run(world, script="echo", args="not json")


def test_failure_reports_only_the_last_error_line(world):
    with pytest.raises(ToolError, match="exit 2.*ValueError: bad input"):
        run(world, script="crash")


def test_slow_script_is_stopped(world):
    with pytest.raises(ToolError, match="did not finish within 1 seconds"):
        run(world, script="slow")


def test_long_output_is_cut(world):
    out = run(world, script="loud")
    assert len(out) <= script_tool.MAX_OUTPUT + 10 and out.endswith("(cut)")


def test_missing_program_is_reported(world):
    with pytest.raises(ToolError, match="missing"):
        run(world, script="gone")


def test_spec_needs_shell_permission_for_script_run():
    with pytest.raises(ValueError, match="shell"):
        make_spec(permissions={})


def test_real_allowlist_points_at_existing_programs():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for name, (path, timeout, _) in script_tool.SCRIPTS.items():
        assert (root / path).is_file(), name
        assert timeout >= 30
    assert script_tool.SCRIPTS["scrape_jobs"][1] >= 600


def test_successful_runs_are_written_to_the_notes(world):
    spec = make_spec(memory={"notes": True})
    ctx = ToolContext(spec, world)
    IMPLEMENTED["script.run"].func(ctx, {"script": "echo", "args": {"file": "data/x_v1.json"}})
    notes = ctx.notes_file.read_text()
    assert "ran echo" in notes and "data/x_v1.json" in notes
    with pytest.raises(ToolError):
        IMPLEMENTED["script.run"].func(ctx, {"script": "crash"})
    assert ctx.notes_file.read_text() == notes  # failures are not remembered


def test_runs_are_not_noted_without_notes_memory(world):
    ctx = ToolContext(make_spec(), world)
    IMPLEMENTED["script.run"].func(ctx, {"script": "echo"})
    assert not ctx.notes_file.exists()
