"""Score saved postings against the preferences and the profile, without a language model, and save a shortlist.

The score (0-100) is plain arithmetic, so it is the same every run:
  role words in the title (+30), internship or Pflichtpraktikum (+20/+5), the profile's skills found in the posting
  (+4 each, at most +40), preferred keywords (+5 each, at most +10); senior roles -40, German required -15
  (unless the preferences say German B2 or better); an excluded keyword sets the score to 0.
Writes data/jobs/shortlist_vN.json (id, title, company, score, flags, matched skills).
The printed summary holds only job IDs, scores and flags: never posting text.

Arguments (JSON, optional): {"jobs_file": "data/jobs/jobs_v2.json", "all": false, "ids": [...], "top": 10}
Prints: {"ok", "file", "scored", "top": [{"id", "score", "flags"}]}"""
from __future__ import annotations

import re

from common import DATA, ME, POSTINGS, ROOT, args, done, fail, latest, next_version, read_json, rel, today, write_json

ROLE_WORDS = ["machine learning", "ml", "ai", "artificial intelligence", "ki", "künstliche intelligenz", "data engineer",
              "data engineering", "data science", "data scientist", "data", "python", "llm", "nlp", "deep learning",
              "computer vision", "mlops", "genai", "generative ai", "software engineer", "backend", "analytics"]
INTERN_WORDS = ["intern", "internship", "praktikum", "praktikant", "praktikantin", "trainee"]
SENIOR_WORDS = ["senior", "lead", "principal", "staff", "head of", "director", "manager", "architect", "sr."]
GERMAN_REQUIRED = re.compile(
    r"(fließend|verhandlungssicher|sehr gute|gute|fluent|business|native)[^.\n]{0,40}(deutsch|german)"
    r"|(deutsch|german)[^.\n]{0,30}(c1|c2|b2|fließend|verhandlungssicher|muttersprach|fluent|required|erforderlich|zwingend)"
    r"|deutschkenntnisse", re.I)
NICE_TO_HAVE = re.compile(r"plus|advantage|nice to have|bonus|beneficial|desirable|preferred|von vorteil|wünschenswert|wuenschenswert|optional", re.I)


def german_required(text: str) -> bool:
    """True when the posting asks for good German, not when German is only "a plus"."""
    pos = 0
    while (m := GERMAN_REQUIRED.search(text, pos)) is not None:
        pos = m.start() + 1  # overlapping: "Fluent in English; German C1" must still see "German C1"
        if re.search(r"english|englisch", m.group(0), re.I) and not re.search(r"(deutsch|german)\W{0,3}(and|und|&)", m.group(0), re.I):
            continue  # "Fluent English (German ..." is about English
        if not NICE_TO_HAVE.search(text[m.start(): m.end() + 40]):
            return True
    return False


GERMAN_STOPWORDS = {"und", "der", "die", "das", "mit", "für", "wir", "sie", "ihre", "deine", "bei", "von", "zu", "ist", "auf"}
EXTRA_SKILLS = ["python", "sql", "pandas", "numpy", "pytorch", "tensorflow", "scikit-learn", "spark", "airflow", "kafka",
                "docker", "kubernetes", "aws", "azure", "gcp", "git", "linux", "fastapi", "flask", "django", "llm", "rag",
                "langchain", "langgraph", "hugging face", "transformers", "nlp", "computer vision", "etl", "dbt", "tableau",
                "power bi", "postgresql", "mongodb", "rest api", "ci/cd", "pytest", "machine learning", "deep learning"]


def has(text: str, word: str) -> bool:
    return re.search(rf"(?<![a-z0-9äöüß]){re.escape(word.lower())}(?![a-z0-9äöüß])", text.lower()) is not None


def skill_vocabulary(profile: dict, projects: dict | None) -> list[str]:
    words: list[str] = []
    for s in profile.get("skills", []):
        items = s["items"] if isinstance(s["items"], list) else re.split(r",|/", s["items"])
        words += [re.sub(r"\(.*?\)", "", i).strip() for i in items]
    for p in profile.get("projects", []):
        words += p.get("stack", [])
    for p in (projects or {}).get("projects", []):
        words += p.get("stack", [])
    # Only the user's own skills count as matches; EXTRA_SKILLS just names common ones the profile writes differently.
    own = " ".join(words).lower()
    words += [s for s in EXTRA_SKILLS if has(own, s)]
    out: list[str] = []
    for w in words:
        w = w.strip().lower()
        if 1 < len(w) <= 30 and w not in out and w not in ("ci", "testing"):
            out.append(w)
    return out


def speaks_german(prefs: dict) -> bool:
    for lang in prefs.get("languages", []):
        if str(lang.get("language", "")).lower() in ("german", "deutsch") and lang.get("level") in ("B2", "C1", "C2", "native"):
            return True
    return False


