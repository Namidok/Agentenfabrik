"""Local web server: lists agents from specs/ and chats with them over a websocket.

It only listens on 127.0.0.1. Agents can read and write files, visit allowed websites and
run code, so the server also refuses any request whose Host or Origin is not this very page.
That blocks other websites you have open from talking to your agents."""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
import yaml
from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from factory.interviewer import SpecBuildError, build_spec, capability_notes, draft_to_spec, permission_warnings, save_spec
from factory.llm import ProviderError, make_provider
from factory.runtime import AgentSession
from factory.schema import MAX_TOOLS, TOOL_REQUIRES, AgentSpec, ModelConfig, load_spec
from factory.tools import IMPLEMENTED, ToolContext

ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = ROOT / "specs"
STATIC_DIR = ROOT / "static"
OLLAMA_HOST = "http://localhost:11434"
MAX_MESSAGE_CHARS = 8000
SLUG = re.compile(r"[a-z][a-z0-9-]{2,40}")

# A small computer runs one model call at a time; other agents wait their turn.
MODEL_LOCK = asyncio.Lock()

app = FastAPI(title="AgentFactory", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
app.mount("/static", StaticFiles(directory=str(STATIC_DIR), check_dir=False), name="static")


@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ---------- reading specs ----------


def _short_error(e: ValidationError) -> str:
    parts = []
    for err in e.errors()[:3]:
        where = ".".join(str(x) for x in err["loc"]) or "spec"
        parts.append(f"{where}: {err['msg']}")
    return "; ".join(parts)


def load_all() -> tuple[list[AgentSpec], list[dict[str, str]]]:
    """Every valid spec in specs/, plus a list of files that could not be loaded."""
    specs: list[AgentSpec] = []
    problems: list[dict[str, str]] = []
    seen: set[str] = set()
    if not SPECS_DIR.is_dir():
        return specs, problems
    for path in sorted(SPECS_DIR.glob("*.yaml")):
        try:
            spec = load_spec(path)
        except ValidationError as e:
            problems.append({"file": path.name, "error": _short_error(e)})
            continue
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
            problems.append({"file": path.name, "error": f"Could not read the file ({type(e).__name__})."})
            continue
        if spec.name in seen:
            problems.append({"file": path.name, "error": f"Another file already defines an agent called '{spec.name}'."})
            continue
        seen.add(spec.name)
        specs.append(spec)
    return specs, problems


def find_spec(name: str) -> AgentSpec:
    if SLUG.fullmatch(name):
        for spec in load_all()[0]:
            if spec.name == name:
                return spec
    raise HTTPException(status_code=404, detail=f"No agent called '{name}'.")


def ollama_models() -> list[str] | None:
    """Names of the installed models, or None when Ollama is not reachable."""
    try:
        r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=1.5)
        r.raise_for_status()
        return [str(m.get("name", "")) for m in r.json().get("models", [])]
    except (httpx.HTTPError, ValueError, AttributeError):
        return None


def _has_model(models: list[str] | None, wanted: str) -> bool | None:
    if models is None:
        return None
    if ":" not in wanted:
        wanted += ":latest"
    return wanted in models


def spec_files() -> dict[str, Path]:
    """Which file defines each agent (the first valid file wins, as in load_all)."""
    found: dict[str, Path] = {}
    if SPECS_DIR.is_dir():
        for path in sorted(SPECS_DIR.glob("*.yaml")):
            try:
                spec = load_spec(path)
            except (ValidationError, OSError, UnicodeDecodeError, yaml.YAMLError):
                continue
            found.setdefault(spec.name, path)
    return found


def summarize(spec: AgentSpec, models: list[str] | None, file: Path | None = None) -> dict[str, Any]:
    missing = [t for t in spec.tools if t not in IMPLEMENTED]
    return {
        "name": spec.name,
        "goal": spec.goal,
        "mode": spec.mode,
        "model": spec.model.name,
        "model_installed": _has_model(models, spec.model.name),
        "tools": spec.tools,
        "missing_tools": missing,
        "runnable": not missing,
        "permissions": spec.permissions.model_dump(),
        "limits": spec.limits.model_dump(),
        "memory": spec.memory.model_dump(),
        "warnings": permission_warnings(spec, ROOT),
        "has_notes": ToolContext(spec, ROOT).notes_file.is_file(),
        "file": file.name if file else "",
        "display_name": spec.appearance.display_name or "",
        "color": spec.appearance.color or "",
        "hair": spec.appearance.hair or "",
    }


# ---------- http routes ----------


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
def api_config() -> dict[str, Any]:
    models = ollama_models()
    return {"ollama_host": OLLAMA_HOST, "ollama_up": models is not None, "models": models or []}


