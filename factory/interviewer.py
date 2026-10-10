"""Interviewer: turns a plain-language request into a validated AgentSpec."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from factory.llm import LLMProvider
from factory.schema import AgentSpec
from factory.tools import IMPLEMENTED

MAX_BUILD_ATTEMPTS = 3


class SpecBuildError(RuntimeError):
    """The model could not produce a valid spec within the allowed attempts."""


def tool_catalog() -> str:
    return "\n".join(f"- {t.id}: {t.description}" for t in IMPLEMENTED.values())


INTERVIEW_PROMPT = """You help a user design a small AI agent that runs on their own computer. Interview them briefly.

Tools that exist right now:
{tools}
Only these tools exist. Anything the tools above cannot do is NOT possible. That includes moving or deleting files, and reading PDFs or images, unless a tool above does it. If the user asks for something impossible, say plainly that it is not possible yet and do NOT agree to it. Never promise an ability that is not in the tool list.

Find out, asking at most two short questions per turn:
1. What the agent should do, and what the user will give it.
2. Which folders it may read, which folders (if any) it may write files into, and which websites (if any) it may visit. It may only touch folders and websites you agree on.
3. How it is started: manually, on a schedule, or when a file appears.
4. Anything it must never do.

Set ready to true only when you know the goal, the folders and the trigger. Do not write the spec yet. Keep every reply under 60 words."""

BUILD_PROMPT = """You write the configuration for a small AI agent from an interview transcript.

Tools that exist right now:
{tools}

