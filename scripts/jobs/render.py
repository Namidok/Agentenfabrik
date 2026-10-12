"""Turn an Application Writer draft into a CV and a cover letter in the master CV's design.

Steps, in order; any failure stops before a PDF is made and says what to fix:
  1. the draft (output/drafts/*.json) must fit schemas/draft.schema.json;
  2. every source ID it cites must exist in the profile or the GitHub project list, and every number in a
     sentence must appear in the facts it cites (so a metric cannot be invented);
  3. the CV and letter are printed with headless Chrome to output/<company>_<role>_cv_vN.pdf and
     _cover_letter_vN.pdf, with the HTML beside them as the editable source (never overwritten);
  4. mechanical checks: page count equals the master CV, fonts embedded, text extractable, nothing runs off the page;
  5. one row is added to output/tracker.csv with status "awaiting approval". Nothing is sent anywhere.

Arguments (JSON): {"job_id": "li-123"} (its newest draft) or {"draft": "output/drafts/li-123_draft_v1.json"}; optional "place"
Prints: {"ok", "cv", "cover_letter", "problems", "tracker"} or {"ok": false, "error", "problems"}"""
from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path

from common import DATA, ME, INPUTS, OUTPUT, POSTINGS, ROOT, args, check_schema, done, fail, latest, load_schema, read_json, rel, slug, today
from render_lib import cv_html, letter_html, mechanical_checks, pdf_facts, print_pdf

DRAFTS = OUTPUT / "drafts"
TRACKER_FIELDS = ["date", "job_id", "company", "role", "link", "cv", "cover_letter", "status", "problems"]
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def repair_quotes(raw: str) -> tuple[str, int]:
    """Escape stray double quotes inside JSON strings ("an "incomplete" verdict"), the most common mistake of small
    models writing JSON. A quote closes a string only when , : } ] or the end follows it."""
    out, inside, fixed, i = [], False, 0, 0
    while i < len(raw):
        ch = raw[i]
        if inside and ch == "\\":
            out.append(raw[i:i + 2])
            i += 2
            continue
        if ch == '"':
            if not inside:
                inside = True
            else:
                rest = raw[i + 1:].lstrip()
                if rest and rest[0] not in ",:}]":
                    out.append('\\"')
                    fixed += 1
                    i += 1
                    continue
                inside = False
        out.append(ch)
        i += 1
    return "".join(out), fixed


def close_brackets(raw: str) -> tuple[str, int]:
    """Add the } and ] a draft forgot at its end. Gives up (returns it unchanged) if brackets cross anywhere."""
    stack, inside, escaped = [], False, False
    for ch in raw:
        if inside:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                inside = False
        elif ch == '"':
            inside = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack or stack.pop() != ch:
                return raw, 0
    if inside:
        return raw, 0
    return raw.rstrip() + "".join(reversed(stack)), len(stack)


def source_texts(profile: dict, projects: dict | None) -> dict[str, str]:
    """Every citable ID and the text a claim citing it may rely on."""
    texts: dict[str, str] = {}
    for f in profile["summary"]:
        texts[f["id"]] = f["text"]
    for s in profile["skills"]:
        texts[s["id"]] = f"{s['label']} {s['items'] if isinstance(s['items'], str) else ', '.join(s['items'])}"
    for e in profile["experience"]:
        for b in e["bullets"]:
            texts[b["id"]] = f"{b['text']} {e['title']} {e['org']} {e['dates']}"
        texts[e["id"]] = " ".join([e["title"], e["org"], e.get("location", ""), e["dates"]] + [b["text"] for b in e["bullets"]])
    for p in profile["projects"]:
        for b in p["bullets"]:
            texts[b["id"]] = f"{b['text']} {p['name']} {p.get('tagline', '')}"
        texts[p["id"]] = " ".join([p["name"], p.get("tagline", ""), " ".join(p.get("stack", []))] + [b["text"] for b in p["bullets"]])
    for e in profile["education"]:
        texts[e["id"]] = " ".join([e["degree"], e["school"], e.get("note", ""), e["dates"]])
    for p in (projects or {}).get("projects", []):
        texts[p["id"]] = " ".join([p["name"], p["summary"], p["what_was_built"], " ".join(p["stack"])] + p["outcomes"])
    return texts


