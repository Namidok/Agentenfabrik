"""Benchmark: a fixed 5-turn conversation with each kind of agent, against the real local Ollama.

    python scripts/bench.py                    # all three agents, prints the tables
    python scripts/bench.py --agents chat      # one agent
    python scripts/bench.py --json out.json    # also save the raw numbers

Agents: the German teacher (specs/german-teacher.yaml, tools + notes + flashcards), a task agent that
reads files, and a plain chat agent. Everything runs in a temporary folder, so your real notes and
cards are never touched. Per turn it records:

  first_token   seconds until the model produced its first token (model load + reading the prompt)
  visible       seconds until reply text could appear on screen (the whole turn without streaming)
  total         wall time of the turn
  calls         model calls in the turn (tool steps, reminders)
  prompt_tok    prompt tokens sent, summed over the calls (Ollama counts cached tokens too)
  read_s        time the model spent reading prompts; a cached prompt prefix makes this small
  out_tok       tokens written
  tok_s         writing speed, out_tok / time spent writing
  model_s       wall time inside model calls; overhead_s = total - model_s (tools, files, our own code)
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from factory.llm import LLMProvider, LLMResponse, make_provider  # noqa: E402
from factory.runtime import AgentSession, build_system_prompt  # noqa: E402
from factory.schema import AgentSpec, load_spec  # noqa: E402
from factory.settings import apply_options, load_settings  # noqa: E402

OLLAMA = "http://localhost:11434"

TURNS = {
    "german": ["Let's get started.", "I'm a total beginner.", "ok", "Ich habe ein Hund.", "yes"],
    "task": ["List the files in ./sandbox.", "Summarize ./sandbox/notes.txt in one sentence.", "What is on the todo list in ./sandbox/todo.txt?",
             "How many lines does ./sandbox/poem.txt have?", "Which file in ./sandbox is the longest?"],
    "chat": ["Hi! Give me one tip for better sleep.", "Why does that help?", "Give me a second tip.",
             "Sum up both tips in one line.", "Thanks!"],
}

SANDBOX = {
    "notes.txt": "Meeting on Tuesday moved to Thursday at 10. Bring the budget sheet and the new logo drafts.\n",
    "todo.txt": "- water the plants\n- call the bank about the card\n- buy coffee beans\n",
    "poem.txt": "The office hums at nine,\nthe kettle sings its line,\nthe cat dreams on the mat,\nand that is that.\n",
}


def bench_specs() -> dict[str, AgentSpec]:
    return {
        "german": load_spec(ROOT / "specs" / "german-teacher.yaml"),
        "task": AgentSpec.model_validate({
            "name": "bench-task", "goal": "Answer questions about the files in ./sandbox", "mode": "task",
            "system_prompt": "You answer questions about files. Read the file before answering. Keep answers short.",
            "tools": ["fs.list", "fs.read"], "permissions": {"fs_read": ["./sandbox"]},
        }),
        "chat": AgentSpec.model_validate({
            "name": "bench-chat", "goal": "Friendly everyday advice in a few sentences", "mode": "conversational",
            "system_prompt": "You give short, friendly, practical advice. Two or three sentences per reply.",
        }),
    }


class Timed(LLMProvider):
    """Wraps the real provider and remembers every call of the current turn."""

    def __init__(self, inner: LLMProvider) -> None:
        self.inner = inner
        self.streams = getattr(inner, "streams", False)  # stream exactly when the app would
        self.calls: list[dict[str, Any]] = []
        self.turn_start = 0.0

    def chat(self, messages, tools=None, schema=None, **kwargs) -> LLMResponse:
        start = time.monotonic()
        resp = self.inner.chat(messages, tools=tools, schema=schema, **kwargs)
        wall = time.monotonic() - start
        first = getattr(resp, "first_token_s", 0.0) or (resp.load_s + resp.prompt_eval_s)
        self.calls.append({
            "offset": start - self.turn_start, "wall": wall, "first_token": first, "streamed": kwargs.get("on_token") is not None,
            "load": resp.load_s, "prompt_eval": resp.prompt_eval_s, "eval": resp.eval_s,
            "prompt_tok": resp.prompt_tokens, "out_tok": resp.completion_tokens, "tool_calls": len(resp.tool_calls),
            "done_reason": resp.done_reason,
        })
        return resp


def turn_row(provider: Timed, total: float, stop: str) -> dict[str, Any]:
    calls = provider.calls
    model_s = sum(c["wall"] for c in calls)
    eval_s = sum(c["eval"] for c in calls)
    out_tok = sum(c["out_tok"] for c in calls)
    final = calls[-1] if calls else None
    visible = (final["offset"] + final["first_token"]) if final and final["streamed"] else total
    return {
        "first_token": round(calls[0]["offset"] + calls[0]["first_token"], 2) if calls else 0.0,
        "visible": round(visible, 2), "total": round(total, 2), "calls": len(calls),
        "prompt_tok": sum(c["prompt_tok"] for c in calls), "read_s": round(sum(c["prompt_eval"] for c in calls), 2), "out_tok": out_tok,
        "tok_s": round(out_tok / eval_s, 1) if eval_s else 0.0,
        "model_s": round(model_s, 2), "overhead_s": round(total - model_s, 3),
        "load_s": round(sum(c["load"] for c in calls), 2), "stop": stop,
    }


def count_tokens(model: str, num_ctx: int, messages: list[dict[str, Any]], tools: list | None) -> int:
    """Exact prompt size: a nonce at the very top defeats Ollama's prompt cache, num_predict 1 keeps it cheap."""
    msgs = [dict(m) for m in messages]
    msgs[0] = {**msgs[0], "content": f"[{uuid.uuid4().hex[:8]}]\n{msgs[0]['content']}"}
    payload = {"model": model, "messages": msgs, "stream": False, "think": False,
               "options": {"num_ctx": num_ctx, "num_predict": 1}}
    if tools:
        payload["tools"] = tools
    r = httpx.post(f"{OLLAMA}/api/chat", json=payload, timeout=300)
    r.raise_for_status()
    return int(r.json().get("prompt_eval_count") or 0)


