"""Turn the automatic job search on or off: a macOS LaunchAgent that starts pipeline.py every few hours.

  .venv/bin/python scripts/jobs/schedule.py '{"action": "install", "every_hours": 3}'
  .venv/bin/python scripts/jobs/schedule.py '{"action": "status"}'
  .venv/bin/python scripts/jobs/schedule.py '{"action": "remove"}'

Runs at fixed times (every 3 hours: 00:00, 03:00, ... 21:00). If the Mac is asleep at that time, macOS starts
the missed run once when it wakes up; the first run of a day searches the last 24 hours. Ollama must be running
(it is a brew service). The log is data/jobs/pipeline.log.
Prints: {"ok", "installed", "times", "plist"}"""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from common import DATA, ROOT, args, done, fail

LABEL = "com.agentfactory.jobsearch"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
PIPELINE = Path(__file__).resolve().parent / "pipeline.py"


def domain() -> str:
    return f"gui/{os.getuid()}"


def loaded() -> bool:
    return subprocess.run(["launchctl", "print", f"{domain()}/{LABEL}"], capture_output=True).returncode == 0


def plist(every: int) -> dict:
    python = ROOT / ".venv" / "bin" / "python"
    return {
        "Label": LABEL,
        "ProgramArguments": [str(python if python.exists() else sys.executable), str(PIPELINE)],
        "WorkingDirectory": str(PIPELINE.parent),
        "StartCalendarInterval": [{"Hour": h, "Minute": 0} for h in range(0, 24, every)],
        "StandardOutPath": str(DATA / "pipeline.log"),
        "StandardErrorPath": str(DATA / "pipeline.log"),
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        "ProcessType": "Background",
    }


def main() -> None:
    a = args()
    action = a.get("action", "status")
    if action == "install":
        every = int(a.get("every_hours", 3))
        if every not in (1, 2, 3, 4, 6, 8, 12, 24):
            fail("every_hours must divide 24: 1, 2, 3, 4, 6, 8, 12 or 24.")
        DATA.mkdir(parents=True, exist_ok=True)
        PLIST.parent.mkdir(parents=True, exist_ok=True)
        if loaded():
            subprocess.run(["launchctl", "bootout", f"{domain()}/{LABEL}"], capture_output=True)
        with PLIST.open("wb") as f:
            plistlib.dump(plist(every), f)
        r = subprocess.run(["launchctl", "bootstrap", domain(), str(PLIST)], capture_output=True, text=True)
        if r.returncode != 0:
            fail(f"macOS refused the schedule: {r.stderr.strip()[:200]}")
        done({"ok": True, "installed": True, "times": [f"{h:02d}:00" for h in range(0, 24, every)], "plist": str(PLIST)})
    elif action == "remove":
        if loaded():
            subprocess.run(["launchctl", "bootout", f"{domain()}/{LABEL}"], capture_output=True)
        PLIST.unlink(missing_ok=True)
        done({"ok": True, "installed": False})
    elif action == "status":
        times = []
        if PLIST.exists():
            with PLIST.open("rb") as f:
                times = [f"{t['Hour']:02d}:00" for t in plistlib.load(f).get("StartCalendarInterval", [])]
        done({"ok": True, "installed": PLIST.exists() and loaded(), "times": times, "plist": str(PLIST)})
    else:
        fail("action must be install, remove or status.")


if __name__ == "__main__":
    main()
