"""The German teacher spec: its tools, its settings, and the order of its teaching loop.

The loop test uses a scripted provider, so it proves the runtime wiring, not the model.
The live check at the bottom talks to a real Ollama and only runs when you ask for it:
    AGENTFACTORY_LIVE=1 python -m pytest -q tests/test_german_teacher.py -k live -s
"""
import os
from pathlib import Path

import httpx
import pytest

from factory.llm import LLMResponse, MockProvider, ToolCall
from factory.runtime import AgentSession
from factory.schema import load_spec
from factory.tools import IMPLEMENTED

SPEC_PATH = Path(__file__).parent.parent / "specs" / "german-teacher.yaml"
TOOLS = {"notes.read", "notes.append", "srs.add", "srs.due", "srs.review"}


@pytest.fixture
def spec():
    if not SPEC_PATH.exists():
        pytest.skip("specs/german-teacher.yaml was removed by the user")
    return load_spec(SPEC_PATH)


def call(name, **args):
    return ToolCall(name=name, arguments=args)


def tools_used(result):
    return [(e["name"], e["output"]) for e in result.trace if e["event"] == "tool"]


def test_it_has_exactly_the_memory_tools_and_no_other_permissions(spec):
    assert set(spec.tools) == TOOLS
    assert all(t in IMPLEMENTED for t in spec.tools)
    assert spec.memory.notes and spec.memory.srs
    perms = spec.permissions
    assert not (perms.fs_read or perms.fs_write or perms.network or perms.shell)


def test_model_settings_suit_a_chatty_local_model(spec):
    assert spec.mode == "conversational"
    assert spec.model.name == "qwen3:8b"
    assert spec.model.think is False  # thinking was 8x slower and called tools less often
    assert 0.3 <= spec.model.temperature <= 0.5
    assert spec.limits.max_steps <= 12  # a turn needs at most ~4 tool steps and a reply
    assert spec.limits.max_tokens <= 60000  # a turn re-sends the prompt every step, so leave room


def test_the_prompt_spells_out_the_loop(spec):
    prompt = spec.system_prompt
    assert "already given to you" in prompt  # the runtime fetches the notes and due cards, not the model
    for rule in ("srs_due", "srs_add", "srs_review", "notes_append",
                 "No emojis", "A) no German yet", "der/die/das", "Would you like"):
        assert rule in prompt, rule
    assert prompt.count("EXAMPLE") == 2


def test_the_model_sees_all_five_tools_with_their_arguments(spec, tmp_path):
    session = AgentSession(spec, MockProvider([]), base_dir=tmp_path)
    schemas = {s["function"]["name"]: s["function"] for s in session.schemas}
    assert set(schemas) == {t.replace(".", "_") for t in TOOLS}
    assert schemas["srs_add"]["parameters"]["required"] == ["front", "back"]
    assert schemas["srs_review"]["parameters"]["properties"]["grade"]["enum"] == ["again", "hard", "good", "easy"]
    assert "card id" in schemas["srs_add"]["description"]


