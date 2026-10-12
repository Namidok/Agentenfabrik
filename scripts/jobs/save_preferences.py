"""Save the user's job preferences (from the Job Desk interview) as data/jobs/preferences_vN.json.

The arguments are the preferences themselves; they are checked against schemas/preferences.schema.json and
merged over the previous version, so the interview can fill them in a few answers at a time.

Arguments (JSON): {"location": "Germany", "target_roles": [...], "seniority": ["internship"], "search": {...}, ...}
Prints: {"ok", "file", "missing"} or {"ok": false, "problems": [...]}"""
from __future__ import annotations

from common import DATA, ME, args, check_schema, done, fail, latest, load_schema, next_version, read_json, rel, today, write_json

ASK_ABOUT = ["relocation", "work_authorization", "languages", "career_stage", "workplace", "salary",
             "deal_breakers", "energizers", "drainers", "urgency", "keywords_include", "keywords_exclude"]


def main() -> None:
    new = args()
    previous = latest(ME, "preferences")
    merged = {k: v for k, v in (read_json(previous) if previous else {}).items() if k not in ("version", "saved")}
    for key, value in new.items():
        if key == "search" and isinstance(value, dict):
            merged["search"] = {**merged.get("search", {}), **value}
        else:
            merged[key] = value
    problems = check_schema(merged, load_schema("preferences"))
    if problems:
        fail("The preferences do not fit the schema; fix these and call again.", problems=problems[:8])
    version = int(previous.stem.rsplit("_v", 1)[1]) + 1 if previous else 1
    path = write_json(next_version(ME, "preferences"), {"version": version, "saved": today(), **merged})
    done({"ok": True, "file": rel(path), "missing": [k for k in ASK_ABOUT if not merged.get(k)]})


if __name__ == "__main__":
    main()
