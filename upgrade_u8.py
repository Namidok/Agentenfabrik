"""Add the flashcard tools (srs.add, srs.due, srs.review) and notes.read if it is missing.
Run once from the project folder, after creating factory/srs.py: python upgrade_u8.py

If anything goes wrong, factory/tools.py is put back exactly as it was."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / "factory" / "tools.py"
MARK = "# Flashcard tools (spaced repetition)"

BLOCK = '''

# Flashcard tools (spaced repetition); their logic lives in factory/srs.py.
from factory import srs as _srs  # noqa: E402

for _tool_id, (_description, _parameters, _func) in _srs.TOOLS.items():
    IMPLEMENTED[_tool_id] = Tool(_tool_id, _description, _parameters, _func)

if "notes.read" not in IMPLEMENTED:
    def _notes_read(ctx, args):
        path = ctx.base_dir / "data" / ctx.spec.name / "notes.md"
        if not path.is_file():
            return "(no notes saved yet)"
        return path.read_text(encoding="utf-8")[-6000:] or "(no notes saved yet)"

    IMPLEMENTED["notes.read"] = Tool("notes.read", "Read the notes saved in earlier chats.",
                                     {"type": "object", "properties": {}}, _notes_read)
'''

if not (ROOT / "factory" / "srs.py").exists():
    raise SystemExit("factory/srs.py is missing. Create it first (paste 1 of 4), then run this again.")
original = TOOLS.read_text(encoding="utf-8")
if MARK in original:
    raise SystemExit("Already applied. Nothing changed.")
if "IMPLEMENTED" not in original or "class Tool" not in original:
    raise SystemExit("factory/tools.py does not look the way I expected. Nothing changed.")

TOOLS.write_text(original.rstrip("\n") + "\n" + BLOCK, encoding="utf-8")
check = "from factory.tools import IMPLEMENTED; assert {'srs.add','srs.due','srs.review','notes.read'} <= set(IMPLEMENTED)"
done = subprocess.run([sys.executable, "-c", check], cwd=ROOT, capture_output=True, text=True)
if done.returncode != 0:
    TOOLS.write_text(original, encoding="utf-8")
    print("That did not work, so factory/tools.py was put back as it was. Please send me this:")
    print(done.stderr.strip()[-1500:])
    raise SystemExit(1)
print("Done: srs.add, srs.due, srs.review and notes.read are ready.")
