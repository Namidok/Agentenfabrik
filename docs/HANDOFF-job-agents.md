# Job application agents: build status (2026-10-12)

User decisions: 4 agents + Python programs (one agent is not safe/feasible). Agents start the programs from the chat
through ONE new tool `script.run` (allowlist in factory/script_tool.py, needs permissions.shell; user-approved).
LinkedIn only, Germany, internships in AI/ML/Data Engineering/Python. GitHub user: Namidok. Never commit.

Full user guide: docs/JOB-AGENTS.md.

## Built
- scripts/jobs: common (versioned files, mini schema check, profile_markdown/write_profile), extract_cv, profile_fix,
  fetch_github, save_preferences, sources (Pacer + LinkedInGuest), scrape_jobs, shortlist (+ .md table, German
  nice-to-have aware), prepare (job brief + facts brief < 8000 chars each), render (schema + source IDs + numbers
  must appear in cited facts; PDFs; mechanical checks; output/tracker.csv), render_lib, selftest_template.
- User files live in data/jobs/me (profile_v1.json/.md, projects_v1..v3.json, preferences_v1.json); postings in
  data/jobs/postings; briefs in data/jobs/briefs.
- factory: script_tool.py (allowlist, JSON on stdin, -E -s, per-script timeout, stdout <= 2000 chars); registered in
  tools.py; KNOWN_TOOLS/TOOL_REQUIRES; interviewer shell detection + warning; settings.apply_options gives chat agents
  with fs.write the task reply cap (2048); UI: TOOL_INFO, CALL_WORDS, argSummary, hire.js name, office "code" station.
- specs: job-desk, job-matcher, application-writer, application-reviewer (qwen3:8b, 8192, temp 0.2, think false).
- tests: tests/test_script_tool.py, tests/test_job_scripts.py, test_settings reply cap.

## Live checks done
- fetch_github live (31 repos, 24 READMEs) -> projects_v3. LinkedIn smoke run: 8 requests, 10 found, 7 saved.
- shortlist + prepare on the real postings; render of a hand-made sample draft -> 1-page CV + letter, checks pass.

## Live LLM checks (qwen3:8b, isolated copies in the scratchpad)
- CV Writer: run 1-2 failed (path "/output/..." refused, then retries without path -> loop guard). Fixed: check_path
  accepts a leading "/" as the project folder when that is inside the allowed folders (tests in test_tools.py).
  Run 3: 198 s, JSON with stray quotes + missing brace + misnested cover_letter. Fixed: render repairs these;
  facts briefs use curly quotes. Run 4 (bullets as bare fact IDs, best-match hint from prepare): 94 s, valid draft,
  left out experience/projects/sources -> render falls back to master bullets and warns. PDFs fine (1 page each).
- CV Reviewer: 95 s, valid review JSON, verdict revise.
- Job Desk: extract_cv -> summary -> profile_fix with the user's words -> shortlist; correct. Fixes: facts_file in
  extract_cv output, "never announce" rule, script.run auto-notes successful runs.
- Job Matcher: shortlist + details; fixed matched_skills to count only the user's own skills.

## Left for the user
- German-teacher flashcards: the 7 wrong cards were deleted on 2026-10-12 at the user's request (deck now empty;
  backup data/german-teacher/cards.db.backup-before-delete). Notes still say A0, numbers 1-10.