def _numbers(text: str) -> list[tuple[str, set[str]]]:
    """Each number in text with the forms that mean the same: 8,000 = 8000 = 8k, 1.5k = 1500, 3,5 = 3.5."""
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # thousands separators
    found = []
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*([kK])?(?![a-zA-Z])", text):
        value = m.group(1).replace(",", ".")
        forms = {value}
        if m.group(2):
            forms.add(f"{float(value) * 1000:g}")
        found.append((m.group(1) + (m.group(2) or ""), forms))
    return found


def unsupported_numbers(text: str, cited: list[str], texts: dict[str, str], allowed: str = "") -> list[str]:
    pool = " ".join(texts.get(c, "") for c in cited) + " " + allowed
    have = set().union(*[forms for _, forms in _numbers(pool)]) if pool.strip() else set()
    return [shown for shown, forms in _numbers(text) if not forms & have]


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{4,}", text.lower()))


def source_warnings(draft: dict, texts: dict[str, str]) -> list[str]:
    """Not errors, but worth a look: reworded sentences far from their fact, and paragraphs that cite nothing."""
    out = []
    cv = draft["cv"]
    items = [(f"cv.summary[{i}]", s) for i, s in enumerate(cv["summary"])]
    items += [(f"cv.{part} {e['id']} bullet {i + 1}", b) for part in ("experience", "projects")
              for e in cv.get(part, []) for i, b in enumerate(e["bullets"])]
    for where, item in items:
        own, src = words(item["text"]), words(texts.get(item["source"], ""))
        if len(own) >= 4 and len(own & src) / len(own) < 0.35:
            out.append(f"{where} shares few words with {item['source']}: check that it says the same")
    for i, para in enumerate(draft["cover_letter"]["paragraphs"]):
        if not para.get("sources"):
            out.append(f"cover_letter.paragraphs[{i}] cites no fact IDs")
    return out


def check_sources(draft: dict, profile: dict, texts: dict[str, str]) -> list[str]:
    problems: list[str] = []
    allowed = f"{draft['company']} {draft['role']}"

    def claim(where: str, text: str, cited: list[str]) -> None:
        for c in cited:
            if c not in texts:
                problems.append(f"{where}: source {c} does not exist in the profile or the project list")
        bad = unsupported_numbers(text, cited, texts, allowed)
        if bad:
            problems.append(f"{where}: the number(s) {', '.join(bad)} do not appear in {', '.join(cited) or 'any source'}")

    cv = draft["cv"]
    for i, s in enumerate(cv["summary"]):
        claim(f"cv.summary[{i}]", s["text"], [s["source"]])
    known_exp = {e["id"] for e in profile["experience"]}
    for e in cv.get("experience", []):
        if e["id"] not in known_exp:
            problems.append(f"cv.experience: {e['id']} is not a job in the profile")
        for i, b in enumerate(e["bullets"]):
            claim(f"cv.experience {e['id']} bullet {i + 1}", b["text"], [b["source"]])
    for p in cv.get("projects", []):
        if p["id"] not in texts:
            problems.append(f"cv.projects: {p['id']} is not a project in the profile or on GitHub")
        for i, b in enumerate(p["bullets"]):
            claim(f"cv.projects {p['id']} bullet {i + 1}", b["text"], [b["source"]])
    for s in cv.get("skills_order", []):
        if s not in texts:
            problems.append(f"cv.skills_order: {s} is not a skill group in the profile")
    for i, para in enumerate(draft["cover_letter"]["paragraphs"]):
        cited = para.get("sources") or []
        if cited:
            claim(f"cover_letter.paragraphs[{i}]", para["text"], cited)
        else:  # no sources given: every number must still be somewhere in the user's facts
            bad = unsupported_numbers(para["text"], list(texts), texts, allowed)
            if bad:
                problems.append(f"cover_letter.paragraphs[{i}]: the number(s) {', '.join(bad)} do not appear in any fact")
    return problems


