"""Deterministic help for flashcard (study) agents, so a small local model does not have to remember it all:

- which card the student is answering (the card the agent asked about last turn),
- the start-of-chat context (notes and due cards, fetched by the runtime rather than by the model),
- a tiny rule-based check for common A1 German article and case slips.

The runtime only uses this for agents that have the srs tools."""
from __future__ import annotations

import re
from typing import Any

# ---------- the card being answered ----------

_ACK = re.compile(r"^\s*(ok(ay)?|k|yes|yep|yeah|sure|ja|jo|jep|weiter|next|go on|continue|go|nein|no|thanks|danke)\W*$", re.I)
_ADDED = re.compile(r"Card added as id (\d+)")
_ALREADY = re.compile(r"Already in the box as id (\d+): (.+)")
_DUE = re.compile(r"^id (\d+)(?: \[[^\]]*\])?\n\s+FRONT: (.+)$", re.M)


def is_ack(text: str) -> bool:
    """True for "ok", "yes", "weiter" and the like: the student is not answering anything."""
    return bool(_ACK.match(text or ""))


def cards_in_turn(calls: list[tuple[str, dict[str, Any], str]]) -> tuple[list[dict[str, Any]], set[int]]:
    """Cards the agent added or listed this turn, in order, and the ids it graded.
    calls: (tool name, arguments, output) for every tool call of the turn."""
    cards: list[dict[str, Any]] = []
    graded: set[int] = set()
    for name, args, output in calls:
        if name == "srs_add":
            m = _ADDED.search(output) or _ALREADY.search(output)
            if m:
                cards.append({"id": int(m.group(1)), "front": str(args.get("front", "")).strip(), "source": "add"})
        elif name == "srs_due":
            cards.extend({"id": int(i), "front": f.strip(), "source": "due"} for i, f in _DUE.findall(output))
        elif name == "srs_review":
            try:
                graded.add(int(args.get("id")))
            except (TypeError, ValueError):
                pass
    return cards, graded


def pending_card(cards: list[dict[str, Any]], graded: set[int], reply: str, previous: dict[str, Any] | None) -> dict[str, Any] | None:
    """The card the student will answer next: the one the reply asks about, else the newest card added
    this turn, else the first due card, else the card that was already waiting (unless it was graded)."""
    open_cards = [c for c in cards if c["id"] not in graded]
    low = (reply or "").lower()
    for card in reversed(open_cards):
        if len(card["front"]) >= 2 and card["front"].lower() in low:
            return card
    added = [c for c in open_cards if c["source"] == "add"]
    if added:
        return added[-1]
    due = [c for c in open_cards if c["source"] == "due"]
    if due:
        return due[0]
    if previous and previous["id"] not in graded:
        return previous
    return None


MAX_NEW_CARDS = 3  # per reply: a micro-lesson is 1 to 3 new words
TOO_MANY_CARDS = (f"ERROR: {MAX_NEW_CARDS} new cards per reply is the limit, so this card was not added. "
                  "Teach the cards you already added first, and add more in a later reply.")


def review_reminder(card: dict[str, Any]) -> str:
    front = f' ("{card["front"]}")' if card.get("front") else ""
    return (
        "[Automatic system reminder, not a message from the student.] Do not mention this reminder. "
        f"The student's last message answers card {card['id']}{front}. Grade it now: call srs_review with id {card['id']} "
        "and grade good if right, hard for a small slip, again if wrong. Then write your complete reply to the student."
    )


# ---------- start of a chat ----------

NOTES_TAIL = 8  # lines of notes shown at the start of a chat


def notes_tail(notes: str, lines: int = NOTES_TAIL) -> str:
    """The latest lines of the notes; older ones are only counted. The agent can call notes_read for all."""
    rows = [r for r in (notes or "").splitlines() if r.strip() and not r.startswith("...[")]
    if len(rows) <= lines:
        return notes
    return f"({len(rows) - lines} older lines not shown; call notes_read to see them all)\n" + "\n".join(rows[-lines:])


def start_note(notes_output: str | None, due_output: str | None) -> str:
    """A short note for the first model call, built from the notes and due cards the runtime fetched."""
    parts = ["[Automatic note, not from the student.] This is the start of the chat. Your notes and due cards are above, "
             "so do not call notes_read or srs_due again now."]
    lines = [ln.strip() for ln in (notes_output or "").splitlines() if ln.strip() and not ln.startswith("...[")]
    if lines and "no notes" not in lines[-1].lower():
        parts.append(f'The last line of your notes is: "{lines[-1][:200]}". Greet the student, name the level and this last topic, then go on from there.')
    else:
        parts.append("There are no notes yet, so you do not know the student's level.")
    if due_output and _DUE.search(due_output):
        parts.append("Cards are due: quiz them first, one front at a time.")
    return " ".join(parts)


# ---------- a tiny German article and case check ----------

