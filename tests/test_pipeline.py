"""The automatic run (scripts/jobs/pipeline.py and auto_agents.py), offline: a scripted model, fake programs."""
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "jobs"))

import auto_agents as A  # noqa: E402
import pipeline  # noqa: E402
import render  # noqa: E402
import run_now  # noqa: E402
import schedule  # noqa: E402
from factory.llm import LLMResponse, MockProvider  # noqa: E402

PROFILE = {
    "header": {"name": "Ada Test", "headline": "MSc Computer Science (Big Data & AI) · LLM tooling", "contact": ["Berlin"]},
    "summary": [{"id": "F001", "text": "MSc student who builds **LLM tools**."}, {"id": "F002", "text": "3 years of software work."},
                {"id": "F003", "text": "Daily user of coding assistants."}],
    "skills": [{"id": "S1", "label": "Programming", "items": "Python, SQL"}, {"id": "S2", "label": "AI", "items": "LangGraph, RAG"}],
    "experience": [
        {"id": "E1", "title": "Developer", "org": "Acme", "location": "Pune", "dates": "2023 – 2025",
         "bullets": [{"id": "F004", "text": "Built a support chatbot that resolved ~72% of queries."},
                     {"id": "F005", "text": "Cut page load from 3.8 s to 1.6 s for 40,000+ users."},
                     {"id": "F006", "text": "Led QA for 18+ releases."}]},
        {"id": "E2", "title": "Trainee", "org": "Beta", "location": "Pune", "dates": "2022 – 2023",
         "bullets": [{"id": "F007", "text": "Tested 40+ functions with pytest."}]},
    ],
    "projects": [
        {"id": "CP1", "name": "VoiceBot", "tagline": "Voice agent", "stack": ["Swift"], "link": "github.com/ada/voicebot",
         "bullets": [{"id": "F008", "text": "Built a voice and text agent (~8k lines of Swift) with 52 unit tests."}]},
        {"id": "CP2", "name": "bench", "tagline": "LLM benchmark", "stack": ["Python"], "link": "github.com/ada/bench",
         "bullets": [{"id": "F009", "text": "Ran 180 controlled runs with deterministic scoring."}]},
        {"id": "CP3", "name": "crew", "tagline": "Multi-agent pipeline", "stack": ["Python"], "link": "github.com/ada/crew",
         "bullets": [{"id": "F010", "text": "Built a 5-agent pipeline that runs every 2 hours."}]},
    ],
    "education": [{"id": "ED1", "degree": "MSc CS", "school": "SRH Berlin", "note": "Internship required", "dates": "2025 – 2027"}],
}
JOB = {"id": "li-1", "title": "Intern Agentic AI for Voice Assistants (m/w/d)", "company": "BMW Group", "location": "Munich",
       "description": "Build agentic voice assistant features with LLMs and Python.", "criteria": {"Employment type": "Internship"}}
MATCH = {"requirements": [{"need": "voice agents", "shown_by": ["F008"]}, {"need": "agent pipelines", "shown_by": ["F010", "CP3"]},
                          {"need": "Python", "shown_by": ["S1"]}], "gaps": ["MCP"], "fit": 82, "verdict": "apply"}


def reply(value) -> LLMResponse:
    return LLMResponse(content=json.dumps(value))


# ---------- text clean-up ----------

def test_clean_text_removes_ids_and_source_notes_and_ends_the_sentence():
    assert A.clean_text("My internship (ED1) is required (sources: ED1, F001)") == "My internship is required."
    assert A.clean_text('built it (F013, F016) "fast"') == "Built it 'fast'."


def test_remove_filler_replaces_stock_phrases():
    assert A.remove_filler("I am excited to join. I believe it aligns with my work.") == "I want to join. It matches my work."


def test_number_check_treats_8k_and_8000_as_the_same():
    texts = {"F008": "~8k lines and 40,000+ users"}
    assert render.unsupported_numbers("8,000 lines for 40000 users", ["F008"], texts) == []
    assert render.unsupported_numbers("9,000 lines", ["F008"], texts) == ["9000"]


# ---------- choosing the CV's contents ----------

