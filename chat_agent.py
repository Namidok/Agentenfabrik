"""Usage: python chat_agent.py specs/<agent>.yaml
Chat with an agent. Commands: /notes shows its saved notes, /quit leaves.
Type one message per line (pasting several lines sends several messages)."""
import sys

from pydantic import ValidationError

from factory.llm import make_provider
from factory.runtime import AgentSession
from factory.schema import load_spec


def show(e: dict) -> None:
    if e["event"] == "model":
        for c in e["calls"]:
            print(f"  -> {c['name']}({c['arguments']})")
    elif e["event"] == "tool":
        out = e["output"].replace("\n", " | ")
        print(f"  <- {out[:150]}")
    elif e["event"] == "nudge":
        print(f"  ({e['message']})")
    elif e["event"] == "trim":
        print("  (older messages were forgotten to fit the model's memory)")
    elif e["event"] in ("error", "warning"):
        print(f"  !! {e['message']}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    try:
        spec = load_spec(sys.argv[1])
    except (ValidationError, OSError) as e:
        print("Could not load the spec:\n", e)
        return 1
    try:
        session = AgentSession(spec, make_provider(spec.model), on_event=show)
    except NotImplementedError as e:
        print("ERROR:", e)
        return 1

    print(f"Chatting with '{spec.name}' on {spec.model.name}. Type /quit to leave, /notes to see its notes.\n")
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text == "/quit":
            break
        if text == "/notes":
            print(session.read_notes() + "\n")
            continue
        try:
            result = session.send(text)
        except KeyboardInterrupt:
            print("\n(interrupted, that message was discarded)\n")
            continue
        label = spec.name if result.ok else f"{spec.name} [stopped: {result.stop_reason}]"
        print(f"\n{label}: {result.final_text or '(no reply)'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
