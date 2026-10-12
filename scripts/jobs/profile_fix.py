"""Apply the user's corrections to the profile by ID and save the result as a new version (never overwrites).

Arguments (JSON), any of:
  {"set":    [{"id": "F003", "text": "..."}, {"id": "E1", "field": "dates", "value": "May 2023 - Aug 2025"}],
   "remove": ["F006"],
   "add":    [{"to": "E1", "text": "a new bullet"}, {"to": "summary", "text": "a new sentence"}]}
IDs: F### facts (bullets and summary sentences), S# skills ("items" or "label"), E# jobs, CP# projects,
ED# education, "header" (fields name, headline, contact).
Prints: {"ok", "file", "changed", "new_ids"} or {"ok": false, "error"}"""
from __future__ import annotations

import re

from common import DATA, ME, args, done, fail, latest, next_version, read_json, rel, today, write_json, write_profile

EDITABLE = {"title", "org", "location", "dates", "name", "tagline", "link", "degree", "school", "note", "label", "items", "headline"}


def all_facts(p: dict) -> list[dict]:
    return p["summary"] + [b for e in p["experience"] + p["projects"] for b in e["bullets"]]


def main() -> None:
    a = args()
    path = latest(ME, "profile")
    if not path:
        fail("No profile yet: run extract_cv first.")
    p = read_json(path)
    facts = {f["id"]: f for f in all_facts(p)}
    entries = {e["id"]: e for e in p["skills"] + p["experience"] + p["projects"] + p["education"]}
    changed, new_ids = [], []
    for change in a.get("set", []):
        cid = str(change.get("id", ""))
        if cid in facts and "text" in change:
            facts[cid]["text"] = str(change["text"]).strip()
        elif cid == "header" and change.get("field") in ("name", "headline", "contact"):
            p["header"][change["field"]] = change["value"]
        elif cid in entries and change.get("field") in EDITABLE:
            entries[cid][change["field"]] = change["value"]
        else:
            fail(f"Cannot change '{cid}' that way. Facts take 'text'; entries take 'field' and 'value'.")
        changed.append(cid)
    for rid in a.get("remove", []):
        for holder in [p["summary"]] + [e["bullets"] for e in p["experience"] + p["projects"]]:
            holder[:] = [f for f in holder if f["id"] != rid]
        if rid not in facts:
            fail(f"No fact with ID {rid}.")
        changed.append(rid)
    top = max([int(f["id"][1:]) for f in all_facts(p)] + [int(k[1:]) for k in facts], default=0)
    for item in a.get("add", []):
        target, text = str(item.get("to", "")), str(item.get("text", "")).strip()
        if not text:
            fail("Each added item needs 'text'.")
        top += 1
        fact = {"id": f"F{top:03d}", "text": text}
        if target == "summary":
            p["summary"].append(fact)
        elif target in entries and "bullets" in entries[target]:
            entries[target]["bullets"].append(fact)
        else:
            fail(f"Cannot add to '{target}': use 'summary' or a job or project ID such as E1 or CP2.")
        new_ids.append(fact["id"])
    if not changed and not new_ids:
        fail("Nothing to change: give set, remove or add.")
    p["version"] = int(re.search(r"_v(\d+)", path.name).group(1)) + 1
    p["edited"] = today()
    out = write_profile(p)
    done({"ok": True, "file": rel(out), "facts_file": rel(out.with_suffix(".md")), "changed": changed, "new_ids": new_ids})


if __name__ == "__main__":
    main()
