"""Tools agents can call. Every tool goes through the permission checks here."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from factory.schema import AgentSpec
from factory import sandbox
from factory.web import WebError, fetch_page

MAX_READ_CHARS = 8000
MAX_WRITE_CHARS = 100_000
NOTES_MAX_CHARS = 50_000


class ToolError(Exception):
    """Expected failure. The message is shown to the model so it can recover."""


@dataclass
class ToolContext:
    spec: AgentSpec
    base_dir: Path  # relative paths in the spec and in tool calls resolve against this
    http_client: Any = None  # tests inject a fake client here
    resolver: Any = None  # tests inject a fake DNS resolver here

    def _resolve(self, raw: str) -> Path:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = self.base_dir / p
        return p.resolve()  # resolves "..", and follows symlinks

    def check_path(self, raw: str, kind: str) -> Path:
        """Return the resolved path if it is inside an allowed folder, else raise."""
        if not raw:
            raise ToolError("Missing required argument: path")
        target = self._resolve(str(raw))
        for root_raw in getattr(self.spec.permissions, kind):
            root = self._resolve(root_raw)
            if target == root or target.is_relative_to(root):
                return target
        raise ToolError(f"Permission denied: '{raw}' is outside the allowed folders.")

    @property
    def notes_file(self) -> Path:
        """The agent's own notes. Fixed location, never chosen by the model."""
        return self.base_dir / "data" / self.spec.name / "notes.md"


def fs_list(ctx: ToolContext, args: dict[str, Any]) -> str:
    path = ctx.check_path(args.get("path", ""), "fs_read")
    if not path.is_dir():
        raise ToolError(f"Not a folder: {args.get('path')}")
    lines = []
    for child in sorted(path.iterdir()):
        if child.name.startswith("."):
            continue
        kind = "folder" if child.is_dir() else f"file, {child.stat().st_size} bytes"
        lines.append(f"{child.name} ({kind})")
    return "\n".join(lines) or "(empty folder)"


def fs_read(ctx: ToolContext, args: dict[str, Any]) -> str:
    path = ctx.check_path(args.get("path", ""), "fs_read")
    if not path.is_file():
        raise ToolError(f"Not a file: {args.get('path')}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ToolError("File is not UTF-8 text.")
    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS] + f"\n...[truncated, file has {len(text)} characters]"
    return text


def fs_write(ctx: ToolContext, args: dict[str, Any]) -> str:
    path = ctx.check_path(args.get("path", ""), "fs_write")
    content = args.get("content")
    if not isinstance(content, str):
        raise ToolError("Argument 'content' is required and must be text.")
    if len(content) > MAX_WRITE_CHARS:
        raise ToolError(
            f"Content is too large ({len(content)} characters, limit {MAX_WRITE_CHARS})."
        )
    if path.is_dir():
        raise ToolError(f"That path is a folder, not a file: {args.get('path')}")
    if path.exists() and not ctx.spec.permissions.allow_overwrite:
        n = 2
        while path.with_name(f"{path.stem}-{n}{path.suffix}").exists():
            n += 1
        suggestion = Path(str(args.get("path"))).with_name(f"{path.stem}-{n}{path.suffix}")
        raise ToolError(
            f"File already exists: {args.get('path')}. Existing files cannot be replaced. "
            f"Write to a new name instead, for example {suggestion}."
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as e:
        raise ToolError(f"Could not write the file: {e.strerror or e}")
    return f"Wrote {len(content)} characters to {args.get('path')}"


def notes_read(ctx: ToolContext, args: dict[str, Any]) -> str:
    f = ctx.notes_file
    if not f.is_file():
        return "(no notes yet)"
    text = f.read_text(encoding="utf-8")
    if not text.strip():
        return "(no notes yet)"
    if len(text) > MAX_READ_CHARS:
        text = "...[earlier notes omitted]\n" + text[-MAX_READ_CHARS:]
    return text


def notes_append(ctx: ToolContext, args: dict[str, Any]) -> str:
    text = args.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ToolError("Argument 'text' is required and must be non-empty text.")
    f = ctx.notes_file
    existing = f.read_text(encoding="utf-8") if f.is_file() else ""
    entry = text.strip() + "\n"
    if len(existing) + len(entry) > NOTES_MAX_CHARS:
        raise ToolError(
            f"Notes are full ({NOTES_MAX_CHARS} characters). "
            "Tell the user the notes need cleaning up."
        )
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(entry)
    return "Note saved."


def http_fetch(ctx: ToolContext, args: dict[str, Any]) -> str:
    url = args.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ToolError("Missing required argument: url")
    try:
        offset = max(0, int(args.get("offset") or 0))
    except (TypeError, ValueError):
        raise ToolError("Argument 'offset' must be a whole number.")
    try:
        return fetch_page(
            url.strip(),
            ctx.spec.permissions.network,
            offset=offset,
            client=ctx.http_client,
            resolver=ctx.resolver,
        )
    except WebError as e:
        raise ToolError(str(e))


def code_run(ctx: ToolContext, args: dict[str, Any]) -> str:
    code = args.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ToolError("Argument 'code' is required and must be C++ source text.")
    stdin = args.get("stdin") or ""
    if not isinstance(stdin, str):
        raise ToolError("Argument 'stdin' must be text.")
    try:
        return sandbox.run_cpp(code, stdin)
    except sandbox.SandboxError as e:
        raise ToolError(str(e))


def code_check_name(ctx: ToolContext, args: dict[str, Any]) -> str:
    name = args.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ToolError("Argument 'name' is required, for example std::vector.")
    header = args.get("header") or ""
    if not isinstance(header, str):
        raise ToolError("Argument 'header' must be text.")
    try:
        return sandbox.check_cpp_name(name, header)
    except sandbox.SandboxError as e:
        raise ToolError(str(e))


@dataclass
class Tool:
    id: str  # as written in specs, e.g. "fs.list"
    description: str
    parameters: dict[str, Any]
    func: Callable[[ToolContext, dict[str, Any]], str]

    @property
    def model_name(self) -> str:
        return self.id.replace(".", "_")  # function names shown to the model

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.model_name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


_PATH_PARAM = {
    "type": "object",
    "properties": {"path": {"type": "string", "description": "Path of the folder or file"}},
    "required": ["path"],
}

_WRITE_PARAM = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path of the file to create"},
        "content": {"type": "string", "description": "Full text to put in the file"},
    },
    "required": ["path", "content"],
}

