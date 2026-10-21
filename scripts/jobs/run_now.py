"""Start a run of pipeline.py now, in the background, and return at once.

{} searches and ranks (about 5-25 minutes), then the good matches wait for the user's OK in the Job Desk panel.
{"approve": [IDs], "decline": [IDs]} writes, checks and prints the documents for the approved jobs.
{"jobs": ["li-123"]} only (re)ranks those jobs without searching. A Mac notification says when a run is done.
Prints: {"ok", "started", "log"} or {"ok": false, "error"}"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from common import DATA, args, done, fail, rel

LOCK = DATA / "pipeline.lock"


def main() -> None:
    a = args()
    if LOCK.exists():
        try:
            os.kill(int(LOCK.read_text().strip() or 0), 0)
            fail("An automatic run is already going; wait for its notification.")
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    DATA.mkdir(parents=True, exist_ok=True)
    log = DATA / "pipeline.log"
    with log.open("a", encoding="utf-8") as out:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve().parent / "pipeline.py"), json.dumps(a)],
                         stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
                         cwd=Path(__file__).resolve().parent)
    done({"ok": True, "started": True, "log": rel(log),
          "note": "Runs in the background for about 5-25 minutes; a Mac notification says when it is done."})


if __name__ == "__main__":
    main()