@app.get("/api/agents")
def api_agents() -> dict[str, Any]:
    specs, problems = load_all()
    models = ollama_models()
    files = spec_files()
    return {"agents": [summarize(s, models, files.get(s.name)) for s in specs], "problems": problems}


@app.get("/api/agents/{name}/notes")
def api_notes(name: str) -> dict[str, str]:
    spec = find_spec(name)
    f = ToolContext(spec, ROOT).notes_file
    text = f.read_text(encoding="utf-8", errors="replace") if f.is_file() else ""
    return {"name": spec.name, "notes": text}


@app.get("/api/agents/{name}/file")
def api_agent_file(name: str) -> dict[str, str]:
    """The agent's own spec file, for the read-only staff file page."""
    spec = find_spec(name)
    path = spec_files().get(spec.name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"No agent called '{name}'.")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise HTTPException(status_code=500, detail=f"Could not read the file ({type(e).__name__}).") from e
    return {"name": spec.name, "file": path.name, "path": f"specs/{path.name}", "yaml": text[:20000],
            "system_prompt": spec.system_prompt}


# ---------- removing an agent ----------
#
# The spec file is moved to the Trash (recycle bin), never deleted, so it can be put back.


def move_to_trash(path: Path) -> None:
    """Moves a file to the Trash so it can be restored from there."""
    try:
        from send2trash import send2trash
    except ImportError as e:
        raise HTTPException(status_code=501, detail="Trash support is not installed. Run: pip install send2trash") from e
    send2trash(str(path))


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        return True  # not a browser page
    return urlparse(origin).netloc.lower() == (request.headers.get("host") or "").lower()


