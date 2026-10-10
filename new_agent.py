"""Usage: python new_agent.py
Describe the agent you want, answer a few questions, review the spec, save it."""
import sys
from pathlib import Path

import yaml

from factory.interviewer import (
    SpecBuildError,
    build_spec,
    capability_notes,
    interview_turn,
    permission_warnings,
    save_spec,
)
from factory.llm import OllamaProvider, ProviderError

SPECS_DIR = Path("specs")
MAX_TURNS = 10


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)


def main() -> int:
    provider = OllamaProvider()
    print("Describe the agent you want. I'll ask a few questions.")
    print("Type /done to build the spec now, /quit to exit.\n")

    transcript: list[dict[str, str]] = []
    user_turns = 0
    try:
        while user_turns < MAX_TURNS:
            text = ask("You: ")
            if text == "/quit":
                return 0
            if text == "/done":
                if user_turns == 0:
                    print("Tell me what you want first.")
                    continue
                break
            if not text:
                continue
            transcript.append({"role": "user", "content": text})
            user_turns += 1

            reply, ready = interview_turn(provider, transcript)
            transcript.append({"role": "assistant", "content": reply})
            print(f"\nFactory: {reply}\n")

            if ready:
                extra = ask("(I have enough. Press Enter to build the spec, or add more details) You: ")
                if not extra:
                    break
                transcript.append({"role": "user", "content": extra})

        print("\nBuilding the spec...")
        spec = build_spec(provider, transcript)
    except ProviderError as e:
        print("ERROR:", e)
        return 1
    except SpecBuildError as e:
        print("ERROR:", e)
        return 1

    print("\n" + yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False, allow_unicode=True))
    for w in permission_warnings(spec):
        print(f"WARNING: {w}")
    for n in capability_notes(transcript, spec):
        print(f"HEADS UP: {n}")

    target = SPECS_DIR / f"{spec.name}.yaml"
    note = " (this will overwrite an existing file)" if target.exists() else ""
    if ask(f"\nSave to {target}?{note} [y/N] ").lower() != "y":
        print("Not saved.")
        return 0
    print(f"Saved. Run it with:\n  python run_agent.py {save_spec(spec, SPECS_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