def test_a_scripted_session_follows_the_loop_and_the_next_chat_remembers(spec, tmp_path):
    provider = MockProvider([
        # 1. chat start: the runtime has already read the notes and due cards; the model asks for the level
        LLMResponse(content="Which fits you? A) no German yet  B) ..."),
        # 2. level given: save it, add the first words, then teach
        LLMResponse(tool_calls=[call("notes_append", text="level: A0 | topic: greetings"),
                                call("srs_add", front="hello", back="Hallo"),
                                call("srs_add", front="bye", back="Tschüss")]),
        LLMResponse(content='Hallo = hello. say: HAH-loh\nYour turn: "hello" in German?'),
        # 3. wrong answer: grade the card it was about, add the next word, correct
        LLMResponse(tool_calls=[call("srs_review", id=1, grade="again"),
                                call("srs_add", front="thank you", back="danke")]),
        LLMResponse(content="Fast richtig: Hallo, with two l.\ndanke = thank you.\nYour turn: \"thank you\"?"),
        # next chat: memory comes back without the model asking for it
        LLMResponse(content="Hallo again. Level A0, last topic: greetings. Karte: hello?"),
    ])
    session = AgentSession(spec, provider, base_dir=tmp_path)

    first = session.send("Let's get started.")
    assert [n for n, _ in tools_used(first)] == ["notes_read", "srs_due"]  # done by the runtime, before the model
    assert "no notes" in tools_used(first)[0][1] and "empty" in tools_used(first)[1][1]
    first_call = provider.calls[0]["messages"]
    assert any(m["role"] == "tool" and m.get("tool_name") == "srs_due" for m in first_call)
    assert "no notes yet" in first_call[-1]["content"]  # the start note tells it the level is unknown

    second = session.send("A) no German yet")
    used = tools_used(second)
    assert [n for n, _ in used] == ["notes_append", "srs_add", "srs_add"]
    assert "id 1" in used[1][1] and "id 2" in used[2][1]  # ids let it grade the card next turn
    assert session.pending_card["id"] == 1  # the reply asks for "hello", which is card 1

    third = session.send("Halo")
    used = tools_used(third)
    assert [n for n, _ in used] == ["srs_review", "srs_add"]
    assert used[0][1].startswith("Saved") and "today again" in used[0][1]
    assert all(r.ok for r in (first, second, third))
    assert not any("Automatic" in str(m["content"]) for m in session.messages)  # notes are for one turn only

    # A new chat starts from the saved notes and the card box.
    later = AgentSession(spec, provider, base_dir=tmp_path)
    assert "shown at the start of each chat" in later.messages[0]["content"]  # notes come with the first message
    again = later.send("Let's continue where we left off.")
    notes_out, due_out = (out for _, out in tools_used(again))
    assert "level: A0" in notes_out
    assert "FRONT: hello" in due_out and "Hallo" in due_out  # the missed card is due again
    start_note = provider.calls[-1]["messages"][-1]["content"]
    assert 'last line of your notes is: "level: A0 | topic: greetings"' in start_note and "Cards are due" in start_note
    assert later.pending_card["id"] == 1  # the reply quizzes "hello"


def _ollama_has(model: str) -> bool:
    try:
        names = [m["name"] for m in httpx.get("http://localhost:11434/api/tags", timeout=1.5).json()["models"]]
    except Exception:
        return False
    return model in names


@pytest.mark.skipif(os.environ.get("AGENTFACTORY_LIVE") != "1", reason="set AGENTFACTORY_LIVE=1 to talk to a real Ollama")
def test_live_first_turns_use_the_tools(spec, tmp_path):
    from factory.llm import make_provider
    if not _ollama_has(spec.model.name):
        pytest.skip(f"Ollama is not running or {spec.model.name} is not installed")
    session = AgentSession(spec, make_provider(spec.model), base_dir=tmp_path)
    first = session.send("Let's get started.")
    second = session.send("A) no German yet")
    third = session.send("Ich habe ein Hund.")
    for r in (first, second, third):
        print("\n", r.final_text, "\n", tools_used(r), [e["message"] for e in r.trace if e["event"] in ("hint", "nudge")])
    assert "notes_read" in [n for n, _ in tools_used(first)]
    assert "srs_add" in [n for n, _ in tools_used(second)]
    assert "srs_review" in [n for n, _ in tools_used(third)]  # the targeted reminder makes sure of it
    assert "einen Hund" in third.final_text  # the grammar hint gets the slip corrected
    assert not any(ord(ch) > 0x1F000 for ch in first.final_text + second.final_text + third.final_text)  # no emojis


# ---------- the flashcard reminder (runtime) ----------

from factory.runtime import CARD_NUDGE  # noqa: E402
from factory.schema import AgentSpec  # noqa: E402


def _reminders(provider):
    return [m for m in provider.calls[-1]["messages"] if m["content"] == CARD_NUDGE]


def test_a_reply_without_card_tools_gets_one_reminder_and_is_redone(spec, tmp_path):
    provider = MockProvider([
        LLMResponse(content="Which fits you? A) ..."),                  # first message: no reminder
        LLMResponse(content="Richtig. Your turn: bye?"),                # answer, no card tool: reminded
        LLMResponse(tool_calls=[call("srs_add", front="bye", back="Tschüss")]),
        LLMResponse(content="Richtig. Tschüss = bye. Your turn: bye?"),
    ])
    session = AgentSession(spec, provider, base_dir=tmp_path)
    first = session.send("Let's get started.")
    assert not [e for e in first.trace if e["event"] == "nudge"]

    second = session.send("Hallo")
    assert [e["event"] for e in second.trace].count("nudge") == 1
    assert len(_reminders(provider)) == 1  # the model saw the reminder...
    assert second.final_text.startswith("Richtig. Tschüss")
    assert not [m for m in session.messages if m["content"] == CARD_NUDGE]  # ...but history did not keep it
    assert "Richtig. Your turn: bye?" not in [m["content"] for m in session.messages]  # draft dropped