def prompt_parts(session: AgentSession) -> dict[str, int]:
    """Tokens of each part of the last request: system prompt, notes in it, tool schemas, history."""
    spec, cfg = session.spec, session.spec.model
    no_notes = [{"role": "system", "content": build_system_prompt(spec, None)}]
    system = count_tokens(cfg.name, cfg.num_ctx, no_notes, None)
    with_notes = count_tokens(cfg.name, cfg.num_ctx, session.messages[:1], None)
    with_tools = count_tokens(cfg.name, cfg.num_ctx, session.messages[:1], session.schemas)
    full = count_tokens(cfg.name, cfg.num_ctx, session.messages, session.schemas)
    return {"system": system, "notes": max(0, with_notes - system), "tools": max(0, with_tools - with_notes),
            "history": max(0, full - with_tools), "total": full}


def run_agent(kind: str, spec: AgentSpec, model: str | None) -> dict[str, Any]:
    base = Path(tempfile.mkdtemp(prefix=f"bench-{kind}-"))
    (base / "sandbox").mkdir()
    for name, text in SANDBOX.items():
        (base / "sandbox" / name).write_text(text)
    if model:
        spec = spec.model_copy(update={"model": spec.model.model_copy(update={"name": model})})
    inner = make_provider(spec.model)
    apply_options(inner, spec.mode, load_settings(ROOT / "settings.yaml")[0])  # the same options the app sends
    provider = Timed(inner)
    listen = lambda entry: None  # noqa: E731  (a listener, as the web page is one, so replies stream)
    session = AgentSession(spec, provider, base_dir=base, on_event=listen)
    rows = []
    for text in TURNS[kind]:
        if spec.mode == "task":  # task agents start fresh for every message, as in the app
            session = AgentSession(spec, provider, base_dir=base, on_event=listen)
        provider.calls = []
        provider.turn_start = time.monotonic()
        result = session.send(text)
        rows.append({"turn": text, **turn_row(provider, time.monotonic() - provider.turn_start, result.stop_reason),
                     "reply": result.final_text[:120]})
    return {"agent": kind, "model": spec.model.name, "turns": rows, "parts": prompt_parts(session)}


COLS = ["first_token", "visible", "total", "calls", "prompt_tok", "read_s", "out_tok", "tok_s", "model_s", "overhead_s"]


def summary(run: dict[str, Any]) -> dict[str, Any]:
    rows = run["turns"]
    mean = lambda k: statistics.mean(r[k] for r in rows)  # noqa: E731
    return {k: round(mean(k), 3 if k == "overhead_s" else 2 if isinstance(rows[0][k], float) else 1) for k in COLS}


def print_tables(runs: list[dict[str, Any]], label: str) -> None:
    print(f"\n=== {label}: per turn ===")
    print(f"{'agent':7} {'turn':34} " + " ".join(f"{c:>10}" for c in COLS) + "  stop")
    for run in runs:
        for r in run["turns"]:
            print(f"{run['agent']:7} {r['turn'][:34]:34} " + " ".join(f"{r[c]:>10}" for c in COLS) + f"  {r['stop']}")
    print(f"\n=== {label}: average per turn ===")
    print(f"{'agent':7} {'model':18} " + " ".join(f"{c:>10}" for c in COLS))
    for run in runs:
        s = summary(run)
        print(f"{run['agent']:7} {run['model']:18} " + " ".join(f"{s[c]:>10}" for c in COLS))
    print(f"\n=== {label}: prompt size of the last request, in tokens ===")
    print(f"{'agent':7} {'system':>8} {'notes':>8} {'tools':>8} {'history':>8} {'total':>8}")
    for run in runs:
        p = run["parts"]
        print(f"{run['agent']:7} {p['system']:>8} {p['notes']:>8} {p['tools']:>8} {p['history']:>8} {p['total']:>8}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agents", default="german,task,chat", help="comma-separated: german, task, chat")
    ap.add_argument("--model", default=None, help="run every agent on this model instead of its own")
    ap.add_argument("--label", default="run")
    ap.add_argument("--json", default=None, help="save the raw numbers here")
    args = ap.parse_args()
    specs = bench_specs()
    runs = []
    for kind in args.agents.split(","):
        print(f"... {kind}", file=sys.stderr, flush=True)
        runs.append(run_agent(kind.strip(), specs[kind.strip()], args.model))
    print_tables(runs, args.label)
    if args.json:
        Path(args.json).write_text(json.dumps({"label": args.label, "runs": runs}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
