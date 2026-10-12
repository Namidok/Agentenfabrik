# Job application agents

Four agents and a set of small Python programs that replicate the idea of
[ai-job-search](https://github.com/MadsLorentzen/ai-job-search) on this computer, with local models only:
find internships on LinkedIn, shortlist them against your profile, and write a tailored CV and cover letter
for each job you pick, **printed in your master CV's design**. Nothing is ever sent: you approve every
document and apply yourself.

## Why four agents and not one

A single agent that scrapes the web, reads job postings and writes files is the riskiest possible shape:
a posting can contain text such as "ignore your instructions and …", and an agent that reads it while it
can also use the network or run programs could be talked into doing that. So the work is split by what
each agent is allowed to touch:

| Agent | Tools | Can read | Can write | Sees posting text? |
|---|---|---|---|---|
| **Job Desk** (`job-desk`) | `script.run`, `fs.read`, notes | `data/jobs/me` (your profile, projects, preferences) | its notes only | **never** |
| **Job Matcher** (`job-matcher`) | `fs.list`, `fs.read` | `data/jobs` | nothing | yes |
| **CV Writer** (`application-writer`) | `fs.list`, `fs.read`, `fs.write` | `data/jobs/briefs`, `output/drafts`, `output/reviews` | `output/drafts` (new files only) | yes |
| **CV Reviewer** (`application-reviewer`) | `fs.list`, `fs.read`, `fs.write` | `data/jobs/briefs`, `output/drafts` | `output/reviews` (new files only) | yes |

- Only Job Desk can run programs (and only the allowlisted ones below). The programs keep posting text out of
  its conversation: they print counts, IDs, scores and file names, never descriptions.
- The agents that read postings have no network and no program tools. The trade-off: CV Writer and Reviewer can
  create files in one folder each. That is needed to hand over a draft; they can never replace a file.
- AgentFactory has no multi-agent workflow type, so **you are the hand-off**: each agent ends by telling you which
  agent to open next and what to give it (a job ID).

## The flow

```
Job Desk:     extract_cv → (you correct facts: profile_fix) → fetch_github → save_preferences
Job Desk:     scrape_jobs → shortlist
Job Matcher:  "show me the shortlist" → details for a job → you pick one
Job Desk:     "prepare li-…"        (writes the job brief and your facts for that job)
CV Writer:    "li-…"                (writes output/drafts/li-…_draft.json)
CV Reviewer:  "li-…"                (writes output/reviews/li-…_review.json; if "revise", back to CV Writer)
Job Desk:     "render li-…"         (checks the draft, prints both PDFs, adds a tracker row)
You:          open the PDFs, approve or ask for changes, apply yourself
```

## Setup (once)

1. Put your master CV at `inputs/master_cv.pdf` (one page, text-based PDF; a scan is read with OCR via `tesseract`).
2. Google Chrome must be installed: it prints the PDFs (the same engine your master CV was made with).
3. The Carlito font (metric-compatible with Calibri, SIL Open Font License) is in `templates/fonts/`.
4. `pypdf` is installed in `.venv` (`.venv/bin/pip install pypdf`).
5. Start the app (`python serve.py`) and open **Job Desk**.

## The programs (`scripts/jobs/`)

Each takes one JSON object (Job Desk passes it through `script.run`; by hand: `.venv/bin/python scripts/jobs/<name>.py '<json>'`)
and prints one JSON line.

| Program | What it does | Writes |
|---|---|---|
| `extract_cv` | Reads the master CV by font, size and colour into facts with IDs (F001…, S1…, E1…, CP1…, ED1…) | `data/jobs/me/profile_vN.json` + `.md` |
| `profile_fix` | Your corrections by ID: `{"set": [{"id": "F006", "text": "…"}], "remove": ["F003"], "add": [{"to": "E1", "text": "…"}]}` | the next `profile_vN` |
| `fetch_github` | Your public repos: description, stack (from dependency files), sentences quoted from the README | `data/jobs/me/projects_vN.json` |
| `save_preferences` | Merges your answers into the preferences, checked against `schemas/preferences.schema.json` | `data/jobs/me/preferences_vN.json` |
| `scrape_jobs` | LinkedIn search from the saved preferences; new postings only | `data/jobs/postings/<id>.json`, `jobs_vN.json`, `seen.json` |
| `shortlist` | Deterministic score 0-100 and flags (internship, Pflichtpraktikum, German required, senior, …) | `data/jobs/shortlist_vN.json` + `.md` |
| `prepare` | For one job: the posting (fenced, marked untrusted) + skill gaps, and your facts + the 4 closest GitHub repos | `data/jobs/briefs/<id>_job_vN.md`, `<id>_facts_vN.md` |
| `render` | Draft → schema check → source check → PDFs → mechanical checks → tracker row | `output/<company>_<role>_cv_vN.pdf/.html`, `…_cover_letter_vN…`, `output/tracker.csv` |
| `selftest_template` | Compares a re-rendered master CV with the original (pixels, line positions, fonts) | `templates/fidelity_report_vN.json` |

All result files are versioned (`_v1`, `_v2`, …) and never overwritten.

## How "never fabricate" is enforced

- CV Writer mostly picks facts by ID: a bullet written as `"F017"` is that fact word for word. Only the headline,
  reworded summary sentences and the cover letter are new text, each with a source ID.
- `render` refuses a draft when a source ID does not exist, when a job or project ID is unknown, or when a sentence
  contains **a number that is not in the facts it cites** (so "reduced defects by 70%" fails if the fact says 55%).
- `render` keeps every job of your master CV (only the bullets are chosen), and copies the header, dates and
  education unchanged from the profile. If the draft leaves out experience or projects, the master CV's own bullets
  are used (they fit its one page). Repeated sentences are dropped.
- Warnings (not errors) point at reworded sentences that share few words with the fact they cite, and at letter
  paragraphs that cite nothing (their numbers are still checked against all your facts).
- Small-model JSON slips are repaired before checking: stray `"` inside texts, a missing closing `}`, and keys left
  inside `cv` by a forgotten brace. The output says how many repairs were made.
- What the job asks for and your facts do not show goes into `keyword_gaps` and the `prepare` gap list; the
  agents are told to state gaps, never to claim them. CV Reviewer checks each sentence against its fact.
- JSON validation happens in the programs (`render`, `save_preferences`), not in the AgentFactory runtime:
  the runtime has no output-schema checks.

## The design check

`render` prints with `templates/cv.css`, measured from your master CV (Carlito, navy `#1f3a6b` headings with a rule,
the same sizes and margins). After printing it checks: same page count as the master CV, all fonts embedded, text
extractable (ATS), nothing running into the bottom margin. Problems are listed and the tracker row says "check failed";
the fix is a shorter draft.

## LinkedIn: limits and terms

**Automated access to LinkedIn conflicts with LinkedIn's User Agreement (section 8.2). This is meant for
low-volume personal use only, at your own risk.** The program uses LinkedIn's public guest job pages (no login),
and:
- waits 3-5 seconds between requests, and never makes more than 30 requests per run;
- backs off exponentially on 429/999/5xx answers and stops after 3 refusals in a row;
- skips jobs it has already opened (`data/jobs/seen.json`) and counts a job found by two searches once.
LinkedIn changes its pages without notice; if `found` stays 0, the page structure changed and `sources.py` needs updating.
Another source can be added in `sources.py` with the same two calls (`search`, `detail`).

## Privacy

`inputs/`, `output/` and `data/` are in `.gitignore`: your CV, profile, postings, drafts and PDFs stay on this computer.
The only network calls are GitHub (your public repos) and LinkedIn (job search), both made by programs you start.

## Measured on the MacBook Air M4 (qwen3:8b)

| Step | Time |
|---|---|
| Job Desk turn with a program (extract_cv, profile_fix, shortlist) | 25-60 s |
| scrape_jobs, 8 requests (live smoke test) | 30 s; a full 30-request run takes about 2-3 minutes |
| CV Writer, one draft | about 95 s |
| CV Reviewer, one review | about 95 s |
| render (both PDFs and checks) | about 3 s |

Live end-to-end run on a real posting (SIXT, Applied AI Engineer internship): Job Desk extracted and corrected the
profile and shortlisted 7 jobs; CV Writer wrote a draft that render printed as a one-page CV and a one-page letter;
CV Reviewer wrote a valid review asking for better-cited letter paragraphs.

## Known limits

- qwen3:8b is a small model: drafts are serviceable, not polished. It sometimes leaves out sections or sources
  (render falls back or warns), cites the wrong fact (render warns), or skips the summary lines in its reply.
  Read every document before you use it; that is what the approval step is for.
- Every program run is written to Job Desk's notes automatically, so a new chat can continue where you stopped.
- The shortlist score is keyword arithmetic, not judgement; Job Matcher is there for the judgement.
- Cover letters are in English by default; ask CV Writer for German if the posting is German.