def test_the_reminder_is_sent_at_most_once_per_turn(spec, tmp_path):
    provider = MockProvider([
        LLMResponse(content="Which fits you?"),
        LLMResponse(content="draft"),
        LLMResponse(content="still no tools"),
    ])
    session = AgentSession(spec, provider, base_dir=tmp_path)
    session.send("hi")
    result = session.send("ok")
    assert result.ok and result.final_text == "still no tools" and result.steps == 2


def test_no_reminder_when_a_card_tool_ran_or_the_agent_has_no_cards(spec, tmp_path):
    provider = MockProvider([
        LLMResponse(content="Which fits you?"),
        LLMResponse(tool_calls=[call("srs_due")]),
        LLMResponse(content="Nothing due. Hallo = hello."),
    ])
    session = AgentSession(spec, provider, base_dir=tmp_path)
    session.send("hi")
    assert not [e for e in session.send("A").trace if e["event"] == "nudge"]

    plain = AgentSpec.model_validate({"name": "note-taker", "goal": "Keep notes for me", "mode": "conversational",
                                      "tools": ["notes.read"], "memory": {"notes": True}})
    provider = MockProvider([LLMResponse(content="one"), LLMResponse(content="two")])
    session = AgentSession(plain, provider, base_dir=tmp_path)
    session.send("hi")
    assert not [e for e in session.send("again").trace if e["event"] == "nudge"]


# ---------- the targeted review reminder and the grammar check ----------

from factory.runtime import AgentSession as _Session  # noqa: E402


def _teach_one_card(spec, tmp_path, extra):
    """A session where card 1 (hello) was just taught and asked; then the scripted replies in extra."""
    provider = MockProvider([
        LLMResponse(content="Which fits you?"),
        LLMResponse(tool_calls=[call("srs_add", front="hello", back="Hallo")]),
        LLMResponse(content='Hallo = hello. Your turn: "hello" in German?'),
        *extra,
    ])
    session = _Session(spec, provider, base_dir=tmp_path)
    session.send("hi")
    session.send("A")
    return session, provider


def test_an_answer_without_srs_review_gets_one_reminder_naming_the_card(spec, tmp_path):
    session, provider = _teach_one_card(spec, tmp_path, [
        LLMResponse(tool_calls=[call("srs_add", front="bye", back="Tschüss")]),  # a card tool, but no grade
        LLMResponse(content="Richtig. Tschüss = bye. Your turn: bye?"),
        LLMResponse(tool_calls=[call("srs_review", id=1, grade="good")]),
        LLMResponse(content="Richtig. Your turn: bye?"),
    ])
    result = session.send("Hallo")
    nudges = [e for e in result.trace if e["event"] == "nudge"]
    assert len(nudges) == 1 and "card 1" in nudges[0]["message"]
    reminder = provider.calls[-2]["messages"][-1]["content"]
    assert "answers card 1" in reminder and '"hello"' in reminder
    assert [n for n, _ in tools_used(result)][-1] == "srs_review"
    assert session.pending_card["id"] == 2  # now the student owes an answer for "bye"


def test_ok_is_not_an_answer_and_the_reminder_cap_stays_at_one(spec, tmp_path):
    session, provider = _teach_one_card(spec, tmp_path, [
        LLMResponse(tool_calls=[call("srs_add", front="bye", back="Tschüss")]),
        LLMResponse(content="Tschüss = bye. Your turn: bye?"),
        LLMResponse(content="draft without tools"),
        LLMResponse(content="still without tools"),
    ])
    ok = session.send("ok")
    assert not [e for e in ok.trace if e["event"] == "nudge"]  # "ok" answers nothing, and a card was added
    result = session.send("Tschüs")
    assert [e["event"] for e in result.trace].count("nudge") == 1
    assert result.final_text == "still without tools"


def test_a_grammar_slip_reaches_the_model_as_a_hint(spec, tmp_path):
    session, provider = _teach_one_card(spec, tmp_path, [
        LLMResponse(tool_calls=[call("srs_review", id=1, grade="again")]),
        LLMResponse(content="Fast richtig: Ich habe einen Hund."),
    ])
    result = session.send("Ich habe ein Hund.")
    hints = [e for e in result.trace if e["event"] == "hint"]
    assert len(hints) == 1 and '"einen Hund"' in hints[0]["message"]
    seen = provider.calls[-2]["messages"][-1]["content"]
    assert "Automatic grammar check" in seen and "accusative" in seen
    assert not any("grammar check" in str(m["content"]) for m in session.messages)


