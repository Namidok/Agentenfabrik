"""factory/study.py: which card is being answered, the start note, and the German article check."""
import pytest

from factory import study


@pytest.mark.parametrize("text, want", [
    ("Ich habe ein Hund.", '"einen Hund"'), ("Ich sehe der Katze.", '"die Katze"'), ("Die Hund ist klein.", '"der Hund"'),
    ("Ich trinke ein Kaffee", '"einen Kaffee"'), ("Ich möchte eine Wasser", '"ein Wasser"'), ("Ich habe keine Hund", '"keinen Hund"'),
    ("ich habe den haus", '"das Haus"'),
])
def test_common_slips_are_found(text, want):
    slips = study.german_slips(text)
    assert len(slips) == 1 and want in slips[0]


@pytest.mark.parametrize("text", [
    "Ich habe einen Hund.", "Der Hund hat einen Ball.", "Ein Hund hat einen Ball.", "Das ist ein Hund.",
    "Ich wohne mit dem Hund.", "Hallo", "I have a dog", "Ein Kaffee, bitte.", "",
])
def test_correct_or_unknown_sentences_are_left_alone(text):
    assert study.german_slips(text) == []


def test_acknowledgements_are_not_answers():
    assert all(study.is_ack(t) for t in ["ok", "OK!", "yes", "ja", "weiter", "  next "])
    assert not any(study.is_ack(t) for t in ["Hallo", "ok, Hallo", "Tschüss"])


def test_the_pending_card_is_the_one_the_reply_asks_about():
    calls = [("srs_add", {"front": "hello"}, "Card added as id 1 (due today)."),
             ("srs_add", {"front": "bye"}, "Card added as id 2 (due today).")]
    cards, graded = study.cards_in_turn(calls)
    assert study.pending_card(cards, graded, 'Your turn: "hello" in German?', None)["id"] == 1
    assert study.pending_card(cards, graded, "Your turn!", None)["id"] == 2  # newest added
    due = [("srs_due", {}, "1 due today, showing 1.\nid 7 [A0]\n  FRONT: the cat\n  BACK (keep hidden until the user has tried): die Katze")]
    cards, graded = study.cards_in_turn(due)
    assert study.pending_card(cards, graded, "Karte: the cat?", None) == {"id": 7, "front": "the cat", "source": "due"}
    previous = {"id": 3, "front": "x", "source": "add"}
    assert study.pending_card([], set(), "", previous) == previous
    assert study.pending_card([], {3}, "", previous) is None  # graded, nothing new


def test_the_start_note_names_the_last_topic_and_due_cards():
    note = study.start_note("old line\nlevel: A1 | topic: cafe", "1 due today, showing 1.\nid 4\n  FRONT: the tea\n  BACK (keep hidden...): der Tee")
    assert '"level: A1 | topic: cafe"' in note and "Cards are due" in note
    assert "do not know the student's level" in study.start_note("(no notes yet)", "The box is empty.")


def test_missing_corrections_are_found_in_the_reply():
    fixes = study.german_fixes("Ich habe ein Hund.")
    assert fixes[0][0] == "einen Hund"
    assert study.missing_corrections("Der Hund ist klein.", fixes) == fixes
    assert study.missing_corrections("Richtig wäre: Ich habe EINEN Hund.", fixes) == []
    assert "einen Hund" in study.correction_reminder(fixes)