def test_relevance_prefers_facts_the_matcher_cited_and_the_title_words():
    scores = A.relevance(JOB, MATCH, PROFILE, [])
    assert scores["F008"] > scores["F009"]  # voice agent, cited and sharing "voice" with the title
    assert scores["CP3"] > scores["CP2"]    # the multi-agent project, cited for "agent pipelines"


def test_select_cv_picks_relevant_projects_and_two_evidence_facts_from_different_places():
    chosen = A.select_cv(A.relevance(JOB, MATCH, PROFILE, []), PROFILE, [])
    ids = [p["id"] for p in chosen["cv"]["projects"]]
    assert ids[0] in ("CP1", "CP3") and "CP2" not in ids[:2]
    assert len(chosen["evidence"]) == 2 and chosen["evidence"][0] != chosen["evidence"][1]
    assert chosen["summary_ids"][0] == "F001"
    assert sum(len(x["bullets"]) for x in chosen["cv"]["experience"] + chosen["cv"]["projects"]) <= 10


def test_github_projects_only_when_the_matcher_cited_them_and_with_a_clean_sentence():
    repo = {"id": "PRJ-x", "name": "x", "summary": "A REST API test agent for PostgreSQL. More text here.", "stack": ["Python"]}
    assert A.repo_sentence(repo) == "A REST API test agent for PostgreSQL."
    assert A.relevance(JOB, MATCH, PROFILE, [repo])["PRJ-x"] == 0.0
    cited = {**MATCH, "requirements": MATCH["requirements"] + [{"need": "APIs", "shown_by": ["PRJ-x"]}]}
    assert A.relevance(JOB, cited, PROFILE, [repo])["PRJ-x"] > 0
    assert A.repo_sentence({"summary": "A modern website with a sleek dark theme and Features"}) == ""


# ---------- the model steps, scripted ----------

def test_match_job_derives_the_verdict_from_the_fit():
    m = MockProvider([reply({"requirements": [{"need": "voice", "shown_by": ["F008", "F999"]}], "gaps": [], "german_needed": "none",
                             "internship": True, "fit": 65, "verdict": "apply", "reason": "ok"})])
    out = A.match_job(m, JOB, PROFILE, [])
    assert out["verdict"] == "maybe" and out["requirements"][0]["shown_by"] == ["F008"]
    assert "F008" in json.dumps(m.calls[0]["schema"])  # fact IDs are an enum in the answer's shape
    assert "IGNORE" not in m.calls[0]["messages"][0]["content"]


def test_match_job_skips_non_internships():
    m = MockProvider([reply({"requirements": [], "gaps": [], "german_needed": "none", "internship": False, "fit": 90,
                             "verdict": "apply", "reason": "senior role"})])
    assert A.match_job(m, JOB, PROFILE, [])["verdict"] == "skip"


def test_summary_rewording_that_drifts_falls_back_to_the_fact():
    m = MockProvider([reply({"focus": "Agentic AI · Voice", "sentences": [
        "MSc student who builds LLM tools for voice agents.", "Expert in Kubernetes, Rust and quantum computing."]})])
    focus, summary = A.write_summary(m, JOB, PROFILE, ["F001", "F002"])
    assert focus == "Agentic AI"
    assert summary[0]["source"] == "F001" and summary[1] == "F002"


def test_write_parts_rewrites_only_the_flagged_parts():
    first = {"hook": "I want to build voice agents.", "evidence_1": "At Acme, I built a chatbot.", "evidence_2": "In crew, I built it.",
             "contribution": "I would build voice features."}
    m = MockProvider([reply({**first, "hook": "Your voice assistant work matches what I build.", "evidence_1": "changed"})])
    parts = A.write_parts(m, JOB, MATCH, PROFILE, ["F004", "F010"], redo={"hook": "generic"}, previous=first)
    assert parts["hook"] == "Your voice assistant work matches what I build." and parts["evidence_1"] == first["evidence_1"]
    assert "PROBLEM: generic" in m.calls[0]["messages"][1]["content"]