_NOTES_APPEND_PARAM = {
    "type": "object",
    "properties": {"text": {"type": "string", "description": "A short note to remember"}},
    "required": ["text"],
}

_FETCH_PARAM = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "Full web address starting with https://"},
        "offset": {"type": "integer", "description": "Character position to continue from (default 0)"},
    },
    "required": ["url"],
}

_CODE_PARAM = {
    "type": "object",
    "properties": {
        "code": {"type": "string", "description": "A complete C++ source file, including #include lines and main()"},
        "stdin": {"type": "string", "description": "Optional text given to the program as input"},
    },
    "required": ["code"],
}

_CHECK_PARAM = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Qualified C++ name to check, for example std::vector or ::getopt"},
        "header": {"type": "string", "description": "Optional: one header to test on its own, for example unistd.h. Leave empty to test the standard library headers."},
    },
    "required": ["name"],
}

_NO_PARAMS = {"type": "object", "properties": {}}

IMPLEMENTED: dict[str, Tool] = {
    "code.check_name": Tool(
        "code.check_name",
        "Check whether a C++ function, class or other name (for example std::getopt) is declared, by compiling a tiny test. Use this for any question like 'does C++ have X'. Leave header empty to test the standard library. Set header only to learn whether one specific header declares the name.",
        _CHECK_PARAM,
        code_check_name,
    ),
    "code.run": Tool(
        "code.run",
        "Compile and run a complete C++ program and get its real output or compiler errors. Use it to test code before you claim it works.",
        _CODE_PARAM,
        code_run,
    ),
    "http.fetch": Tool(
        "http.fetch",
        "Fetch a web page or text file from an allowed website. Returns plain text with links. Long pages come in parts: use offset to continue.",
        _FETCH_PARAM,
        http_fetch,
    ),
    "fs.list": Tool("fs.list", "List the files and folders inside a folder.", _PATH_PARAM, fs_list),
    "fs.read": Tool("fs.read", "Read the text content of a file.", _PATH_PARAM, fs_read),
    "fs.write": Tool(
        "fs.write",
        "Create a text file. If the name is already taken you get an error and must pick a new name.",
        _WRITE_PARAM,
        fs_write,
    ),
    "notes.read": Tool(
        "notes.read", "Read your saved notes from earlier runs.", _NO_PARAMS, notes_read
    ),
    "notes.append": Tool(
        "notes.append",
        "Save a short note to remember in future runs.",
        _NOTES_APPEND_PARAM,
        notes_append,
    ),
}


def build_tools(spec: AgentSpec) -> dict[str, Tool]:
    """Return the spec's tools, keyed by the name the model sees."""
    missing = [t for t in spec.tools if t not in IMPLEMENTED]
    if missing:
        raise NotImplementedError(f"Tools not implemented yet: {', '.join(missing)}")
    return {IMPLEMENTED[t].model_name: IMPLEMENTED[t] for t in spec.tools}


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
