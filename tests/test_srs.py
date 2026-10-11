from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from factory import srs
from factory.llm import LLMResponse, MockProvider, ToolCall
from factory.runtime import AgentSession
from factory.schema import AgentSpec
from factory.tools import IMPLEMENTED, ToolError


@pytest.fixture
def ctx(tmp_path):
    return SimpleNamespace(spec=SimpleNamespace(name="german-teacher"), base_dir=tmp_path)


@pytest.fixture
def today(monkeypatch):
    now = {"day": date(2026, 1, 1)}
    monkeypatch.setattr(srs, "_today", lambda: now["day"])
    return now


def add(ctx, front="der Tisch", back="the table", **extra):
    return srs.srs_add(ctx, {"front": front, "back": back, **extra})


def test_the_tools_are_registered_under_their_dotted_names():
    assert {"srs.add", "srs.due", "srs.review"} <= set(IMPLEMENTED)
    assert IMPLEMENTED["srs.add"].model_name == "srs_add"


def test_add_then_due_shows_the_card_with_front_and_back(ctx, today):
    assert "1 card" in add(ctx, tags="nouns")
    out = srs.srs_due(ctx, {})
    assert "FRONT: der Tisch" in out and "the table" in out and "[nouns]" in out


def test_adding_the_same_front_twice_is_ignored(ctx, today):
    add(ctx)
    assert "Already in the box" in add(ctx, front="DER  tisch", back="x")
    assert "1 due today" in srs.srs_due(ctx, {})


def test_a_good_answer_pushes_the_card_out_and_hides_it_until_then(ctx, today):
    add(ctx)
    assert "in 1 day" in srs.srs_review(ctx, {"id": 1, "grade": "good"})
    assert "Nothing is due" in srs.srs_due(ctx, {})
    today["day"] += timedelta(days=1)
    assert "FRONT: der Tisch" in srs.srs_due(ctx, {})


def test_gaps_grow_with_each_good_answer(ctx, today):
    add(ctx)
    gaps = []
    for _ in range(4):
        out = srs.srs_review(ctx, {"id": 1, "grade": "good"})
        gap = int(out.split("in ")[1].split(" day")[0])
        gaps.append(gap)
        today["day"] += timedelta(days=gap)
    assert gaps[:2] == [1, 3] and gaps[2] > gaps[1] and gaps[3] > gaps[2]


def test_again_brings_the_card_back_today_and_resets_progress(ctx, today):
    add(ctx)
    srs.srs_review(ctx, {"id": 1, "grade": "good"})
    today["day"] += timedelta(days=1)
    assert "today again" in srs.srs_review(ctx, {"id": 1, "grade": "again"})
    assert "FRONT: der Tisch" in srs.srs_due(ctx, {})
    assert "in 1 day" in srs.srs_review(ctx, {"id": 1, "grade": "good"})


def test_easy_jumps_further_than_good(ctx, today):
    add(ctx)
    assert "in 3 days" in srs.srs_review(ctx, {"id": 1, "grade": "easy"})


def test_due_limit_is_respected_and_capped(ctx, today):
    for i in range(14):
        add(ctx, front=f"Wort {i}", back=f"word {i}")
    assert srs.srs_due(ctx, {"limit": 3}).count("FRONT:") == 3
    out = srs.srs_due(ctx, {"limit": 99})
    assert out.count("FRONT:") == 10 and "14 due today" in out


def test_empty_box_and_nothing_due_messages(ctx, today):
    assert "empty" in srs.srs_due(ctx, {})
    add(ctx)
    srs.srs_review(ctx, {"id": 1, "grade": "good"})
    assert "next one is due 2026-01-02" in srs.srs_due(ctx, {})


@pytest.mark.parametrize("args", [{"front": "", "back": "x"}, {"front": "x"}, {"front": 5, "back": "x"},
                                  {"front": "x" * 500, "back": "y"}])
def test_add_rejects_bad_input(ctx, args):
    with pytest.raises(ToolError):
        srs.srs_add(ctx, args)


@pytest.mark.parametrize("args", [{"id": "abc", "grade": "good"}, {"id": 99, "grade": "good"},
                                  {"id": 1, "grade": "great"}, {"id": 1, "grade": 2}, {"id": 1}])
def test_review_rejects_bad_input(ctx, today, args):
    add(ctx)
    with pytest.raises(ToolError):
        srs.srs_review(ctx, args)


def test_each_agent_has_its_own_box(tmp_path, today):
    a = SimpleNamespace(spec=SimpleNamespace(name="agent-a"), base_dir=tmp_path)
    b = SimpleNamespace(spec=SimpleNamespace(name="agent-b"), base_dir=tmp_path)
    add(a)
    assert "empty" in srs.srs_due(b, {})


def test_text_is_stored_as_plain_text_not_sql(ctx, today):
    add(ctx, front="x'); DROP TABLE cards;--", back="ok")
    assert "DROP TABLE" in srs.srs_due(ctx, {})


def test_an_agent_can_use_the_tools_end_to_end(tmp_path):
    spec = AgentSpec.model_validate({"name": "german-teacher", "goal": "Teach me German vocabulary",
                                     "tools": ["srs.add", "srs.due"], "memory": {"srs": True}})
    provider = MockProvider([
        LLMResponse(tool_calls=[ToolCall("srs_add", {"front": "das Haus", "back": "the house"})]),
        LLMResponse(tool_calls=[ToolCall("srs_due", {})]),
        LLMResponse(content="Was heisst 'das Haus'?"),
    ])
    result = AgentSession(spec, provider, base_dir=tmp_path).send("Lerne mit mir")
    outputs = [e["output"] for e in result.trace if e["event"] == "tool"]
    assert result.ok and "Card added" in outputs[0] and "FRONT: das Haus" in outputs[1]


def test_notes_can_be_read_back(tmp_path):
    from factory.tools import ToolContext
    spec = AgentSpec.model_validate({"name": "german-teacher", "goal": "Teach me German vocabulary",
                                     "tools": ["notes.read", "notes.append"], "memory": {"notes": True}})
    ctx = ToolContext(spec, tmp_path)
    read, append = IMPLEMENTED["notes.read"].func, IMPLEMENTED["notes.append"].func
    assert "no notes" in read(ctx, {})
    append(ctx, {"text": "Level A2, weak on dative"})
    assert "dative" in read(ctx, {})


def test_the_german_teacher_file_loads_and_every_tool_exists():
    from pathlib import Path
    from factory.schema import load_spec
    path = Path(__file__).parent.parent / "specs" / "german-teacher.yaml"
    if not path.exists():
        pytest.skip("specs/german-teacher.yaml was removed by the user")
    spec = load_spec(path)
    assert not [t for t in spec.tools if t not in IMPLEMENTED]
    assert spec.memory.srs and spec.memory.notes


def test_the_page_can_list_the_cards_without_creating_a_box(ctx, today):
    assert srs.list_cards(ctx) == {"cards": [], "total": 0, "due_today": 0}
    assert not (ctx.base_dir / "data" / "german-teacher" / "cards.db").exists()
    add(ctx, front="the dog", back="der Hund")
    add(ctx, front="the cat", back="die Katze")
    srs.srs_review(ctx, {"id": 1, "grade": "good"})
    listed = srs.list_cards(ctx)
    assert listed["total"] == 2 and listed["due_today"] == 1
    assert [c["front"] for c in listed["cards"]] == ["the cat", "the dog"]  # soonest due first
    assert listed["cards"][1]["reps"] == 1