MASCULINE = set("""hund tisch stuhl apfel kaffee tee saft kuchen freund bruder vater sohn mann name tag abend morgen
bahnhof zug bus garten computer schlüssel löffel teller wein käse kühlschrank lehrer arzt brief hut rock schuh ball
platz park supermarkt film fisch kuli bleistift baum hamburger salat""".split())
FEMININE = set("""katze frau mutter schwester tochter tür lampe stadt schule zeit straße wohnung küche tasse flasche
banane milch uhr arbeit familie freundin lehrerin zeitung tasche jacke hose blume woche nacht stunde pizza suppe gabel
maus kirche bank brille""".split())
NEUTER = set("""haus buch auto wasser kind bier brot zimmer mädchen fenster bett handy fahrrad glas ei messer hemd
kleid geld jahr wetter essen restaurant hotel café kino büro bad sofa telefon mittagessen frühstück pferd schwein
heft bild""".split())
GENDER = {**{w: "m" for w in MASCULINE}, **{w: "f" for w in FEMININE}, **{w: "n" for w in NEUTER}}
GENDER_WORD = {"m": "masculine", "f": "feminine", "n": "neuter"}
DEFINITE = {"m": "der", "f": "die", "n": "das"}

# verbs whose object is in the accusative
ACC_VERBS = set("""habe hast hat haben habt sehe siehst sieht sehen seht möchte möchtest möchten brauche brauchst braucht
brauchen kaufe kaufst kauft kaufen trinke trinkst trinkt trinken esse isst essen esst suche suchst sucht suchen mag magst
mögen nehme nimmst nimmt nehmen liebe liebst liebt lieben finde findest findet finden kenne kennst kennt kennen gibt
bestelle bestellst bestellt lese liest lesen""".split())
PREPOSITIONS = set("mit bei von zu aus nach seit für durch gegen ohne um in an auf unter über vor hinter neben zwischen im am zum zur vom beim ins".split())
ARTICLES = {"der": "def", "die": "def", "das": "def", "den": "def", "ein": "indef", "eine": "indef", "einen": "indef",
            "kein": "neg", "keine": "neg", "keinen": "neg"}
_WORD = re.compile(r"[A-Za-zÄÖÜäöüß]+")


def _expected(kind: str, gender: str, accusative: bool) -> str:
    if kind == "def":
        return "den" if (gender == "m" and accusative) else DEFINITE[gender]
    base = "ein" if kind == "indef" else "kein"
    if gender == "f":
        return base + "e"
    return base + "en" if (gender == "m" and accusative) else base


def german_slips(text: str) -> list[str]:
    """Plain-English notes about article or case slips with common A1 nouns. Empty when nothing is found."""
    return [note for _, note in german_fixes(text)]


def german_fixes(text: str) -> list[tuple[str, str]]:
    """(the right form, a note explaining it) for every slip found, for example ("einen Hund", "...")."""
    found: list[tuple[str, str]] = []
    for sentence in re.split(r"[.!?\n]+", text or ""):
        words = _WORD.findall(sentence)
        lower = [w.lower() for w in words]
        verb_at = next((k for k, w in enumerate(lower) if w in ACC_VERBS), None)
        for i in range(1, len(words)):
            noun, article = lower[i], lower[i - 1]
            if noun not in GENDER or article not in ARTICLES:
                continue
            if i >= 2 and lower[i - 2] in PREPOSITIONS:
                continue  # dative and two-way prepositions: too many cases for a tiny checker
            gender = GENDER[noun]
            # the object of an accusative verb that comes before it; a sentence's first word is its subject
            accusative = verb_at is not None and verb_at < i - 1 and i - 1 > 0
            want = _expected(ARTICLES[article], gender, accusative)
            if article == want:
                continue
            noun_word = words[i][0].upper() + words[i][1:]
            reason = f"{noun_word} is {GENDER_WORD[gender]} ({DEFINITE[gender]} {noun_word})"
            if accusative and gender == "m":
                reason += f', and after "{words[verb_at]}" it is accusative'
            note = f'"{words[i - 1]} {words[i]}" should be "{want} {noun_word}": {reason}.'
            if all(note != n for _, n in found):
                found.append((f"{want} {noun_word}", note))
    return found


def missing_corrections(reply: str, fixes: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The fixes whose right form does not appear in the reply."""
    low = (reply or "").lower()
    return [(right, note) for right, note in fixes if right.lower() not in low]


def correction_reminder(fixes: list[tuple[str, str]]) -> str:
    forms = ", ".join(f'"{right}"' for right, _ in fixes)
    return (
        "[Automatic system reminder, not a message from the student.] Do not mention this reminder. Your reply does not "
        f"correct the student's mistake. Write your reply again and start it with the correct form ({forms}) and the one "
        f"rule behind it: {' '.join(note for _, note in fixes)}"
    )


def grammar_hint(slips: list[str]) -> str:
    return (
        "[Automatic grammar check, not from the student.] Do not mention this check. The student's message has these "
        f"mistakes: {' '.join(slips)} Correct each one in your reply: show the right form and the one rule behind it."
    )
