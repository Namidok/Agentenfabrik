"""Turn the automatic job search on or off. The app (serve.py) starts it every few hours while it is open.

  .venv/bin/python scripts/jobs/schedule.py '{"action": "install", "every_hours": 3}'
  .venv/bin/python scripts/jobs/schedule.py '{"action": "status"}'
  .venv/bin/python scripts/jobs/schedule.py '{"action": "remove"}'

Runs at fixed times (every 3 hours: 00:00, 03:00, ... 21:00). If the Mac was asleep at that time, the missed run
starts once when it wakes up. Every run stops before writing a CV and waits for the user's OK in the Job Desk panel.
The setting is data/jobs/schedule.json. (A macOS LaunchAgent cannot be used: background jobs started by macOS may
not read ~/Downloads, where this project lives; the old one is removed here.)
Prints: {"ok", "installed", "times", "note"}"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from common import DATA, args, done, fail

SETTING = DATA / "schedule.json"
EVERY = (1, 2, 3, 4, 6, 8, 12, 24)
NOTE = "Runs while the AgentFactory app is open."
OLD_LABEL = "com.agentfactory.jobsearch"
OLD_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{OLD_LABEL}.plist"


def remove_old_launch_agent() -> None:
    if OLD_PLIST.exists():
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{OLD_LABEL}"], capture_output=True)
        OLD_PLIST.unlink(missing_ok=True)


def every_hours() -> int | None:
    try:
        every = int(json.loads(SETTING.read_text(encoding="utf-8"))["every_hours"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return every if every in EVERY else None


def times(every: int | None) -> list[str]:
    return [f"{h:02d}:00" for h in range(0, 24, every)] if every else []


def main() -> None:
    a = args()
    action = a.get("action", "status")
    remove_old_launch_agent()
    if action == "install":
        every = int(a.get("every_hours", 3))
        if every not in EVERY:
            fail("every_hours must divide 24: 1, 2, 3, 4, 6, 8, 12 or 24.")
        DATA.mkdir(parents=True, exist_ok=True)
        SETTING.write_text(json.dumps({"every_hours": every}), encoding="utf-8")
        done({"ok": True, "installed": True, "times": times(every), "note": NOTE})
    elif action == "remove":
        SETTING.unlink(missing_ok=True)
        done({"ok": True, "installed": False})
    elif action == "status":
        every = every_hours()
        done({"ok": True, "installed": every is not None, "times": times(every), "note": NOTE})
    else:
        fail("action must be install, remove or status.")


if __name__ == "__main__":
    main()
