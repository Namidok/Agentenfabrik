"""script.run: start one of a fixed list of Python programs in scripts/ and return its short JSON summary.

The model only picks a name from SCRIPTS and passes a JSON object of arguments; it never writes code or
command lines. The arguments go to the program on stdin, and only its stdout (one JSON summary, cut to
MAX_OUTPUT characters) comes back, so the job programs can keep posting text out of the conversation.
Needs permissions.shell, because the programs run on this computer with the user's rights.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from typing import Any

MAX_OUTPUT = 2000
MAX_ARGS = 20_000  # characters of JSON arguments

# name -> (file under the project folder, timeout in seconds, what it does)
SCRIPTS: dict[str, tuple[str, int, str]] = {
    "extract_cv": ("scripts/jobs/extract_cv.py", 180, "read inputs/master_cv.pdf into data/jobs/profile_vN.json"),
    "profile_fix": ("scripts/jobs/profile_fix.py", 30, "correct profile facts by ID (set, remove, add) into a new profile version"),
    "fetch_github": ("scripts/jobs/fetch_github.py", 600, "catalogue a GitHub user's public repos into data/jobs/projects_vN.json"),
    "save_preferences": ("scripts/jobs/save_preferences.py", 30, "save job preferences into data/jobs/preferences_vN.json"),
    "scrape_jobs": ("scripts/jobs/scrape_jobs.py", 900, "search LinkedIn (max 30 requests) and save new postings; returns counts and IDs"),
    "shortlist": ("scripts/jobs/shortlist.py", 60, "score saved postings against the preferences; returns IDs, scores and flags"),
    "prepare": ("scripts/jobs/prepare.py", 30, "write the job brief and your facts for one job ID, for the Application Writer"),
    "render": ("scripts/jobs/render.py", 180, "check a draft in output/drafts and print the CV and cover letter PDFs"),
    "run_now": ("scripts/jobs/run_now.py", 30, "start the job search now in the background: {} searches and ranks, then the good matches wait for the user's OK; {\"approve\": [IDs], \"decline\": [IDs]} writes and checks the documents"),
    "schedule": ("scripts/jobs/schedule.py", 30, "turn the automatic run every few hours on or off: {\"action\": \"install\" | \"remove\" | \"status\", \"every_hours\": 3}"),
    "selftest_template": ("scripts/jobs/selftest_template.py", 300, "re-check that the CV template still matches the master CV"),
}


def _error(message: str) -> Exception:
    from factory.tools import ToolError  # imported late: tools.py imports this module

    return ToolError(message)


def script_run(ctx: Any, args: dict[str, Any]) -> str:
    name = args.get("script")
    if name not in SCRIPTS:
        raise _error(f"Unknown script '{name}'. Allowed: {', '.join(SCRIPTS)}")
    payload = args.get("args") or {}
    if isinstance(payload, str):  # small models sometimes send the object as text
        try:
            payload = json.loads(payload) if payload.strip() else {}
        except ValueError:
            raise _error("Argument 'args' must be a JSON object, for example {\"top\": 10}.")
    if not isinstance(payload, dict):
        raise _error("Argument 'args' must be a JSON object, for example {\"top\": 10}.")
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) > MAX_ARGS:
        raise _error(f"The arguments are too long ({len(text)} characters, at most {MAX_ARGS}).")
    rel_path, timeout, _ = SCRIPTS[name]
    path = (ctx.base_dir / rel_path).resolve()
    if not path.is_file():
        raise _error(f"The program for '{name}' is missing: {rel_path}")
    try:
        proc = subprocess.run([sys.executable, "-E", "-s", str(path)], input=text, capture_output=True, text=True,
                              timeout=timeout, cwd=path.parent)
    except subprocess.TimeoutExpired:
        raise _error(f"'{name}' did not finish within {timeout} seconds and was stopped.")
    out = proc.stdout.strip()
    if not out:
        last = (proc.stderr.strip().splitlines() or ["no output"])[-1]
        raise _error(f"'{name}' failed (exit {proc.returncode}): {last[:300]}")
    _remember(ctx, name, out)
    return out if len(out) <= MAX_OUTPUT else out[:MAX_OUTPUT] + " …(cut)"


def _remember(ctx: Any, name: str, out: str) -> None:
    """One line per successful run in the agent's notes, so the next chat knows what was done (small models forget
    to write notes). The programs never print posting text, so neither do the notes."""
    if not getattr(ctx.spec.memory, "notes", False):
        return
    try:
        summary = json.loads(out.splitlines()[-1])
    except ValueError:
        return
    if not isinstance(summary, dict) or summary.get("ok") is not True:
        return
    keep = {k: v for k, v in summary.items() if k not in ("ok", "note", "next", "html", "top", "ids", "missing", "warnings")}
    line = f"- {date.today().isoformat()} ran {name}: {json.dumps(keep, ensure_ascii=False)[:300]}\n"
    try:
        ctx.notes_file.parent.mkdir(parents=True, exist_ok=True)
        with ctx.notes_file.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


TOOLS = {
    "script.run": (
        "Run one of the job-search programs on this computer and get its short JSON summary. Programs: "
        + "; ".join(f"{n}: {d}" for n, (_, _, d) in SCRIPTS.items()) + ".",
        {"type": "object", "properties": {
            "script": {"type": "string", "enum": list(SCRIPTS), "description": "Which program to run"},
            "args": {"type": "object", "description": "The program's arguments as a JSON object; {} for none"}},
         "required": ["script"]},
        script_run,
    ),
}