def expand_fact_ids(draft: dict, profile: dict) -> list[str]:
    """Turn bare fact IDs ("F007") into {"text": <the fact word for word>, "source": "F007"}, in place."""
    facts = {f["id"]: f["text"] for f in profile["summary"]}
    facts.update({b["id"]: b["text"] for e in profile["experience"] + profile["projects"] for b in e["bullets"]})
    problems: list[str] = []

    def expand(items: list, where: str) -> None:
        for i, item in enumerate(items):
            if isinstance(item, str):
                if item in facts:
                    items[i] = {"text": facts[item], "source": item}
                else:
                    problems.append(f"{where}: fact {item} does not exist in the profile")

    cv = draft["cv"]
    expand(cv["summary"], "cv.summary")
    for part in ("experience", "projects"):
        for entry in cv.get(part, []):
            expand(entry["bullets"], f"cv.{part} {entry['id']}")
    return problems


def unique(items: list[dict]) -> list[dict]:
    """Drop sentences that repeat an earlier one (small models sometimes cite the same fact twice)."""
    seen, out = set(), []
    for item in items:
        key = re.sub(r"[^a-z0-9]+", " ", item["text"].replace("**", "").lower()).strip()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def build_cv(draft: dict, profile: dict, projects: dict | None) -> dict:
    cv = draft["cv"]
    header = {**profile["header"], "headline": cv.get("headline") or profile["header"]["headline"]}
    order = cv.get("skills_order") or []
    skills = sorted(profile["skills"], key=lambda s: order.index(s["id"]) if s["id"] in order else len(order))
    bullets = {e["id"]: unique(e["bullets"]) for e in cv.get("experience", [])}
    experience = [{**e, "bullets": bullets.get(e["id"], e["bullets"])} for e in profile["experience"]]  # no job is ever dropped
    by_id = {p["id"]: p for p in profile["projects"]}
    by_id.update({p["id"]: {"name": p["name"], "tagline": "", "stack": p["stack"][:6], "link": p["link"]}
                  for p in (projects or {}).get("projects", [])})
    chosen = [{**by_id[p["id"]], "id": p["id"], "bullets": p["bullets"][:2]} for p in cv.get("projects", []) if p["id"] in by_id][:3]
    for p in profile["projects"]:  # always three projects: fill up from the master CV, one bullet each
        if len(chosen) >= 3:
            break
        if p["id"] not in {c["id"] for c in chosen}:
            chosen.append({**p, "bullets": p["bullets"][:1]})
    return {"header": header, "summary": unique(cv["summary"]), "skills": skills, "experience": experience,
            "projects": chosen, "education": profile["education"]}


def build_letter(draft: dict, profile: dict, place: str) -> dict:
    cl = draft["cover_letter"]
    d = date.today()
    return {"header": {**profile["header"], "headline": draft["cv"].get("headline") or profile["header"]["headline"]},
            "place_date": f"{place}, {d.day} {d.strftime('%B %Y')}", "recipient": cl.get("recipient") or [draft["company"]],
            "subject": cl["subject"], "salutation": cl.get("salutation") or "Dear Hiring Team,",
            "paragraphs": [p["text"] for p in cl["paragraphs"]], "closing": cl.get("closing") or "Kind regards,"}


def version_for(stem: str) -> int:
    n = 1
    while any((OUTPUT / f"{stem}_{kind}_v{n}{ext}").exists() for kind in ("cv", "cover_letter") for ext in (".pdf", ".html")):
        n += 1
    return n


def add_tracker_row(row: dict) -> Path:
    path = OUTPUT / "tracker.csv"
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRACKER_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    return path