@app.delete("/api/agents/{name}")
def api_remove_agent(name: str, request: Request, notes: bool = False) -> dict[str, Any]:
    if request.headers.get("x-agentfactory") != "1" or not _same_origin(request):
        raise HTTPException(status_code=403, detail="This request did not come from the AgentFactory page.")
    spec = find_spec(name)
    path = spec_files().get(spec.name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"No agent called '{name}'.")
    try:
        move_to_trash(path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not move the file to the Trash ({type(e).__name__}).") from e
    result: dict[str, Any] = {"removed": spec.name, "file": path.name, "notes_moved": False}
    notes_file = ToolContext(spec, ROOT).notes_file
    if notes and notes_file.is_file():
        try:
            move_to_trash(notes_file)
            result["notes_moved"] = True
        except Exception as e:  # the agent is already gone; say that the notes stayed
            result["notes_error"] = f"The notes could not be moved ({type(e).__name__})."
    return result


# ---------- hiring a new agent ----------
#
# The page sends a plain form. The server turns it into an AgentSpec with the same validation the
# terminal interviewer uses, shows a preview, and only writes the file when the user approves.
# "Draft" asks the local model to fill the form in from a free-text description.

HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{6}")
DEFAULT_PROMPT = (
    "You are a helpful assistant. Your job: {goal} "
    "Use only the tools you have been given. If you are not sure about something, say so instead of guessing."
)
HIRE_LOCK = threading.Lock()  # two hires with the same name must not both succeed


class HireForm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field("", max_length=60)
    display_name: str = Field("", max_length=30)
    goal: str = Field("", max_length=600)
    system_prompt: str = Field("", max_length=4000)
    mode: Literal["task", "conversational"] = "conversational"
    tools: list[str] = Field(default_factory=list, max_length=20)
    fs_read: list[str] = Field(default_factory=list)
    fs_write: list[str] = Field(default_factory=list)
    network: list[str] = Field(default_factory=list)
    allow_overwrite: bool = False
    color: str | None = None
    hair: str | None = None

    @field_validator("fs_read", "fs_write", "network")
    @classmethod
    def _tidy(cls, v: list[str]) -> list[str]:
        out = [item.strip() for item in v if item.strip()]
        if len(out) > 10:
            raise ValueError("at most 10 entries")
        if any(len(item) > 200 for item in out):
            raise ValueError("entries must be shorter than 200 characters")
        return out

    @field_validator("color", "hair")
    @classmethod
    def _hex(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if not HEX_COLOUR.fullmatch(v):
            raise ValueError("colours must look like #8c7cf6")
        return v


def _form_errors(err: ValidationError) -> JSONResponse:
    errors = []
    for e in err.errors():
        loc = [str(x) for x in e["loc"]]
        if loc and loc[0] == "permissions" and len(loc) > 1:
            loc = loc[1:]
        if loc and loc[0] == "appearance" and len(loc) > 1:
            loc = loc[1:]
        errors.append({"field": loc[0] if loc else "", "message": e["msg"].removeprefix("Value error, ")})
    message = errors[0]["message"] if errors else "The form is not valid."
    return JSONResponse(status_code=422, content={"detail": message, "errors": errors})


class FormInvalid(Exception):
    def __init__(self, response: JSONResponse) -> None:
        self.response = response


@app.exception_handler(FormInvalid)
async def _form_invalid(request: Request, exc: FormInvalid) -> JSONResponse:
    return exc.response


def _require_page(request: Request) -> None:
    if request.headers.get("x-agentfactory") != "1" or not _same_origin(request):
        raise HTTPException(status_code=403, detail="This request did not come from the AgentFactory page.")


def _parse_form(body: dict[str, Any]) -> HireForm:
    try:
        return HireForm.model_validate(body)
    except ValidationError as e:
        raise FormInvalid(_form_errors(e)) from e


def _spec_from_form(form: HireForm) -> AgentSpec:
    unavailable = [t for t in form.tools if t not in IMPLEMENTED]
    if unavailable:
        raise FormInvalid(JSONResponse(status_code=422, content={
            "detail": f"The tool {unavailable[0]} does not exist yet.",
            "errors": [{"field": "tools", "message": f"The tool {unavailable[0]} does not exist yet."}]}))
    # Least privilege: a folder or website only counts when a tool that needs it is switched on.
    needs = {TOOL_REQUIRES.get(t) for t in form.tools}
    goal = form.goal.strip()
    draft = {
        "name": form.name.strip(),
        "goal": goal,
        "system_prompt": form.system_prompt.strip() or DEFAULT_PROMPT.format(goal=goal),
        "mode": form.mode,
        "tools": form.tools,
        "fs_read": form.fs_read if "fs_read" in needs else [],
        "fs_write": form.fs_write if "fs_write" in needs else [],
        "network": form.network if "network" in needs else [],
        "trigger_type": "manual",
    }
    try:
        data = draft_to_spec(draft).model_dump(mode="json")
        data["permissions"]["allow_overwrite"] = bool(form.allow_overwrite and draft["fs_write"])
        data["appearance"] = {"display_name": form.display_name.strip() or None, "color": form.color, "hair": form.hair}
        return AgentSpec.model_validate(data)
    except ValidationError as e:
        raise FormInvalid(_form_errors(e)) from e


def _form_notes(form: HireForm, spec: AgentSpec) -> list[str]:
    notes = capability_notes([{"role": "user", "content": f"{form.goal} {form.system_prompt}"}], spec)
    for raw in spec.permissions.fs_read + spec.permissions.fs_write:
        path = Path(raw).expanduser()
        if not (path if path.is_absolute() else ROOT / path).exists():
            notes.append(f"The folder '{raw}' does not exist yet. The agent will find nothing there until you create it.")
    return notes


def _agent_exists(name: str) -> bool:
    return (SPECS_DIR / f"{name}.yaml").exists() or name in spec_files() or any(s.name == name for s in load_all()[0])


@app.get("/api/hire/options")
def api_hire_options() -> dict[str, Any]:
    tools = [{"id": t.id, "description": t.description, "needs": TOOL_REQUIRES.get(t.id, "")} for t in IMPLEMENTED.values()]
    return {"tools": sorted(tools, key=lambda t: t["id"]), "max_tools": MAX_TOOLS}


@app.post("/api/hire/preview")
def api_hire_preview(request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    _require_page(request)
    form = _parse_form(body)
    spec = _spec_from_form(form)
    return {
        "name": spec.name,
        "file": f"{spec.name}.yaml",
        "yaml": yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        "warnings": permission_warnings(spec, ROOT),
        "notes": _form_notes(form, spec),
        "exists": _agent_exists(spec.name),
    }


@app.post("/api/hire")
def api_hire(request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    _require_page(request)
    spec = _spec_from_form(_parse_form(body))
    with HIRE_LOCK:
        if _agent_exists(spec.name):
            raise HTTPException(status_code=409, detail=f"An agent called '{spec.name}' already exists. Choose another name.")
        try:
            path = save_spec(spec, SPECS_DIR)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Could not save the agent file ({type(e).__name__}).") from e
    return summarize(spec, ollama_models(), path)


def _form_from_spec(spec: AgentSpec) -> dict[str, Any]:
    return {
        "name": spec.name, "display_name": "", "goal": spec.goal, "system_prompt": spec.system_prompt,
        "mode": spec.mode, "tools": [t for t in spec.tools if t in IMPLEMENTED],
        "fs_read": spec.permissions.fs_read, "fs_write": spec.permissions.fs_write,
        "network": spec.permissions.network, "allow_overwrite": spec.permissions.allow_overwrite,
    }


@app.post("/api/hire/draft")
async def api_hire_draft(request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    _require_page(request)
    description = str(body.get("description", "")).strip()
    if len(description) < 10:
        raise HTTPException(status_code=422, detail="Describe in a sentence or two what the agent should do.")
    if len(description) > 2000:
        raise HTTPException(status_code=422, detail="That description is too long (limit 2000 characters).")
    transcript = [{"role": "user", "content": description}]
    async with MODEL_LOCK:
        try:
            provider = make_provider(ModelConfig())
            spec = await asyncio.to_thread(build_spec, provider, transcript)
        except ProviderError as e:
            raise HTTPException(status_code=503, detail=f"The model is not available: {e}") from e
        except SpecBuildError as e:
            raise HTTPException(status_code=422, detail=f"Nova could not turn that into a valid agent. {e}") from e
        except Exception as e:  # keep the server alive whatever the model does
            raise HTTPException(status_code=500, detail=f"Something went wrong while drafting ({type(e).__name__}).") from e
    return {"fields": _form_from_spec(spec), "notes": capability_notes(transcript, spec)}


# ---------- chat websocket ----------
#
# client -> server: {"type": "message", "text": "..."}
# server -> client: {"event": "ready" | "queued" | "started" | "trace" | "reply" | "error", "payload": {...}}


def _origin_ok(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if origin is None:
        return True  # not a browser page
    return urlparse(origin).netloc.lower() == (ws.headers.get("host") or "").lower()


def _clean(entry: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(entry, default=str))


async def _run_turn(ws: WebSocket, session: AgentSession, text: str, events: asyncio.Queue) -> None:
    if MODEL_LOCK.locked():
        await ws.send_json({"event": "queued", "payload": {}})
    async with MODEL_LOCK:
        await ws.send_json({"event": "started", "payload": {}})
        started = time.monotonic()
        gone = False

        async def forward() -> None:
            nonlocal gone
            while True:
                entry = await events.get()
                if entry is None:
                    return
                if gone:
                    continue
                try:
                    await ws.send_json({"event": "trace", "payload": entry})
                except Exception:
                    gone = True

        forwarder = asyncio.create_task(forward())
        result = None
        failure = ""
        try:
            result = await asyncio.to_thread(session.send, text)
        except Exception as e:  # a bug inside an agent must not take the server down
            failure = f"{type(e).__name__}: {e}"
        events.put_nowait(None)
        await forwarder
        if gone:
            raise WebSocketDisconnect()
        if result is None:
            await ws.send_json({"event": "error", "payload": {
                "message": f"Something went wrong inside the agent ({failure}). Start a new chat to reset it."}})
            return
        await ws.send_json({"event": "reply", "payload": {
            "text": result.final_text,
            "ok": result.ok,
            "stop_reason": result.stop_reason,
            "steps": result.steps,
            "tokens": result.tokens,
            "seconds": round(time.monotonic() - started, 1),
        }})


@app.websocket("/ws/chat/{name}")
async def ws_chat(ws: WebSocket, name: str) -> None:
    if not _origin_ok(ws):
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        spec = await asyncio.to_thread(find_spec, name)
    except HTTPException:
        await ws.send_json({"event": "error", "payload": {"message": f"No agent called '{name}'.", "fatal": True}})
        await ws.close()
        return

    loop = asyncio.get_running_loop()
    events: asyncio.Queue = asyncio.Queue()

    def on_event(entry: dict[str, Any]) -> None:  # called from the worker thread
        loop.call_soon_threadsafe(events.put_nowait, _clean(entry))

    def new_session() -> AgentSession:
        return AgentSession(spec, make_provider(spec.model), base_dir=ROOT, on_event=on_event)

    try:
        session = new_session()
    except (NotImplementedError, ProviderError) as e:
        await ws.send_json({"event": "error", "payload": {"message": str(e), "fatal": True}})
        await ws.close()
        return

    await ws.send_json({"event": "ready", "payload": {"agent": spec.name, "mode": spec.mode}})
    try:
        while True:
            try:
                data = await ws.receive_json()
            except ValueError:
                continue
            if not isinstance(data, dict) or data.get("type") != "message":
                continue
            text = str(data.get("text", "")).strip()
            if not text:
                continue
            if len(text) > MAX_MESSAGE_CHARS:
                await ws.send_json({"event": "error", "payload": {
                    "message": f"That message is too long (limit {MAX_MESSAGE_CHARS} characters)."}})
                continue
            if spec.mode == "task":  # task agents start fresh for every message
                try:
                    session = new_session()
                except (NotImplementedError, ProviderError) as e:
                    await ws.send_json({"event": "error", "payload": {"message": str(e)}})
                    continue
            await _run_turn(ws, session, text, events)
    except (WebSocketDisconnect, RuntimeError):
        return