def test_letter_has_the_fixed_true_sentences():
    parts = {"hook": "Your voice work matches mine.", "evidence_1": "a.", "evidence_2": "b.", "contribution": "I would help."}
    letter = A.assemble_letter(parts, "BMW Group", "Agentic AI Intern", ["F004", "F010"])
    assert letter[0]["text"].startswith("I am applying for the Agentic AI Intern role at BMW Group.")
    assert A.role_phrase("Intern Agentic AI for Voice Assistants") == "the Agentic AI for Voice Assistants internship"
    assert A.role_phrase("Praktikum Data Science") == "the Data Science internship"
    assert A.fix_places("At VoiceBot, I built it. At Acme, I led QA.", PROFILE) == "In VoiceBot, I built it. At Acme, I led QA."
    assert "mandatory internship" in letter[0]["text"] and letter[1]["sources"] == ["F004"]
    assert "available" not in " ".join(p["text"] for p in letter)
    assert "I am available from March 2027." in A.assemble_letter(parts, "BMW", "Intern", ["F004", "F010"], "from March 2027")[3]["text"]


def test_part_problems_and_review_flag_only_real_problems():
    texts = render.source_texts(PROFILE, None)
    parts = {"hook": "I am excited about your work.", "evidence_1": "At Acme, I resolved ~72% of queries.",
             "evidence_2": "In crew, I built a 9-agent pipeline.", "contribution": "I am available from May for 6 months."}
    found = A.part_problems(parts, ["F004", "F010"], texts, "BMW", "Intern")
    assert set(found) == {"hook", "evidence_2", "contribution"}
    m = MockProvider([reply({k: {"ok": k != "evidence_1", "claim_not_in_facts": "" if k != "evidence_1" else "says 99 users"} for k in A.PARTS})])
    assert list(A.review_parts(m, JOB, parts, PROFILE, ["F004", "F010"])) == ["evidence_1"]


def test_safety_nets_replace_broken_evidence_and_drop_invented_sentences():
    texts = render.source_texts(PROFILE, None)
    letter = [{"text": "I am applying. I start in March for 6 months.", "sources": ["ED1"]},
              {"text": "At Acme, I resolved 95% of queries.", "sources": ["F004"]},
              {"text": "In crew, I built a 5-agent pipeline.", "sources": ["F010"]},
              {"text": "I would help.", "sources": ["F004", "F010"]}]
    replaced = A.safe_evidence(letter, texts, PROFILE, "BMW", "Intern")
    assert replaced == ["At Acme, I resolved 95% of queries."]
    assert letter[1]["text"].startswith("At Acme, I built a support chatbot that resolved ~72%")
    removed = A.drop_unsupported(letter, texts, "BMW", "Intern")
    assert removed == ["I start in March for 6 months."] and letter[0]["text"] == "I am applying."


def test_mechanical_review_catches_the_usual_mistakes():
    texts = render.source_texts(PROFILE, None)
    letter = [{"text": "I am passionate about AI and I do not have experience with MCP.", "sources": ["ED1"]}]
    problems = " ".join(A.mechanical_review(letter, [], texts, "BMW", "Intern"))
    for expected in ("generic wording", "lacks", "never names BMW", "mandatory internship", "words"):
        assert expected in problems


# ---------- the run ----------

def test_search_window_is_24_hours_on_the_first_run_of_a_day_then_since_the_last_run():
    now = datetime(2026, 10, 12, 15, 0)
    assert pipeline.window({}, now)[:2] == (24, 2)
    assert pipeline.window({"last_day": "2026-10-11", "last_run": "2026-10-11T21:00"}, now)[:2] == (24, 2)
    assert pipeline.window({"last_day": "2026-10-12", "last_run": "2026-10-12T12:00"}, now)[:2] == (4.0, 1)


def test_clean_role_drops_gender_tags():
    assert pipeline.clean_role("Intern Agentic AI (m/w/d)*") == "Intern Agentic AI"
    assert pipeline.clean_role("Praktikant Data (w/m/x)") == "Praktikant Data"