def test_agents_without_flashcards_get_none_of_this(tmp_path):
    from factory.schema import AgentSpec
    plain = AgentSpec.model_validate({"name": "note-taker", "goal": "Keep notes for me", "mode": "conversational",
                                      "tools": ["notes.read"], "memory": {"notes": True}})
    provider = MockProvider([LLMResponse(content="one"), LLMResponse(content="two")])
    session = _Session(plain, provider, base_dir=tmp_path)
    first = session.send("Ich habe ein Hund.")
    assert not [e for e in first.trace if e["event"] in ("tool", "hint", "nudge")]
    assert len(provider.calls[0]["messages"]) == 2  # system and the user's message, nothing injected


def test_more_than_three_new_cards_in_one_reply_are_refused(spec, tmp_path):
    from factory import srs
    two = [call("srs_add", front=f"word {i}", back=f"Wort {i}") for i in range(2)]
    later = [call("srs_add", front=f"word {i}", back=f"Wort {i}") for i in range(2, 4)]
    provider = MockProvider([LLMResponse(tool_calls=two), LLMResponse(tool_calls=later), LLMResponse(content="Lektion 1 ...")])
    provider.streams = False  # a provider that cannot be stopped early: the runtime still refuses the 4th card
    result = AgentSession(spec, provider, base_dir=tmp_path).send("Let's get started.")
    outputs = [out for name, out in tools_used(result) if name == "srs_add"]
    assert [o.startswith("Card added") for o in outputs] == [True, True, True, False]  # the 4th, in a later step
    assert "limit" in outputs[3]
    assert srs.list_cards(AgentSession(spec, MockProvider([]), base_dir=tmp_path).ctx)["total"] == 3


def test_a_reply_that_ignores_the_grammar_slip_is_redone_once(spec, tmp_path):
    session, provider = _teach_one_card(spec, tmp_path, [
        LLMResponse(tool_calls=[call("srs_review", id=1, grade="again")]),
        LLMResponse(content="Der Hund ist klein. Your turn: the dog?"),  # no correction
        LLMResponse(content="Fast richtig: Ich habe einen Hund. Hund is masculine."),
    ])
    result = session.send("Ich habe ein Hund.")
    nudges = [e["message"] for e in result.trace if e["event"] == "nudge"]
    assert nudges == ["Asked the model to correct: einen Hund"]
    assert result.final_text.startswith("Fast richtig: Ich habe einen Hund")
    assert not any("Automatic" in str(m["content"]) for m in session.messages)


def test_the_model_is_stopped_once_three_new_cards_have_arrived(spec, tmp_path):
    many = [call("srs_add", front=f"word {i}", back=f"Wort {i}") for i in range(8)]
    provider = MockProvider([LLMResponse(tool_calls=many), LLMResponse(content="Lektion 1 ...")])
    result = AgentSession(spec, provider, base_dir=tmp_path).send("Let's get started.")
    added = [out for name, out in tools_used(result) if name == "srs_add"]
    assert len(added) == 3 and all(o.startswith("Card added") for o in added)  # the rest was never written
    assert any("after 3 new cards" in e.get("message", "") for e in result.trace if e["event"] == "warning")


def test_only_the_latest_notes_are_shown_and_the_system_prompt_stays_the_same(spec, tmp_path):
    from factory.study import NOTES_TAIL
    folder = tmp_path / "data" / spec.name
    folder.mkdir(parents=True)
    (folder / "notes.md").write_text("".join(f"level: A0 | topic: chapter {i}\n" for i in range(30)))
    provider = MockProvider([LLMResponse(content="Hallo again.")])
    session = AgentSession(spec, provider, base_dir=tmp_path)
    assert "chapter" not in session.messages[0]["content"]  # notes are not in the system prompt
    result = session.send("Let's continue.")
    notes_out = tools_used(result)[0][1]
    assert "chapter 29" in notes_out and "chapter 0\n" not in notes_out and f"{30 - NOTES_TAIL} older lines" in notes_out
    (folder / "notes.md").write_text("something else entirely\n")
    assert AgentSession(spec, MockProvider([]), base_dir=tmp_path).messages[0]["content"] == session.messages[0]["content"]