- Real data now holds: profile_v1 (+ .md), projects_v1..v3, preferences_v1 (from the user's stated preferences),
  7 postings, jobs_v1, shortlist_v1..v2, briefs for li-4438674690 (v1, v2). output/ is still empty.

## How the user runs it (given 2026-10-12)
`.venv/bin/python serve.py` -> http://127.0.0.1:8010. Job Desk: profile -> GitHub -> preferences -> search -> shortlist.
Job Matcher: choose. Then Job Desk "prepare <id>" -> CV Writer "<id>" -> CV Reviewer "<id>" -> Job Desk "render <id>".
PDFs in output/, status in output/tracker.csv. Job Desk's real notes are still empty (live tests ran in copies).

## Automatic run (built 2026-10-12, user request: all 4 agents on one trigger every 3 hours)
- scripts/jobs/pipeline.py (orchestration, report, ranked list, notes line, Mac notification), auto_agents.py (model
  steps with Ollama structured output; fact IDs are enums), schedule.py (LaunchAgent com.agentfactory.jobsearch,
  INSTALLED, 00/03/.../21:00, log data/jobs/pipeline.log), run_now.py (allowlisted; Job Desk "run now").
- Search window: 24 h + 2 pages on the first run of a day, else since last run (+1 h). sources.py: "hours" -> f_TPR=r<seconds>.
- Matcher uses thinking (~2 min/job); writer/reviewer do not. Off-topic jobs (role_not_in_title and keyword score
  < 40) and senior / not-internship jobs are skipped without the model. German blocks writing only when the
  posting's text requires it (shortlist flag), never on the model's guess (it invented "good German" for BMW).
- Quality lessons (live, BMW li-4473693337): the model copied example IDs, invented availability, wrote "I lack",
  rated every item 3/3, dropped punctuation when told "no punctuation like ·". Fix: program picks facts
  (matcher mapping + title/posting word stems), fixed true sentences for role/company/MSc/internship, model writes
  hook / 2 evidence paragraphs / closing; program checks (numbers incl. 8k=8,000, filler, lacking, availability)
  + model claim check per part; one rewrite; fallback = the fact as a plain sentence. v4 BMW letter: no issues.
- Chat agents: matcher reads data/jobs/ranked.md first and always shows IDs; writer prompt has placeholder IDs
  (no copying); reviewer never suggests adding skills; Job Desk knows run_now/schedule.
- output/ has earlier BMW test versions v1-v3 (+ tracker rows); v4 is the good one. Not deleted (user's folder).

## Clean slate (2026-10-12 12:37, user request)
All job-agent data (data/jobs, output/, data/job-desk/notes.md) moved to ~/.Trash/agentfactory-job-data-20261012-1237.
Kept: inputs/master_cv.pdf, templates, code, specs, the every-3-hours schedule. A scheduled run without a profile
stops with "No profile yet" until Job Desk step 1 (extract_cv) has run again.

## 2026-10-21: one automatic flow with an OK step; three bugs fixed
User request: Job Desk "search for jobs" runs everything; only ask before writing CVs; no clicking between agents.
- Bug 1 (every agent): opening a chat starts a prefill that set the SHARED provider's num_predict to 1; a message
  sent meanwhile got a one-word reply ("We"). factory/llm.py prefill now uses a copy. Test in test_llm.py.
- Bug 2 (Job Desk never ran a program from the chat): Ollama 0.32.13's tool parsing stopped qwen3:8b after ~16
  tokens mid-call and returned an empty reply; the raw output (api/generate raw) was a correct <tool_call> every
  time. Not the prompt, cache, enum or tool names (bisected). Fix: OllamaProvider(tools_as_text=True), on in
  make_provider: tools go into the system prompt in the template's own words, calls are read from <tool_call> text
  (streamed tool-call text is never shown). Live: Job Desk calls run_now at once.
- Bug 3 (schedule never ran): the LaunchAgent exited 78; macOS blocks background jobs from reading ~/Downloads
  (confirmed: `ls` there failed "Operation not permitted" under launchd). User chose: the app runs it. schedule.py
  now writes data/jobs/schedule.json and removed the LaunchAgent; serve.py checks every 30 s (schedule_tick).
- Flow: pipeline.py {} = search + match, then status "waiting" with the good matches (best max_drafts_per_run
  ticked); {"approve": [...], "decline": [...]} = documents; declined get note DECLINED and are not offered again.
  data/jobs/run_status.json drives the Job Desk panel (static/app.js renderRun; /api/jobs/run, /api/jobs/choose,
  /api/jobs/file limited to output/ .pdf/.md). Job Desk prompt rewritten: never sends the user to another agent.
- Ollama runs 2 slots on its own (log shows slot 0 and 1) even though OLLAMA_NUM_PARALLEL is gone from the plist.
- CVs fill the page (user, angrily): render.py fill_page adds left-out master facts (experience bullets, project
  bullets, other master projects) while the printed PDF stays one page, then prints with .page.fill. All CVs end at
  816.7 of 841.9 pt. Template self-test unchanged (v6 = v5). Today's 5 CVs re-printed as v2; panel points at v2.