@pytest.fixture
def run_world(tmp_path, monkeypatch):
    data, out = tmp_path / "data" / "jobs", tmp_path / "output"
    (data / "me").mkdir(parents=True)
    (data / "postings").mkdir()
    (data / "me" / "profile_v1.json").write_text(json.dumps(PROFILE))
    (data / "postings" / "li-1.json").write_text(json.dumps(JOB))
    for name, value in (("DATA", data), ("ME", data / "me"), ("OUTPUT", out), ("POSTINGS", data / "postings"), ("ROOT", tmp_path),
                        ("MATCHES", data / "matches"), ("STATE", data / "pipeline_state.json"), ("LOCK", data / "pipeline.lock"),
                        ("RUNS", out / "runs"), ("STATUS", data / "run_status.json")):
        monkeypatch.setattr(pipeline, name, value)
    monkeypatch.setenv("AGENTFACTORY_NO_NOTIFY", "1")
    calls = []

    def fake_script(name, arguments, timeout=900):
        calls.append((name, arguments))
        if name == "scrape_jobs":
            return {"ok": True, "saved": 1, "requests_used": 6}
        if name == "shortlist":
            (data / "shortlist_v1.json").write_text(json.dumps({"jobs": [{"id": "li-1", "score": 70, "flags": []}]}))
            return {"ok": True, "file": "data/jobs/shortlist_v1.json"}
        if name == "render":
            return {"ok": True, "cv": "output/bmw_cv_v1.pdf", "cover_letter": "output/bmw_cover_letter_v1.pdf", "problems": []}
        return {"ok": False}
    monkeypatch.setattr(pipeline, "run_script", fake_script)
    answers = {
        "job-matcher": [reply({**MATCH, "german_needed": "none", "internship": True, "reason": "voice agent experience"})],
        "application-writer": [reply({"focus": "Agentic AI & Voice", "sentences": ["MSc student who builds LLM tools for agents.",
                                                                                  "3 years of software work.", "Daily user of coding assistants."]}),
                               reply({"hook": "Your voice assistant work matches what I build.",
                                      "evidence_1": "In VoiceBot, I built a voice and text agent with 52 unit tests.",
                                      "evidence_2": "In crew, I built a 5-agent pipeline that runs every 2 hours.",
                                      "contribution": "I would build agentic voice features with your team."})],
        "application-reviewer": [reply({k: {"ok": True, "claim_not_in_facts": ""} for k in A.PARTS})],
    }
    monkeypatch.setattr(A, "provider_for", lambda agent, **kw: MockProvider(answers[agent]))
    return tmp_path, calls


def run(monkeypatch, capsys, arguments: dict) -> dict:
    monkeypatch.setattr(sys, "argv", ["pipeline", json.dumps(arguments)])
    pipeline.main()
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def status(root: Path) -> dict:
    return json.loads((root / "data" / "jobs" / "run_status.json").read_text())


def test_a_search_ranks_then_waits_for_the_users_ok(run_world, capsys, monkeypatch):
    root, calls = run_world
    result = run(monkeypatch, capsys, {})
    assert result["ok"] and result["waiting"] == ["li-1"] and result["documents"] == [] and result["ranked"] == 1
    assert [c[0] for c in calls] == ["scrape_jobs", "shortlist"]  # no document without the OK
    assert calls[0][1] == {"hours": 24, "pages": 2}
    s = status(root)
    assert s["state"] == "waiting" and s["waiting"][0]["id"] == "li-1" and s["waiting"][0]["pick"] is True
    assert s["waiting"][0]["company"] == "BMW Group" and s["waiting"][0]["fit"] == 82
    assert any("Job Matcher" in line for line in s["log"])
    report = (root / result["report"]).read_text()
    assert "li-1" in report and "Waiting for your OK" in report
    assert "li-1" in (root / "output" / "ranked_jobs.md").read_text()
    assert "waiting for your OK" in (root / "data" / "job-desk" / "notes.md").read_text()
    assert not (root / "data" / "jobs" / "pipeline.lock").exists()


