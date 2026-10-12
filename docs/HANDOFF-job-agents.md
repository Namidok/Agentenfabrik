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
- 7 old flashcards in data/german-teacher/cards.db are wrong German; asked earlier whether to delete, no answer.
- Real data now holds: profile_v1 (+ .md), projects_v1..v3, preferences_v1 (from the user's stated preferences),
  7 postings, jobs_v1, shortlist_v1..v2, briefs for li-4438674690 (v1, v2). output/ is still empty.