Rules:
- name: lowercase letters, digits and hyphens only, for example note-summarizer.
- goal: one clear sentence.
- system_prompt: 2 to 5 sentences telling the agent how to behave, including every restriction the user stated. Describe only what the listed tools can do. Never say the agent may modify, write, create or delete files, use the internet or run commands unless a listed tool does that.
- tools: only the tools the goal needs.
- fs_read: only the folders the user agreed to, written as they said them, for example ./notes.
- fs_write: only folders the user agreed the agent may write into. Leave it empty if the agent never writes files. Add fs.write to tools only if the agent must create files.
- network: only website domains the user agreed to, for example example.com. Leave it empty if the agent does not need the internet. Add http.fetch to tools only if the agent must read web pages.
- Add notes.read and notes.append to tools only if the agent must remember things between runs.
- Add code.run to tools only if the agent must compile and run C++ programs.
- Add code.check_name to tools only if the agent must check whether a C++ function, class or header exists.
- Use at most 6 tools.
- mode: conversational if the user talks back and forth with the agent, otherwise task.
- trigger_type: manual unless the user asked for a schedule or a file watcher. A schedule needs a cron expression. A file_watch needs watch_path."""

TURN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"reply": {"type": "string"}, "ready": {"type": "boolean"}},
    "required": ["reply", "ready"],
}


def draft_schema() -> dict[str, Any]:
    """Flat schema the model fills in. It grows as we add tools and permissions."""
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "goal": {"type": "string"},
            "system_prompt": {"type": "string"},
            "mode": {"type": "string", "enum": ["task", "conversational"]},
            "tools": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(IMPLEMENTED)},
            },
            "fs_read": {"type": "array", "items": {"type": "string"}},
            "fs_write": {"type": "array", "items": {"type": "string"}},
            "network": {"type": "array", "items": {"type": "string"}},
            "trigger_type": {
                "type": "string",
                "enum": ["manual", "schedule", "file_watch"],
            },
            "cron": {"type": "string"},
            "watch_path": {"type": "string"},
        },
        "required": [
            "name", "goal", "system_prompt", "mode", "tools", "fs_read", "fs_write", "network", "trigger_type",
        ],
    }


def interview_turn(
    provider: LLMProvider, transcript: list[dict[str, str]]
) -> tuple[str, bool]:
    """transcript: [{"role": "user"|"assistant", "content": "..."}]. Returns (reply, ready)."""
    messages = [
        {"role": "system", "content": INTERVIEW_PROMPT.format(tools=tool_catalog())},
        *transcript,
    ]
    resp = provider.chat(messages, schema=TURN_SCHEMA)
    try:
        data = json.loads(resp.content)
        return str(data["reply"]).strip(), bool(data.get("ready", False))
    except (json.JSONDecodeError, KeyError, TypeError):
        return resp.content.strip() or "Could you rephrase that?", False


def draft_to_spec(d: dict[str, Any]) -> AgentSpec:
    trigger: dict[str, Any] = {"type": d.get("trigger_type", "manual")}
    if trigger["type"] == "schedule":
        trigger["cron"] = d.get("cron") or None
    if trigger["type"] == "file_watch":
        trigger["path"] = d.get("watch_path") or None
    return AgentSpec.model_validate({
        "name": d.get("name", ""),
        "goal": d.get("goal", ""),
        "system_prompt": d.get("system_prompt", ""),
        "mode": d.get("mode", "task"),
        "tools": d.get("tools", []),
        "permissions": {"fs_read": d.get("fs_read", []), "fs_write": d.get("fs_write", []), "network": d.get("network", []), "shell": any(t.startswith("code.") for t in d.get("tools", []))},
        "memory": {"notes": any(t.startswith("notes.") for t in d.get("tools", []))},
        "trigger": trigger,
    })


def _format_errors(err: ValidationError) -> str:
    parts = []
    for e in err.errors():
        where = ".".join(str(x) for x in e["loc"]) or "spec"
        parts.append(f"{where}: {e['msg']}")
    return "; ".join(parts)


def build_spec(provider: LLMProvider, transcript: list[dict[str, str]]) -> AgentSpec:
    convo = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in transcript)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": BUILD_PROMPT.format(tools=tool_catalog())},
        {"role": "user", "content": f"Interview transcript:\n{convo}\n\nWrite the agent spec now."},
    ]
    problem = ""
    for _ in range(MAX_BUILD_ATTEMPTS):
        resp = provider.chat(messages, schema=draft_schema())
        try:
            draft = json.loads(resp.content)
            if not isinstance(draft, dict):
                raise ValueError("The reply was not a JSON object.")
            return draft_to_spec(draft)
        except json.JSONDecodeError:
            problem = "The reply was not valid JSON."
        except ValidationError as e:
            problem = _format_errors(e)
        except ValueError as e:
            problem = str(e)
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({
            "role": "user",
            "content": f"That spec was rejected: {problem}. Fix these problems and answer again.",
        })
    raise SpecBuildError(
        f"Could not build a valid spec after {MAX_BUILD_ATTEMPTS} attempts. Last problem: {problem}"
    )


def permission_warnings(spec: AgentSpec, base_dir: str | Path | None = None) -> list[str]:
    """Plain-language warnings shown to the user before a spec is saved."""
    base = Path(base_dir or Path.cwd()).resolve()
    home = Path.home().resolve()
    warnings: list[str] = []
    for raw in spec.permissions.fs_read + spec.permissions.fs_write:
        p = (base / Path(raw).expanduser()).resolve()
        if p == Path(p.anchor):
            warnings.append(f"'{raw}' gives access to the whole disk.")
        elif home.is_relative_to(p):
            warnings.append(f"'{raw}' covers your entire home folder (or more).")
    if spec.permissions.fs_write:
        warnings.append("This agent can write files.")
        if spec.permissions.allow_overwrite:
            warnings.append("It is allowed to replace existing files.")
    if spec.permissions.network:
        warnings.append(f"This agent can access the internet, limited to: {', '.join(spec.permissions.network)}.")
    if spec.permissions.shell:
        warnings.append("This agent can compile and run code on your computer. It is not isolated, so that code could read your files or use the network.")
    return warnings


def save_spec(spec: AgentSpec, specs_dir: str | Path) -> Path:
    specs_dir = Path(specs_dir)
    specs_dir.mkdir(parents=True, exist_ok=True)
    path = specs_dir / f"{spec.name}.yaml"
    text = yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")
    return path


CAPABILITY_RULES = [
    (r"\b(modify|modifies|edit|write|rename|move|delete|overwrite|save)\b",
     {"fs.write", "fs.move"}, "write, change or delete files"),
    (r"\bpdfs?\b", {"pdf.read"}, "read PDF files"),
    (r"\b(web|internet|online|website|websites|scrape|scraping|browse)\b",
     {"http.fetch"}, "use the internet"),
    (r"\b(execute|compile|run (code|commands?|scripts?))\b",
     {"code.run"}, "run code or commands"),
]
_NEGATION = re.compile(r"\b(never|not|no|without|don'?t|dont|can'?t|cannot)\b", re.IGNORECASE)


def capability_notes(transcript: list[dict[str, str]], spec: AgentSpec) -> list[str]:
    """Heads-ups for things the user asked for that the spec has no tool for."""
    have = set(spec.tools)
    notes: list[str] = []
    for pattern, tool_ids, what in CAPABILITY_RULES:
        if have & tool_ids:
            continue
        for msg in transcript:
            if msg["role"] != "user":
                continue
            text = msg["content"]
            hit = next(
                (m for m in re.finditer(pattern, text, re.IGNORECASE)
                 if not _NEGATION.search(text[max(0, m.start() - 40):m.start()])),
                None,
            )
            if hit:
                notes.append(
                    f"You mentioned wanting to {what}, but this agent has no tool for that, so it will not."
                )
                break
    return notes