def score(job: dict, prefs: dict, vocab: list[str]) -> dict:
    title = job.get("title", "")
    criteria = " ".join(f"{k} {v}" for k, v in (job.get("criteria") or {}).items())
    text = f"{title}\n{criteria}\n{job.get('description', '')}"
    flags: list[str] = []
    points = 0
    roles = [r.lower() for r in prefs.get("target_roles", [])] + ROLE_WORDS
    if any(has(title, r) for r in roles):
        points += 30
    else:
        flags.append("role_not_in_title")
    intern = any(has(title, w) for w in INTERN_WORDS) or "internship" in criteria.lower()
    if intern:
        points += 20
    elif has(title, "werkstudent") or has(title, "working student"):
        flags.append("working_student")
    else:
        flags.append("not_internship")
    if has(text, "pflichtpraktikum") or has(text, "mandatory internship") or has(text, "curricular internship"):
        points += 5
        flags.append("mandatory_internship_ok")
    matched = [w for w in vocab if has(text, w)]
    points += min(40, 4 * len(matched))
    include = [k for k in prefs.get("keywords_include", []) if has(text, k)]
    points += min(10, 5 * len(include))
    if any(has(title, w) for w in SENIOR_WORDS) and not intern:  # "Product Manager Intern" is still an internship
        points -= 40
        flags.append("senior")
    if german_required(text):
        flags.append("german_required")
        if not speaks_german(prefs):
            points -= 15
    words = re.findall(r"[a-zäöüß]+", job.get("description", "").lower())
    if words and sum(w in GERMAN_STOPWORDS for w in words) / len(words) > 0.08:
        flags.append("posting_in_german")
    excluded = [k for k in prefs.get("keywords_exclude", []) if has(text, k)]
    if excluded:
        flags.append("excluded_keyword")
        points = 0
    if not job.get("description"):
        flags.append("no_description")
    return {"id": job["id"], "title": title, "company": job.get("company", ""), "location": job.get("location", ""),
            "link": job.get("link", ""), "score": max(0, min(100, points)), "flags": flags,
            "matched_skills": matched[:15], "matched_keywords": include, "excluded_by": excluded}


def main() -> None:
    a = args()
    profile_path = latest(ME, "profile")
    if not profile_path:
        fail("No profile yet: run extract_cv first.")
    prefs_path, projects_path = latest(ME, "preferences"), latest(ME, "projects")
    prefs = read_json(prefs_path) if prefs_path else {}
    vocab = skill_vocabulary(read_json(profile_path), read_json(projects_path) if projects_path else None)
    if a.get("ids"):
        ids = [str(i) for i in a["ids"]]
    elif a.get("all"):
        ids = sorted(p.stem for p in POSTINGS.glob("*.json"))
    else:
        jobs_file = (ROOT / a["jobs_file"]) if a.get("jobs_file") else latest(DATA, "jobs")
        if not jobs_file or not jobs_file.exists():
            fail("No job list yet: run scrape_jobs first, or pass {\"all\": true}.")
        ids = [j["id"] for j in read_json(jobs_file)["jobs"]]
    results, missing = [], []
    for job_id in ids:
        if not re.fullmatch(r"[a-z]+-[0-9A-Za-z]+", job_id) or not (POSTINGS / f"{job_id}.json").exists():
            missing.append(job_id)
            continue
        results.append(score(read_json(POSTINGS / f"{job_id}.json"), prefs, vocab))
    if not results:
        fail("No saved postings to score.", missing=missing[:10])
    results.sort(key=lambda r: -r["score"])
    path = write_json(next_version(DATA, "shortlist"), {"version": 1, "made": today(), "preferences": rel(prefs_path) if prefs_path else "",
                                                        "jobs": results})
    table = ["| score | id | title | company | location | flags | matched skills |", "|---|---|---|---|---|---|---|"]
    table += [f"| {r['score']} | {r['id']} | {r['title'][:60]} | {r['company'][:40]} | {r['location'][:30]} | {', '.join(r['flags'])} | "
              f"{', '.join(r['matched_skills'][:8])} |" for r in results[:40]]
    md = path.with_suffix(".md")
    md.write_text(f"# Shortlist {path.stem} ({today()}): best first, at most 40 rows\n\n" + "\n".join(table) + "\n", encoding="utf-8")
    top = int(a.get("top", 10))
    done({"ok": True, "file": rel(path), "table": rel(md), "scored": len(results), "missing": missing[:10],
          "top": [{"id": r["id"], "score": r["score"], "flags": r["flags"]} for r in results[:top]]})


if __name__ == "__main__":
    main()
