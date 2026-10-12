"""The whole job search in one run: started every 3 hours by macOS (see schedule.py), from Job Desk ("run now"),
or by hand:  .venv/bin/python scripts/jobs/pipeline.py ['{"jobs": ["li-123"], "skip_scrape": true}']

  1. Job Desk      search LinkedIn: the last 24 h on the first run of a day, otherwise since the last run
                   (seen jobs are skipped), then the keyword score of every new job
  2. Job Matcher   rank each new job against your profile: requirements, the facts that show them, gaps, fit 0-100
  3. CV Writer     for each good match (verdict apply, fit >= min_fit, German not a blocker): pick the facts for
                   the CV, then write the cover letter
  4. CV Reviewer   program checks (numbers, generic words, invented availability, length) and a model review;
                   one revision round; anything still unsupported is removed
  5. render        both PDFs in the master CV design, a row in output/tracker.csv
  6. report        output/runs/<date>_<time>.md, the ranked list (output/ranked_jobs.md and data/jobs/ranked.md),
                   a line in Job Desk's notes, and a Mac notification. Nothing is ever sent anywhere.

Settings (optional) in the preferences: "availability": "from March 2027 for 6 months", and
"automation": {"min_fit": 70, "max_drafts_per_run": 3, "max_matches_per_run": 12}.
The last printed line is a JSON summary (for script.run)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from common import DATA, ME, OUTPUT, POSTINGS, ROOT, args, latest, next_version, read_json, rel, today, write_json
import auto_agents as agents
from prepare import relevant_projects
from render import source_texts

HERE = Path(__file__).resolve().parent
MATCHES = DATA / "matches"
STATE = DATA / "pipeline_state.json"
LOCK = DATA / "pipeline.lock"
RUNS = OUTPUT / "runs"
DEFAULTS = {"min_fit": 70, "max_drafts_per_run": 3, "max_matches_per_run": 12, "min_keyword_score": 40}
SKIP_FLAGS = {"excluded_keyword", "senior"}
GERMAN_OK = {"B2", "C1", "C2", "native"}


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def run_script(name: str, arguments: dict[str, Any], timeout: int = 900) -> dict[str, Any]:
    proc = subprocess.run([sys.executable, "-E", "-s", str(HERE / f"{name}.py"), json.dumps(arguments)],
                          capture_output=True, text=True, timeout=timeout, cwd=HERE)
    lines = proc.stdout.strip().splitlines()
    try:
        return json.loads(lines[-1]) if lines else {"ok": False, "error": proc.stderr.strip()[-300:]}
    except ValueError:
        return {"ok": False, "error": lines[-1][:300]}


# ---------- one run at a time, and when the last one was ----------

def take_lock() -> bool:
    DATA.mkdir(parents=True, exist_ok=True)
    if LOCK.exists():
        try:
            os.kill(int(LOCK.read_text().strip() or 0), 0)
            return False  # another run is still going
        except (ValueError, ProcessLookupError, PermissionError):
            pass  # left over from a run that crashed
    LOCK.write_text(str(os.getpid()))
    return True


def window(state: dict[str, Any], now: datetime) -> tuple[float, int, str]:
    """(hours to look back, result pages per search, why)."""
    if state.get("last_day") != now.date().isoformat() or not state.get("last_run"):
        return 24, 2, "first run today: the last 24 hours"
    since = (now - datetime.fromisoformat(state["last_run"])).total_seconds() / 3600
    hours = round(min(24, max(1, since + 1)), 1)  # one hour of overlap; seen jobs are skipped anyway
    return hours, 1, f"since the last run: the last {hours:g} hours"


# ---------- matches ----------

def load_match(job_id: str) -> dict[str, Any] | None:
    path = MATCHES / f"{job_id}.json"
    return read_json(path) if path.exists() else None


def save_match(record: dict[str, Any]) -> None:
    MATCHES.mkdir(parents=True, exist_ok=True)
    (MATCHES / f"{record['id']}.json").write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")


def pending_jobs(limit: int, only: list[str] | None = None) -> list[str]:
    if only:
        return [i for i in only if (POSTINGS / f"{i}.json").exists()]
    files = sorted(POSTINGS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.stem for p in files if not (MATCHES / p.name).exists()][:limit]


def speaks_german(prefs: dict[str, Any]) -> bool:
    return any(str(l.get("language", "")).lower() in ("german", "deutsch") and l.get("level") in GERMAN_OK
               for l in prefs.get("languages", []))


def clean_role(title: str) -> str:
    title = re.sub(r"\s*\((?:[mwfdx]\s*/?\s*)+\)\*?", "", title, flags=re.I)
    return re.sub(r"\s+", " ", title).strip(" -*")


# ---------- documents for one job ----------

def make_documents(job: dict, match: dict, profile: dict, catalogue: dict | None, prefs: dict) -> dict[str, Any]:
    repos = relevant_projects(catalogue, f"{job.get('title', '')}\n{job.get('description', '')}",
                              {p["name"].lower() for p in profile["projects"]}, 3)
    texts = source_texts(profile, catalogue)
    company, role = job.get("company", "").strip() or "the company", clean_role(job.get("title", "")) or "Intern"
    availability = str(prefs.get("availability", "")).strip()
    writer = agents.provider_for("application-writer", num_predict=1500, think=False)
    reviewer = agents.provider_for("application-reviewer", num_predict=1200, think=False)

    ratings = agents.relevance(job, match, profile, repos)
    chosen = agents.select_cv(ratings, profile, repos)
    log("  CV Writer: headline and summary")
    focus, summary = agents.write_summary(writer, job, profile, chosen["summary_ids"])
    from render import unsupported_numbers
    summary = [s["source"] if isinstance(s, dict) and unsupported_numbers(s["text"], [s["source"]], texts, f"{company} {role}") else s
               for s in summary]
    cv = {"headline": agents.headline(profile, focus), "summary": summary, **chosen["cv"]}
    evidence = chosen["evidence"]

    log("  CV Writer: cover letter")
    parts = agents.write_parts(writer, job, match, profile, evidence)
    log("  CV Reviewer: checking every part")
    problems = agents.part_problems(parts, evidence, texts, company, role, availability)
    flagged = agents.review_parts(reviewer, job, parts, profile, evidence)
    redo = {k: "; ".join(x for x in (problems.get(k), flagged.get(k)) if x) for k in {**problems, **flagged}}
    rounds = 0
    if redo:
        log(f"  CV Writer: rewriting {', '.join(sorted(redo))}")
        parts = agents.write_parts(writer, job, match, profile, evidence, redo=redo, previous=parts)
        rounds = 1
    paragraphs = agents.assemble_letter(parts, company, role, evidence, availability)
    removed = agents.safe_evidence(paragraphs, texts, profile, company, role, availability)
    removed += agents.drop_unsupported(paragraphs, texts, company, role, availability)
    paragraphs = [p for p in paragraphs if p["text"]]
    remaining = agents.mechanical_review(paragraphs, cv["summary"], texts, company, role, availability)

    draft = {"job_id": job["id"], "company": company, "role": role, "language": "en", "cv": cv,
             "cover_letter": {"recipient": [company, "Hiring Team"], "subject": f"Application: {role}",
                              "salutation": "Dear Hiring Team,", "closing": "Kind regards,", "paragraphs": paragraphs},
             "keyword_gaps": match.get("gaps", []), "notes": "written by the automatic run"}
    draft_path = write_json(next_version(OUTPUT / "drafts", f"{job['id']}_auto"), draft)
    review_path = write_json(next_version(OUTPUT / "reviews", f"{job['id']}_auto_review"), {
        "job_id": job["id"], "draft": draft_path.name, "verdict": "approve" if not remaining else "revise",
        "relevance": {k: round(v, 1) for k, v in sorted(ratings.items(), key=lambda x: -x[1])},
        "evidence": chosen["evidence"], "program_checks": problems, "model_review": flagged, "revision_rounds": rounds,
        "removed_sentences": removed, "remaining": remaining})
    log("  render: printing both PDFs")
    printed = run_script("render", {"draft": rel(draft_path)}, timeout=300)
    return {"draft": rel(draft_path), "review": rel(review_path), "cv": printed.get("cv", ""),
            "cover_letter": printed.get("cover_letter", ""), "rounds": rounds, "removed": len(removed),
            "remaining": remaining + list(printed.get("problems", [])) + ([printed["error"]] if not printed.get("ok") else []),
            "warnings": printed.get("warnings", [])}


# ---------- reports ----------

def ranked_table(records: list[dict], limit: int = 60) -> str:
    rows = ["| fit | verdict | job ID | role | company | city | why | documents |", "|---|---|---|---|---|---|---|---|"]
    for r in records[:limit]:
        docs = r.get("documents") or {}
        files = f"[CV]({docs['cv'].removeprefix('output/')}), [letter]({docs['cover_letter'].removeprefix('output/')})" if docs.get("cv") else ""
        city = (r.get("location") or "").split(",")[0]
        why = (r.get("reason") or "").replace("|", "/")[:160]
        rows.append(f"| {r.get('fit', '')} | {r.get('verdict', '')} | {r['id']} | {r.get('title', '')[:60]} | "
                    f"{r.get('company', '')[:30]} | {city} | {why} | {files} |")
    return "\n".join(rows)


def all_matches() -> list[dict]:
    records = [read_json(p) for p in MATCHES.glob("*.json")] if MATCHES.exists() else []
    return sorted(records, key=lambda r: (r.get("verdict") != "apply", -(r.get("fit") or 0)))


def write_reports(summary: dict[str, Any], new_records: list[dict], made: list[dict], stamp: str) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    every = all_matches()
    shown_all = [r for r in every if r.get("verdict") != "skip"]  # only the internships worth a look
    ranked = ranked_table(shown_all) + f"\n\n{len(every) - len(shown_all)} other jobs hidden (not a match, or not an AI/ML/data internship)."
    head = f"# All matched jobs, best first ({datetime.now().strftime('%d %b %Y %H:%M')})\n\n"
    (OUTPUT / "ranked_jobs.md").write_text(head + ranked + "\n", encoding="utf-8")
    (DATA / "ranked.md").write_text(head + ranked.replace("](", "](../../output/") + "\n", encoding="utf-8")
    lines = [f"# Job run {datetime.now().strftime('%d %b %Y, %H:%M')}", "",
             f"Search: {summary['window']} | LinkedIn requests: {summary['requests']} | new jobs: {summary['new_jobs']}"
             f" | ranked: {summary['matched']} | documents made: {len(made)}", ""]
    if summary.get("problems"):
        lines += ["**Problems:** " + "; ".join(summary["problems"]), ""]
    shown = sorted((r for r in new_records if r.get("verdict") != "skip"), key=lambda r: -(r.get("fit") or 0))
    hidden = len(new_records) - len(shown)
    lines += ["## New internships this run, ranked", "", ranked_table(shown) if shown else "No new matching internships.",
              "", f"{hidden} other new jobs hidden (not a match, or not an AI/ML/data internship).", ""]
    if made:
        lines += ["## Documents to check (nothing has been sent)", ""]
        for m in made:
            d = m["documents"]
            lines.append(f"- **{m['company']} – {m['title']}** (fit {m['fit']}): {d.get('cv', '?')}, {d.get('cover_letter', '?')}; "
                         f"review rounds {d['rounds']}, sentences removed {d['removed']}")
            for p in d.get("remaining", []) + d.get("warnings", []):
                lines.append(f"  - check: {p}")
            if m.get("gaps"):
                lines.append(f"  - gaps (not in the letter): {', '.join(m['gaps'])}")
        lines.append("")
    skipped = [r for r in new_records if r.get("note") and r.get("verdict") != "skip"]
    if skipped:
        lines += ["## Not written automatically", ""] + [f"- {r['id']} {r.get('company', '')}: {r['note']}" for r in skipped] + [""]
    lines += ["All matched jobs: output/ranked_jobs.md. Ask CV Writer and CV Reviewer in the app for changes, then",
              "Job Desk: render <job ID>."]
    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / f"{stamp}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def notify(title: str, text: str) -> None:
    if sys.platform != "darwin" or os.environ.get("AGENTFACTORY_NO_NOTIFY"):
        return
    safe = lambda s: s.replace("\\", "").replace('"', "'")  # noqa: E731
    subprocess.run(["osascript", "-e", f'display notification "{safe(text)}" with title "{safe(title)}"'],
                   capture_output=True, timeout=10)


def note_for_job_desk(text: str) -> None:
    notes = ROOT / "data" / "job-desk" / "notes.md"
    notes.parent.mkdir(parents=True, exist_ok=True)
    with notes.open("a", encoding="utf-8") as f:
        f.write(f"- {datetime.now().strftime('%Y-%m-%d %H:%M')} automatic run: {text}\n")


# ---------- the run ----------

def main() -> None:
    a = args()
    if not take_lock():
        print(json.dumps({"ok": False, "error": "Another automatic run is still going."}))
        return
    started, now = time.monotonic(), datetime.now()
    stamp = now.strftime("%Y-%m-%d_%H%M")
    try:
        profile_path = latest(ME, "profile")
        if not profile_path:
            print(json.dumps({"ok": False, "error": "No profile yet: ask Job Desk to read your CV first."}))
            return
        profile = read_json(profile_path)
        prefs_path, catalogue_path = latest(ME, "preferences"), latest(ME, "projects")
        prefs = read_json(prefs_path) if prefs_path else {}
        catalogue = read_json(catalogue_path) if catalogue_path else None
        settings = {**DEFAULTS, **(prefs.get("automation") or {}), **{k: a[k] for k in DEFAULTS if k in a}}
        state = read_json(STATE) if STATE.exists() else {}
        summary: dict[str, Any] = {"window": "not searched", "requests": 0, "new_jobs": 0, "matched": 0, "problems": []}

        # 1. Job Desk: search and keyword scores
        if not a.get("skip_scrape") and not a.get("jobs"):
            hours, pages, why = window(state, now)
            log(f"Job Desk: searching LinkedIn, {why}")
            scraped = run_script("scrape_jobs", {"hours": hours, "pages": pages})
            summary["window"] = why
            if scraped.get("ok"):
                summary.update(requests=scraped.get("requests_used", 0), new_jobs=scraped.get("saved", 0))
                if scraped.get("stopped"):
                    summary["problems"].append(f"search stopped early: {scraped['stopped']}")
                state.update(last_day=now.date().isoformat(), last_run=now.isoformat(timespec="minutes"))
                STATE.write_text(json.dumps(state), encoding="utf-8")
            else:
                summary["problems"].append(f"search failed: {scraped.get('error', '?')}")
            log(f"Job Desk: {summary['new_jobs']} new jobs, {summary['requests']} requests")
        ids = pending_jobs(500, a.get("jobs"))
        keyword: dict[str, dict] = {}
        if ids:
            scored = run_script("shortlist", {"ids": ids, "top": 0})
            if scored.get("ok"):
                keyword = {r["id"]: r for r in read_json(ROOT / scored["file"])["jobs"]}
        # the most promising jobs first; the model ranks at most max_matches_per_run, the rest wait for the next run
        ids.sort(key=lambda i: -(keyword.get(i, {}).get("score") or 0))
        asked = set(a.get("jobs") or [])
        budget = int(settings["max_matches_per_run"])

        # 2. Job Matcher
        new_records: list[dict] = []
        model_ok = True
        matcher = agents.provider_for("job-matcher")
        for job_id in ids:
            job = read_json(POSTINGS / f"{job_id}.json")
            kw = keyword.get(job_id, {})
            record = {"id": job_id, "title": job.get("title", ""), "company": job.get("company", ""),
                      "location": job.get("location", ""), "link": job.get("link", ""), "posted": job.get("posted", ""),
                      "keyword_score": kw.get("score"), "flags": kw.get("flags", []), "matched_at": today()}
            hard = SKIP_FLAGS & set(record["flags"])
            if "not_internship" in record["flags"] and "working_student" not in record["flags"]:
                hard = hard | {"not_internship"}
            off_topic = ("role_not_in_title" in record["flags"] and (record["keyword_score"] or 0) < settings["min_keyword_score"]
                         and job_id not in asked)
            if hard:
                record.update(fit=0, verdict="skip", reason=f"keyword check: {', '.join(sorted(hard))}")
            elif "not_wanted" in record["flags"] and job_id not in asked:
                record.update(fit=0, verdict="skip", reason="not an AI/ML/data-engineering internship")
            elif off_topic:
                record.update(fit=0, verdict="skip", reason=f"keyword check: not an AI/ML/data/Python role (score {record['keyword_score']})")
            elif budget <= 0:
                continue  # ranked next run
            elif not job.get("description"):
                record.update(fit=None, verdict="maybe", reason="the posting had no description to judge")
            elif model_ok:
                repos = relevant_projects(catalogue, f"{job.get('title', '')}\n{job['description']}",
                                          {p["name"].lower() for p in profile["projects"]}, 3)
                try:
                    log(f"Job Matcher: {job_id} {record['company']} – {record['title'][:50]}")
                    budget -= 1
                    record.update(agents.match_job(matcher, job, profile, repos))
                except agents.StepError as e:
                    model_ok = False
                    summary["problems"].append(f"the model is not reachable ({e}); ranking continues next run")
                    continue
            else:
                continue
            save_match(record)
            new_records.append(record)
        summary["matched"] = len(new_records)

        # 3-5. CV Writer, CV Reviewer, render for the best new matches
        made: list[dict] = []
        german = speaks_german(prefs)
        earlier = [r for r in all_matches() if r["id"] not in {x["id"] for x in new_records}
                   and not r.get("documents") and not r.get("note") and (not a.get("jobs") or r["id"] in a["jobs"])]
        def sane(r: dict) -> bool:
            """The model's fit is generous; documents need the program's keyword check to agree as well."""
            flags = set(r.get("flags") or [])
            not_intern = "not_internship" in flags and "working_student" not in flags
            return (r.get("keyword_score") or 0) >= settings["min_keyword_score"] and not {"role_not_in_title", "not_wanted"} & flags \
                and not not_intern and not SKIP_FLAGS & flags
        candidates = sorted((r for r in new_records + earlier if r.get("verdict") == "apply" and (r.get("fit") or 0) >= settings["min_fit"]
                             and sane(r)), key=lambda r: -((r.get("fit") or 0) + 0.2 * (r.get("keyword_score") or 0)))
        for record in candidates:
            # Only the posting's own words block a job (the program's check); the model's guess is information.
            if not german and "german_required" in record.get("flags", []):
                record["note"] = "the posting asks for good German (set your German level in the preferences if you have it)"
                save_match(record)
                continue
            if len(made) >= int(settings["max_drafts_per_run"]):
                record["note"] = "the limit of documents per run was reached; it will not be written automatically"
                save_match(record)
                continue
            if not model_ok:
                break
            log(f"Documents for {record['id']} {record['company']} (fit {record['fit']})")
            try:
                record["documents"] = make_documents(read_json(POSTINGS / f"{record['id']}.json"), record, profile, catalogue, prefs)
                made.append(record)
            except agents.StepError as e:
                record["note"] = f"writing failed: {e}"
            save_match(record)

        # 6. Report
        report = write_reports(summary, new_records, made, stamp)
        best = max(new_records, key=lambda r: r.get("fit") or 0, default=None)
        text = (f"{summary['new_jobs']} new jobs, {len(made)} CVs written."
                + (f" Best: {best['company']} ({best.get('fit')})" if best and best.get("fit") else ""))
        note_for_job_desk(f"{text} Report: {rel(report)}")
        notify("Job search", text)
        result = {"ok": True, "report": rel(report), "new_jobs": summary["new_jobs"], "ranked": len(new_records),
                  "documents": [r["id"] for r in made], "problems": summary["problems"],
                  "minutes": round((time.monotonic() - started) / 60, 1)}
        log(f"done in {result['minutes']} minutes: {rel(report)}")
        print(json.dumps(result, ensure_ascii=False))
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