def test_the_ok_writes_checks_and_prints_the_documents(run_world, capsys, monkeypatch):
    root, calls = run_world
    run(monkeypatch, capsys, {})
    result = run(monkeypatch, capsys, {"approve": ["li-1"]})
    assert result["ok"] and result["documents"] == ["li-1"]
    assert [c[0] for c in calls] == ["scrape_jobs", "shortlist", "render"]
    match = json.loads((root / "data" / "jobs" / "matches" / "li-1.json").read_text())
    assert match["fit"] == 82 and match["documents"]["cv"] == "output/bmw_cv_v1.pdf"
    draft = json.loads((root / "output" / "drafts" / "li-1_auto_v1.json").read_text())
    assert draft["role"] == "Intern Agentic AI for Voice Assistants" and draft["cv"]["headline"].endswith("· Agentic AI & Voice")
    assert "mandatory internship" in draft["cover_letter"]["paragraphs"][0]["text"]
    assert draft["cv"]["projects"][0]["id"] in ("CP1", "CP3")
    assert "nothing has been sent" in (root / result["report"]).read_text()
    s = status(root)
    assert s["state"] == "done" and s["waiting"] == [] and s["result"]["files"][0]["cv"] == "output/bmw_cv_v1.pdf"
    assert {line.split("] ")[1].split(":")[0].strip() for line in s["log"]} >= {"CV Writer", "CV Reviewer", "Job Desk"}
    assert "1 CV written" in (root / "data" / "job-desk" / "notes.md").read_text()


def test_declined_jobs_are_not_offered_again(run_world, capsys, monkeypatch):
    root, calls = run_world
    run(monkeypatch, capsys, {})
    result = run(monkeypatch, capsys, {"decline": ["li-1"]})
    assert result["declined"] == ["li-1"] and status(root)["state"] == "idle" and status(root)["waiting"] == []
    assert json.loads((root / "data" / "jobs" / "matches" / "li-1.json").read_text())["note"] == pipeline.DECLINED
    calls.clear()
    assert run(monkeypatch, capsys, {})["waiting"] == []
    assert "render" not in [c[0] for c in calls]


def test_a_crash_shows_as_failed_in_the_app(run_world, capsys, monkeypatch):
    root, calls = run_world
    monkeypatch.setattr(pipeline, "search_run", lambda *a: 1 / 0)
    monkeypatch.setattr(sys, "argv", ["pipeline", "{}"])
    with pytest.raises(ZeroDivisionError):
        pipeline.main()
    assert status(root)["state"] == "failed" and "ZeroDivisionError" in status(root)["detail"]
    assert not (root / "data" / "jobs" / "pipeline.lock").exists()


def test_a_second_run_skips_jobs_already_ranked(run_world, capsys, monkeypatch):
    root, calls = run_world
    (root / "data" / "jobs" / "matches").mkdir(parents=True)
    (root / "data" / "jobs" / "matches" / "li-1.json").write_text(json.dumps({"id": "li-1", "fit": 80}))
    monkeypatch.setattr(sys, "argv", ["pipeline", "{}"])
    pipeline.main()
    result = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert result["ranked"] == 0 and [c[0] for c in calls] == ["scrape_jobs"]


def test_a_run_does_not_start_while_another_is_going(run_world, capsys, monkeypatch):
    root, calls = run_world
    (root / "data" / "jobs" / "pipeline.lock").write_text(str(__import__("os").getpid()))
    monkeypatch.setattr(sys, "argv", ["pipeline", "{}"])
    pipeline.main()
    assert "still going" in capsys.readouterr().out and calls == []


def test_the_models_german_guess_does_not_block_a_job(run_world, capsys, monkeypatch):
    root, calls = run_world
    answers = [reply({**MATCH, "german_needed": "fluent", "internship": True, "reason": "x"})]
    real_provider = A.provider_for

    def provider(agent, **kw):
        return MockProvider(answers) if agent == "job-matcher" else real_provider(agent, **kw)
    monkeypatch.setattr(A, "provider_for", provider)
    assert run(monkeypatch, capsys, {})["waiting"] == ["li-1"]


def test_german_required_jobs_are_ranked_but_not_written(run_world, capsys, monkeypatch):
    root, calls = run_world
    monkeypatch.setattr(A, "provider_for", lambda agent, **kw: MockProvider(
        [reply({**MATCH, "german_needed": "none", "internship": True, "reason": "x"})]))
    real = pipeline.run_script

    def flagged(name, arguments, timeout=900):
        out = real(name, arguments, timeout)
        if name == "shortlist":
            (root / "data" / "jobs" / "shortlist_v1.json").write_text(json.dumps({"jobs": [{"id": "li-1", "score": 60, "flags": ["german_required"]}]}))
        return out
    monkeypatch.setattr(pipeline, "run_script", flagged)
    monkeypatch.setattr(sys, "argv", ["pipeline", "{}"])
    pipeline.main()
    match = json.loads((root / "data" / "jobs" / "matches" / "li-1.json").read_text())
    assert "German" in match["note"] and "render" not in [c[0] for c in calls]


