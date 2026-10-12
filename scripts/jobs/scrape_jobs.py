"""Search jobs from the saved preferences and store each new posting in its own file.

The agent that starts this only gets counts and job IDs back, never posting text: postings are untrusted
data and are only read by agents that cannot use the network, run programs or write outside drafts.

Writes data/jobs/postings/<id>.json (description cut to about 3000 characters), data/jobs/jobs_vN.json (an
index of this run's new jobs, without descriptions) and data/jobs/seen.json (every job ever seen, to skip repeats).

Arguments (JSON, optional): {"source": "linkedin", "max_requests": 30, "queries": ["..."], "age": "week",
                             "hours": 24, "pages": 1}  (hours overrides age; pages = result pages of 10 per query)
Prints: {"ok", "requests_used", "found", "new", "saved", "ids", "stopped", "file"}"""
from __future__ import annotations

import json

from common import DATA, ME, POSTINGS, args, clip, done, fail, latest, next_version, read_json, rel, today, write_json
from sources import SOURCES, Blocked, OutOfBudget, Pacer

DEFAULT_SEARCH = {
    "queries": ["Machine Learning Intern", "AI Intern", "Data Engineering Intern",
                "Praktikum Machine Learning", "Praktikum Künstliche Intelligenz", "Praktikum Data Engineering"],
    "location": "Germany", "age": "week", "job_types": ["internship"], "workplace": [],
}


def main() -> None:
    a = args()
    prefs_path = latest(ME, "preferences")
    search = dict(DEFAULT_SEARCH)
    if prefs_path:
        search.update(read_json(prefs_path).get("search") or {})
    for key in ("queries", "location", "age", "hours", "job_types", "workplace"):
        if key in a:
            search[key] = a[key]
    source_name = a.get("source", "linkedin")
    if source_name not in SOURCES:
        fail(f"Unknown source '{source_name}'. Known: {', '.join(SOURCES)}")
    pacer = Pacer(max_requests=min(int(a.get("max_requests", 30)), 30))  # never more than 30 requests per run
    source = SOURCES[source_name](pacer)

    seen_file = DATA / "seen.json"
    seen: dict[str, str] = read_json(seen_file) if seen_file.exists() else {}
    found: dict[str, dict] = {}
    saved: list[dict] = []
    stopped = ""
    try:
        pages = max(1, min(int(a.get("pages", 1)), 3))
        for query in search["queries"]:
            for page in range(pages):
                stubs = source.search({**search, "keywords": query}, start=page * 10)
                for stub in stubs:
                    found.setdefault(stub["id"], stub)  # the same job from two searches counts once
                if len(stubs) < 10:  # a short page is the last one
                    break
        for stub in [s for s in found.values() if s["id"] not in seen]:
            job = source.detail(stub)
            POSTINGS.mkdir(parents=True, exist_ok=True)
            job["description"] = clip(job.get("description", ""))
            job["fetched"] = today()
            (POSTINGS / f"{job['id']}.json").write_text(json.dumps(job, indent=1, ensure_ascii=False), encoding="utf-8")
            seen[job["id"]] = today()
            saved.append(job)
    except OutOfBudget:
        stopped = f"request budget of {pacer.max_requests} used; jobs not opened yet come next run"
    except Blocked as e:
        stopped = f"blocked: {e}"
    DATA.mkdir(parents=True, exist_ok=True)
    seen_file.write_text(json.dumps(seen, indent=0), encoding="utf-8")  # only jobs actually opened are skipped later
    index = [{k: j[k] for k in ("id", "title", "company", "location", "posted", "link")} for j in saved]
    path = write_json(next_version(DATA, "jobs"), {"version": 1, "fetched": today(), "source": source_name,
                                                   "search": search, "requests_used": pacer.used, "jobs": index})
    done({"ok": True, "source": source_name, "requests_used": pacer.used, "found": len(found),
          "already_seen": len([s for s in found.values() if s["id"] in seen]) - len(saved), "saved": len(saved), "ids": [j["id"] for j in saved], "stopped": stopped, "file": rel(path),
          "note": "Automated LinkedIn access conflicts with LinkedIn's terms: personal, low-volume use only."})


if __name__ == "__main__":
    main()
