"""Shared helpers for the job application scripts: folders, versioned files, a small JSON-schema check.

Every script takes its arguments as one JSON object (on stdin, or as the first command-line argument)
and prints one short JSON summary on stdout. That summary is all an agent ever sees, so it must never
contain job posting text."""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "inputs"
DATA = ROOT / "data" / "jobs"
POSTINGS = DATA / "postings"
ME = DATA / "me"  # the user's own files (profile, projects, preferences): no posting text, so Job Desk may read them
TEMPLATES = ROOT / "templates"
OUTPUT = ROOT / "output"
SCHEMAS = Path(__file__).resolve().parent / "schemas"

MAX_TEXT = 3000  # characters kept per README or job description


def args() -> dict[str, Any]:
    """The script's arguments: a JSON object on the command line or on stdin (empty means {})."""
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    if not raw and not sys.stdin.isatty():
        import select  # only read stdin when something was actually sent (an open, silent pipe must not hang)
        if select.select([sys.stdin], [], [], 0.5)[0]:
            raw = sys.stdin.read()
    raw = raw.strip()
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        fail("Arguments must be a JSON object.")
    return value


def done(summary: dict[str, Any]) -> str:
    """Print the one-line summary the agent will read, and return it."""
    text = json.dumps(summary, ensure_ascii=False)
    print(text)
    return text


def fail(message: str, **extra: Any) -> None:
    done({"ok": False, "error": message, **extra})
    raise SystemExit(1)


def today() -> str:
    return date.today().isoformat()


def slug(text: str, n: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:n].strip("-") or "item"


def next_version(folder: Path, stem: str, suffix: str = ".json") -> Path:
    """folder/stem_v1.json, _v2, ...: never overwrite an earlier version."""
    folder.mkdir(parents=True, exist_ok=True)
    n = 1
    while (folder / f"{stem}_v{n}{suffix}").exists():
        n += 1
    return folder / f"{stem}_v{n}{suffix}"


def latest(folder: Path, stem: str, suffix: str = ".json") -> Path | None:
    """The newest folder/stem_vN.json, or None."""
    found = []
    for p in folder.glob(f"{stem}_v*{suffix}"):
        m = re.fullmatch(rf"{re.escape(stem)}_v(\d+){re.escape(suffix)}", p.name)
        if m:
            found.append((int(m.group(1)), p))
    return max(found)[1] if found else None


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"{path} exists; versioned files are never overwritten")
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def clip(text: str, n: int = MAX_TEXT) -> str:
    text = text.strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def curly(text: str) -> str:
    """"word" -> “word”: agents copy facts into JSON strings, and curly quotes need no escaping there."""
    return re.sub(r'"([^"\n]*)"', "\u201c\\1\u201d", str(text)).replace('"', "\u201d")


def profile_markdown(profile: dict, projects: list[dict] | None = None) -> str:
    """The profile as short lines "ID: text", the form agents read and cite (much smaller than the JSON)."""
    h = profile["header"]
    lines = ["# Your facts (cite these IDs; nothing else may be claimed)", "",
             f"Name: {h['name']}. Master headline: {h['headline']}", "", "## Summary sentences"]
    lines += [f"- {f['id']}: {curly(f['text'])}" for f in profile["summary"]]
    lines += ["", "## Skill groups (skills_order uses these IDs)"]
    lines += [f"- {s['id']} {s['label']}: {s['items'] if isinstance(s['items'], str) else ', '.join(s['items'])}" for s in profile["skills"]]
    lines += ["", "## Jobs"]
    for e in profile["experience"]:
        lines.append(f"{e['id']} {e['title']}, {e['org']}, {e.get('location', '')}, {e['dates']}")
        lines += [f"- {b['id']}: {curly(b['text'])}" for b in e["bullets"]]
    lines += ["", "## Projects on the master CV"]
    for p in profile["projects"]:
        lines.append(f"{p['id']} {p['name']}: {p.get('tagline', '')} ({', '.join(p.get('stack', []))})")
        lines += [f"- {b['id']}: {curly(b['text'])}" for b in p["bullets"]]
    lines += ["", "## Education"]
    lines += [f"- {e['id']}: {e['degree']}, {e['school']}, {e['dates']}" + (f". {e['note']}" if e.get("note") else "") for e in profile["education"]]
    if projects:
        lines += ["", "## GitHub projects closest to this job (cite the PRJ- ID; use only what is written here)"]
        for p in projects:
            text = clip(" ".join(x for x in (p["summary"], p["what_was_built"]) if x) or "(no description)", 260)
            outcome = f" Results stated in its README: {' / '.join(p['outcomes'][:2])}" if p["outcomes"] else ""
            lines.append(f"- {p['id']} ({', '.join(p['stack'][:6])}): {curly(text)}{curly(outcome)}")
    return "\n".join(lines) + "\n"


def write_profile(profile: dict[str, Any]) -> Path:
    """Save a new profile version as JSON plus the same facts as Markdown (profile_vN.md) for agents to read."""
    path = write_json(next_version(ME, "profile"), profile)
    path.with_suffix(".md").write_text(profile_markdown(profile), encoding="utf-8")
    return path


# ---------- a small JSON-schema check (the subset the schemas here use) ----------

_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool}


def _is(value: Any, kind: str) -> bool:
    if kind == "null":
        return value is None
    if kind in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[kind])


def check_schema(value: Any, schema: dict[str, Any], where: str = "$") -> list[str]:
    """Problems with value against schema: anyOf, type, required, properties, additionalProperties,
    items, enum, pattern, minLength, minItems, maxItems. Empty when it is valid."""
    problems: list[str] = []
    if "anyOf" in schema:
        options = [check_schema(value, s, where) for s in schema["anyOf"]]
        if all(options):
            return min(options, key=len)
    kind = schema.get("type")
    if kind:
        allowed = kind if isinstance(kind, list) else [kind]
        if not any(_is(value, k) for k in allowed):
            return [f"{where}: expected {kind}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{where}: {value!r} is not one of {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            problems.append(f"{where}: too short")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            problems.append(f"{where}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            problems.append(f"{where}: needs at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            problems.append(f"{where}: at most {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                problems += check_schema(item, schema["items"], f"{where}[{i}]")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                problems.append(f"{where}: missing '{key}'")
        props = schema.get("properties", {})
        for key, item in value.items():
            if key in props:
                problems += check_schema(item, props[key], f"{where}.{key}")
            elif schema.get("additionalProperties") is False:
                problems.append(f"{where}: unexpected key '{key}'")
    return problems


def load_schema(name: str) -> dict[str, Any]:
    return read_json(SCHEMAS / f"{name}.schema.json")