# ---------- schedule and run now ----------

def test_schedule_is_a_setting_the_app_reads(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(schedule, "SETTING", tmp_path / "schedule.json")
    monkeypatch.setattr(schedule, "DATA", tmp_path)
    monkeypatch.setattr(schedule, "OLD_PLIST", tmp_path / "missing.plist")
    for action in ({"action": "install", "every_hours": 3}, {"action": "status"}):
        monkeypatch.setattr(sys, "argv", ["schedule", json.dumps(action)])
        schedule.main()
        out = json.loads(capsys.readouterr().out)
        assert out["installed"] and out["times"] == ["00:00", "03:00", "06:00", "09:00", "12:00", "15:00", "18:00", "21:00"]
    assert schedule.every_hours() == 3
    monkeypatch.setattr(sys, "argv", ["schedule", '{"action": "remove"}'])
    schedule.main()
    assert schedule.every_hours() is None and not (tmp_path / "schedule.json").exists()


def test_run_now_refuses_while_a_run_is_going(tmp_path, monkeypatch, capsys):
    lock = tmp_path / "pipeline.lock"
    lock.write_text(str(__import__("os").getpid()))
    monkeypatch.setattr(run_now, "LOCK", lock)
    monkeypatch.setattr(sys, "argv", ["run_now", "{}"])
    with pytest.raises(SystemExit):
        run_now.main()
    assert "already going" in capsys.readouterr().out


def test_off_topic_jobs_are_skipped_without_the_model(run_world, capsys, monkeypatch):
    root, calls = run_world
    real = pipeline.run_script

    def low(name, arguments, timeout=900):
        out = real(name, arguments, timeout)
        if name == "shortlist":
            (root / "data" / "jobs" / "shortlist_v1.json").write_text(json.dumps({"jobs": [{"id": "li-1", "score": 20, "flags": ["role_not_in_title"]}]}))
        return out
    monkeypatch.setattr(pipeline, "run_script", low)
    monkeypatch.setattr(A, "provider_for", lambda agent, **kw: MockProvider([]))  # any model call would fail
    monkeypatch.setattr(sys, "argv", ["pipeline", "{}"])
    pipeline.main()
    match = json.loads((root / "data" / "jobs" / "matches" / "li-1.json").read_text())
    assert match["verdict"] == "skip" and "not an AI/ML" in match["reason"]


def test_not_internship_jobs_are_skipped_by_the_keyword_check(run_world, capsys, monkeypatch):
    root, calls = run_world
    real = pipeline.run_script

    def flags(name, arguments, timeout=900):
        out = real(name, arguments, timeout)
        if name == "shortlist":
            (root / "data" / "jobs" / "shortlist_v1.json").write_text(json.dumps({"jobs": [{"id": "li-1", "score": 60, "flags": ["not_internship"]}]}))
        return out
    monkeypatch.setattr(pipeline, "run_script", flags)
    monkeypatch.setattr(A, "provider_for", lambda agent, **kw: MockProvider([]))
    monkeypatch.setattr(sys, "argv", ["pipeline", "{}"])
    pipeline.main()
    assert json.loads((root / "data" / "jobs" / "matches" / "li-1.json").read_text())["reason"] == "keyword check: not_internship"


def test_good_matches_from_an_earlier_run_are_offered_again(run_world, capsys, monkeypatch):
    root, calls = run_world
    (root / "data" / "jobs" / "matches").mkdir(parents=True)
    (root / "data" / "jobs" / "matches" / "li-1.json").write_text(json.dumps({**MATCH, "id": "li-1", "title": JOB["title"],
                                                                            "company": "BMW Group", "flags": [], "keyword_score": 70}))
    assert run(monkeypatch, capsys, {})["waiting"] == ["li-1"]  # offered again, still not written
    assert "render" not in [c[0] for c in calls]
    run(monkeypatch, capsys, {"approve": ["li-1"]})
    assert json.loads((root / "data" / "jobs" / "matches" / "li-1.json").read_text())["documents"]["cv"]