def main() -> None:
    a = args()
    if not a.get("draft") and re.fullmatch(r"[a-z]+-[0-9A-Za-z]+", str(a.get("job_id", ""))):
        newest = sorted(DRAFTS.glob(f"{a['job_id']}_*.json"), key=lambda p: p.stat().st_mtime)
        a["draft"] = rel(newest[-1]) if newest else ""
    draft_path = (ROOT / str(a.get("draft", ""))).resolve()
    if DRAFTS.resolve() not in draft_path.parents or draft_path.suffix != ".json" or not draft_path.exists():
        fail("Give {\"job_id\": \"li-...\"} or {\"draft\": \"output/drafts/<file>.json\"}; only files in output/drafts are rendered.")
    raw = draft_path.read_text(encoding="utf-8")
    try:
        draft, repaired = json.loads(raw), 0
    except ValueError:
        fixed_raw, repaired = repair_quotes(raw)
        fixed_raw, closed = close_brackets(fixed_raw)
        repaired += closed
        try:
            draft = json.loads(fixed_raw)
        except ValueError as e:
            fail(f"The draft is not valid JSON: {e}. Write a new draft; inside texts use ' or “ ” instead of \".")
    if isinstance(draft, dict) and isinstance(draft.get("cv"), dict):
        for key in ("cover_letter", "keyword_gaps", "notes"):  # a forgotten } leaves these inside "cv"
            if key in draft["cv"] and key not in draft:
                draft[key] = draft["cv"].pop(key)
                repaired += 1
    problems = check_schema(draft, load_schema("draft"))
    if problems:
        fail("The draft does not fit the draft schema.", problems=problems[:10])
    profile_path, projects_path = latest(ME, "profile"), latest(ME, "projects")
    if not profile_path:
        fail("No profile yet: run extract_cv first.")
    profile = read_json(profile_path)
    projects = read_json(projects_path) if projects_path else None
    texts = source_texts(profile, projects)
    problems = expand_fact_ids(draft, profile) + check_sources(draft, profile, texts)
    if problems:
        fail("Some claims are not backed by the profile; fix the draft and render again.", problems=problems[:12])

    stem = f"{slug(draft['company'], 30)}_{slug(draft['role'], 40)}"
    n = version_for(stem)
    place = str(a.get("place") or profile["header"]["contact"][0].split(" (")[0])
    cv_pdf, cl_pdf = OUTPUT / f"{stem}_cv_v{n}.pdf", OUTPUT / f"{stem}_cover_letter_v{n}.pdf"
    try:
        print_pdf(cv_html(build_cv(draft, profile, projects)), cv_pdf.with_suffix(".html"), cv_pdf)
        print_pdf(letter_html(build_letter(draft, profile, place)), cl_pdf.with_suffix(".html"), cl_pdf)
    except RuntimeError as e:
        fail(str(e))
    master = INPUTS / "master_cv.pdf"
    pages = pdf_facts(master)["pages"] if master.exists() else 1
    name = profile["header"]["name"]
    checks = mechanical_checks(cv_pdf, pages, [name]) + mechanical_checks(cl_pdf, 1, [name, draft["company"]])

    posting = POSTINGS / f"{draft['job_id']}.json"
    link = read_json(posting).get("link", "") if posting.exists() else ""
    tracker = add_tracker_row({"date": today(), "job_id": draft["job_id"], "company": draft["company"], "role": draft["role"],
                               "link": link, "cv": rel(cv_pdf), "cover_letter": rel(cl_pdf),
                               "status": "awaiting approval" if not checks else "check failed", "problems": " | ".join(checks)})
    done({"ok": True, "cv": rel(cv_pdf), "cover_letter": rel(cl_pdf), "html": [rel(cv_pdf.with_suffix(".html")), rel(cl_pdf.with_suffix(".html"))],
          "problems": checks, "warnings": source_warnings(draft, texts)[:8], "tracker": rel(tracker), "repaired": repaired,
          "next": "Open both PDFs and approve or ask for changes; nothing has been sent." if not checks
                  else "Shorten the draft (fewer or shorter bullets) and render again."})


if __name__ == "__main__":
    main()
