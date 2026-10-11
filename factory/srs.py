"""Flashcards that come back at the right time (spaced repetition), kept on this computer.

Each agent has its own box: data/<agent-name>/cards.db (one small SQLite file).
Three tools use it: srs.add, srs.due and srs.review. The schedule is a simplified SM-2:
a card you know comes back after 1 day, then 3, then each gap grows by the card's ease;
a card you miss comes back today.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, timedelta
from typing import Any

MAX_DUE = 10
GRADES = {"again": 0, "hard": 3, "good": 4, "easy": 5}
_TEXT_LIMIT = 400


def _today() -> date:  # one place to change in tests
    return date.today()


def _error(message: str) -> Exception:
    from factory.tools import ToolError  # imported late: tools.py imports this module

    return ToolError(message)


def _connect(ctx: Any) -> sqlite3.Connection:
    folder = ctx.base_dir / "data" / ctx.spec.name
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / "cards.db")
    db.row_factory = sqlite3.Row
    db.execute(
        "CREATE TABLE IF NOT EXISTS cards ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, front TEXT NOT NULL, back TEXT NOT NULL,"
        " tags TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, due TEXT NOT NULL,"
        " interval INTEGER NOT NULL DEFAULT 0, ease REAL NOT NULL DEFAULT 2.5,"
        " reps INTEGER NOT NULL DEFAULT 0, lapses INTEGER NOT NULL DEFAULT 0)"
    )
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS cards_front ON cards (lower(front))")
    return db


def _text(args: dict[str, Any], key: str, required: bool = True) -> str:
    value = args.get(key, "")
    if not isinstance(value, str):
        raise _error(f"Argument '{key}' must be text.")
    value = " ".join(value.split())
    if required and not value:
        raise _error(f"Argument '{key}' is required and must be non-empty text.")
    if len(value) > _TEXT_LIMIT:
        raise _error(f"Argument '{key}' is too long (at most {_TEXT_LIMIT} characters).")
    return value


def srs_add(ctx: Any, args: dict[str, Any]) -> str:
    front, back = _text(args, "front"), _text(args, "back")
    tags = _text(args, "tags", required=False)
    today = _today().isoformat()
    with closing(_connect(ctx)) as db:
        try:
            card_id = db.execute("INSERT INTO cards (front, back, tags, created, due) VALUES (?, ?, ?, ?, ?)",
                                 (front, back, tags, today, today)).lastrowid
            db.commit()
        except sqlite3.IntegrityError:
            old = db.execute("SELECT id FROM cards WHERE lower(front) = lower(?)", (front,)).fetchone()
            return f"Already in the box as id {old['id']}: {front}"
        total = db.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    # The id lets the agent grade this card with srs.review right after the student tries it.
    return (f"Card added as id {card_id} (due today). The box now holds {total} card{'s' if total != 1 else ''}. "
            f"When the user answers it, grade it with srs.review id {card_id}.")


def srs_due(ctx: Any, args: dict[str, Any]) -> str:
    raw = args.get("limit", 5)
    try:
        limit = max(1, min(MAX_DUE, int(raw)))
    except (TypeError, ValueError):
        raise _error("Argument 'limit' must be a whole number.") from None
    today = _today().isoformat()
    with closing(_connect(ctx)) as db:
        total = db.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        waiting = db.execute("SELECT COUNT(*) FROM cards WHERE due <= ?", (today,)).fetchone()[0]
        rows = db.execute("SELECT * FROM cards WHERE due <= ? ORDER BY due, id LIMIT ?", (today, limit)).fetchall()
        if not rows:
            nxt = db.execute("SELECT MIN(due) FROM cards").fetchone()[0]
            if not total:
                return "The box is empty. Add cards with srs.add first."
            return f"Nothing is due. {total} cards in the box, the next one is due {nxt}."
    lines = [f"{waiting} due today, showing {len(rows)}. Ask the front, wait for the user's answer, only then show the back."]
    for r in rows:
        tag = f" [{r['tags']}]" if r["tags"] else ""
        lines.append(f"id {r['id']}{tag}\n  FRONT: {r['front']}\n  BACK (keep hidden until the user has tried): {r['back']}")
    return "\n".join(lines)


def _grade(raw: Any) -> int:
    if isinstance(raw, str) and raw.strip().lower() in GRADES:
        return GRADES[raw.strip().lower()]
    try:
        number = int(raw)
    except (TypeError, ValueError):
        raise _error("Argument 'grade' must be again, hard, good or easy.") from None
    if number not in (0, 3, 4, 5):
        raise _error("Argument 'grade' must be again, hard, good or easy.")
    return number


def srs_review(ctx: Any, args: dict[str, Any]) -> str:
    try:
        card_id = int(args.get("id"))
    except (TypeError, ValueError):
        raise _error("Argument 'id' must be a card id from srs.add or srs.due.") from None
    grade = _grade(args.get("grade"))
    with closing(_connect(ctx)) as db:
        card = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if card is None:
            raise _error(f"No card with id {card_id}.")
        ease, reps, interval, lapses = card["ease"], card["reps"], card["interval"], card["lapses"]
        if grade == 0:
            reps, interval, lapses, ease = 0, 0, lapses + 1, max(1.3, ease - 0.2)
        else:
            reps += 1
            ease = max(1.3, ease + {3: -0.15, 4: 0.0, 5: 0.15}[grade])
            if reps == 1:
                interval = 3 if grade == 5 else 1
            elif reps == 2:
                interval = 6 if grade == 5 else 3
            else:
                interval = max(interval + 1, round(interval * ease * (0.8 if grade == 3 else 1.0)))
        due = _today() + timedelta(days=interval)
        db.execute("UPDATE cards SET due=?, interval=?, ease=?, reps=?, lapses=? WHERE id=?",
                   (due.isoformat(), interval, round(ease, 2), reps, lapses, card_id))
        db.commit()
    when = "today again" if interval == 0 else f"in {interval} day{'s' if interval != 1 else ''} ({due.isoformat()})"
    # Without this hint small models tend to ask the card they just graded once more.
    return f"Saved. This card comes back {when}. Do not ask it again now: move on to another card or a new one."


def list_cards(ctx: Any, limit: int = 500) -> dict[str, Any]:
    """Every card in an agent's box, soonest due first, for the page. Never creates the box."""
    path = ctx.base_dir / "data" / ctx.spec.name / "cards.db"
    if not path.is_file():
        return {"cards": [], "total": 0, "due_today": 0}
    today = _today().isoformat()
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT id, front, back, tags, due, interval, reps, lapses FROM cards ORDER BY due, id LIMIT ?",
                          (limit,)).fetchall()
        total = db.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        due = db.execute("SELECT COUNT(*) FROM cards WHERE due <= ?", (today,)).fetchone()[0]
    return {"cards": [dict(r) for r in rows], "total": total, "due_today": due, "today": today}


_ID = {"type": "integer", "description": "Card id from srs.add or srs.due"}
TOOLS = {
    "srs.add": (
        "Put one flashcard in the box: a front (the question) and a back (the answer). Returns the card id for srs.review.",
        {"type": "object", "properties": {
            "front": {"type": "string", "description": "What the user sees first, for example: the table"},
            "back": {"type": "string", "description": "The answer, kept hidden until the user tries, for example: der Tisch, die Tische"},
            "tags": {"type": "string", "description": "Optional, for example: verbs, A2"}},
         "required": ["front", "back"]},
        srs_add,
    ),
    "srs.due": (
        "List the flashcards that are due today so you can quiz the user.",
        {"type": "object", "properties": {"limit": {"type": "integer", "description": "How many cards, at most 10"}}},
        srs_due,
    ),
    "srs.review": (
        "Record how the user did on a card: again (wrong), hard, good or easy. This schedules its next visit.",
        {"type": "object", "properties": {
            "id": _ID, "grade": {"type": "string", "enum": ["again", "hard", "good", "easy"]}},
         "required": ["id", "grade"]},
        srs_review,
    ),
}
