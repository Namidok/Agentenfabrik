"""Usage: python run_agent.py specs/hello.yaml ["optional task text"]"""
import sys

from pydantic import ValidationError

from factory.llm import make_provider
from factory.runtime import run_agent
from factory.schema import load_spec


def show(e: dict) -> None:
    if e["event"] == "model":
        for c in e["calls"]:
            print(f"  -> {c['name']}({c['arguments']})")
    elif e["event"] == "tool":
        out = e["output"].replace("\n", " | ")
        print(f"  <- {out[:200]}")
    elif e["event"] in ("error", "warning"):
        print(f"  !! {e['message']}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    try:
        spec = load_spec(sys.argv[1])
    except ValidationError as e:
        print("Invalid spec:\n", e)
        return 1

    task = sys.argv[2] if len(sys.argv) > 2 else spec.goal
    print(f"Running '{spec.name}' on {spec.model.name}\nTask: {task}\n")
    result = run_agent(spec, task, make_provider(spec.model), on_event=show)

    print(f"\n--- {result.stop_reason.upper()} | {result.steps} steps | {result.tokens} tokens ---")
    print(result.final_text or "(no final answer)")
    return 0 if result.ok else 2


if __name__ == "__main__":
    sys.exit(main())
