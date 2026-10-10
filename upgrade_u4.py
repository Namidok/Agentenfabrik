"""Upgrade AgentFactory to U4: the hiring popup. Run once from the project folder: python upgrade_u4.py

Every piece is matched exactly once before anything is written, so a mismatch changes nothing."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
problems = []


def swap(text, old, new, label):
    if text.count(old) != 1:
        problems.append(f"{label} (found {text.count(old)} times)")
        return text
    return text.replace(old, new)


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


texts = {}

factory_schema_py = read("factory/schema.py")
factory_schema_py = swap(factory_schema_py, r'''
class AgentSpec(Strict):''', r'''
class Appearance(Strict):
    """How the agent looks in the office. Everything is optional."""
    display_name: str | None = Field(None, max_length=30)
    color: str | None = None  # shirt and accent colour, "#rrggbb"
    hair: str | None = None   # hair colour, "#rrggbb"

    @field_validator("color", "hair")
    @classmethod
    def _hex(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
            raise ValueError("colours must look like #8c7cf6")
        return v


class AgentSpec(Strict):''', "factory/schema.py #1")

factory_schema_py = swap(factory_schema_py, r'''    success_criteria: list[str] = Field(default_factory=list)
    read_before_answer: bool = False''', r'''    success_criteria: list[str] = Field(default_factory=list)
    appearance: Appearance = Field(default_factory=Appearance)
    read_before_answer: bool = False''', "factory/schema.py #2")

texts["factory/schema.py"] = factory_schema_py

factory_server_py = read("factory/server.py")
factory_server_py = swap(factory_server_py, r'''import re
import time''', r'''import re
import threading
import time''', "factory/server.py #1")

factory_server_py = swap(factory_server_py, r'''from pathlib import Path
from typing import Any
from urllib.parse import urlparse''', r'''from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse''', "factory/server.py #2")

factory_server_py = swap(factory_server_py, r'''import yaml
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware''', r'''import yaml
from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware''', "factory/server.py #3")

factory_server_py = swap(factory_server_py, r'''
from factory.interviewer import permission_warnings
from factory.llm import ProviderError, make_provider''', r'''
from factory.interviewer import SpecBuildError, build_spec, capability_notes, draft_to_spec, permission_warnings, save_spec
from factory.llm import ProviderError, make_provider''', "factory/server.py #4")

factory_server_py = swap(factory_server_py, r'''from factory.runtime import AgentSession
from factory.schema import AgentSpec, load_spec
from factory.tools import IMPLEMENTED, ToolContext''', r'''from factory.runtime import AgentSession
from factory.schema import MAX_TOOLS, TOOL_REQUIRES, AgentSpec, ModelConfig, load_spec
from factory.tools import IMPLEMENTED, ToolContext''', "factory/server.py #5")

factory_server_py = swap(factory_server_py, r'''        "file": file.name if file else "",
    }''', r'''        "file": file.name if file else "",
        "display_name": spec.appearance.display_name or "",
        "color": spec.appearance.color or "",
        "hair": spec.appearance.hair or "",
    }''', "factory/server.py #6")

factory_server_py = swap(factory_server_py, r'''    return result
''', r'''    return result


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
''', "factory/server.py #7")

texts["factory/server.py"] = factory_server_py

static_index_html = read("static/index.html")
static_index_html = swap(static_index_html, r'''          <h2 id="roster-title">Your agents <span class="count" id="agent-count"></span></h2>
          <button type="button" class="btn-quiet" id="refresh-agents" title="Reload the agents from the specs folder">Refresh</button>
        </div>''', r'''          <h2 id="roster-title">Your agents <span class="count" id="agent-count"></span></h2>
          <span class="panel-actions">
            <button type="button" class="btn-quiet" id="new-agent-btn" title="Hire a new agent">New agent</button>
            <button type="button" class="btn-quiet" id="refresh-agents" title="Reload the agents from the specs folder">Refresh</button>
          </span>
        </div>''', "static/index.html #1")

static_index_html = swap(static_index_html, r'''
  <script src="/static/office.js"></script>
  <script src="/static/nova.js"></script>''', r'''
  <dialog class="dialog dialog-wide" id="hire-dialog" aria-labelledby="hire-title">
    <form id="hire-form" novalidate autocomplete="off">
      <header class="hire-head">
        <div class="avatar" aria-hidden="true"><canvas id="hire-nova"></canvas></div>
        <div class="hire-head-text">
          <h2 id="hire-title">Hire a new agent</h2>
          <p id="hire-sub"></p>
        </div>
        <button type="button" class="btn-quiet" id="hire-x" aria-label="Close without hiring" title="Close (Esc)">&#10005;</button>
      </header>

      <div class="hire-body" id="hire-body">
        <div id="hire-step-form">
          <section class="hire-section">
            <h3>1. Describe it</h3>
            <label for="hire-describe">In your own words, what should this agent do for you?</label>
            <textarea id="hire-describe" rows="3" maxlength="2000" placeholder="For example: A C++ teacher that explains memory and concurrency, quizzes me and remembers what I struggled with."></textarea>
            <div class="hire-row">
              <button type="button" class="btn-secondary" id="hire-draft">Let Nova fill in the form</button>
              <span class="hint" id="hire-draft-status" role="status"></span>
            </div>
            <p class="hint">Or skip this and fill in the form yourself. Nova's draft always needs a quick check.</p>
          </section>

          <section class="hire-section">
            <h3>2. Who is it?</h3>
            <label for="hire-name">Name</label>
            <input type="text" id="hire-name" maxlength="30" placeholder="Ada the C++ Tutor" aria-describedby="hire-slug">
            <p class="hint" id="hire-slug"></p>
            <label for="hire-goal">Goal, in one sentence</label>
            <input type="text" id="hire-goal" maxlength="600" placeholder="Teach me C++ memory management with short exercises.">
            <fieldset class="choice">
              <legend>How do you work with it?</legend>
              <label class="option"><input type="radio" name="hire-mode" id="hire-mode-chat" value="conversational" checked>
                <span><strong>Chat</strong><small>A back-and-forth conversation that remembers what was said.</small></span></label>
              <label class="option"><input type="radio" name="hire-mode" value="task">
                <span><strong>Task</strong><small>You give it a job and get one answer. Every message starts fresh.</small></span></label>
            </fieldset>
            <label for="hire-prompt">Instructions <span class="optional">(optional)</span></label>
            <textarea id="hire-prompt" rows="3" maxlength="4000" placeholder="How it should behave, what it must never do. Leave empty and a sensible default is used."></textarea>
          </section>

          <section class="hire-section">
            <h3>3. What may it use?</h3>
            <p class="hint">Every tool is a permission. Pick only what the job needs. <span id="hire-tool-count"></span></p>
            <div class="tools" id="hire-tools" role="group" aria-label="Tools"></div>
            <div class="perm" id="hire-read-row" hidden>
              <label for="hire-read">Folders it may read <span class="optional">(one per line)</span></label>
              <textarea id="hire-read" rows="2" placeholder="./sandbox"></textarea>
              <p class="hint">Relative to the AgentFactory folder. It cannot go outside the folders listed here.</p>
            </div>
            <div class="perm" id="hire-write-row" hidden>
              <label for="hire-write">Folders it may write into <span class="optional">(one per line)</span></label>
              <textarea id="hire-write" rows="2" placeholder="./out"></textarea>
              <label class="check"><input type="checkbox" id="hire-overwrite"> It may replace files that already exist</label>
            </div>
            <div class="perm" id="hire-net-row" hidden>
              <label for="hire-net">Websites it may visit <span class="optional">(one per line)</span></label>
              <textarea id="hire-net" rows="2" placeholder="en.wikipedia.org"></textarea>
              <p class="hint">Plain domains only, like example.com. No wildcards.</p>
            </div>
            <p class="callout is-warn" id="hire-shell-note" hidden>This agent will compile and run code on your computer. It is not isolated, so that code could read your files or use the network.</p>
            <p class="callout" id="hire-notes-note" hidden>It keeps a notes file under data/ so it can remember things between chats.</p>
          </section>

          <section class="hire-section">
            <h3>4. How does it look?</h3>
            <div class="look">
              <div class="look-preview">
                <div class="avatar" aria-hidden="true"><canvas id="hire-preview-face"></canvas></div>
                <strong id="hire-preview-name"></strong>
              </div>
              <div class="look-pickers">
                <fieldset class="swatches"><legend>Shirt and accent colour</legend><div id="hire-colors"></div></fieldset>
                <fieldset class="swatches"><legend>Hair</legend><div id="hire-hairs"></div></fieldset>
              </div>
            </div>
          </section>
        </div>

        <div id="hire-step-review" hidden>
          <div class="review-top">
            <div class="avatar" aria-hidden="true"><canvas id="hire-review-face"></canvas></div>
            <div>
              <h3 id="hire-review-name"></h3>
              <p id="hire-review-goal"></p>
            </div>
          </div>
          <dl class="summary" id="hire-summary"></dl>
          <div class="callout is-warn" id="hire-warn-box" hidden>
            <strong>Check before you approve</strong>
            <ul id="hire-warnings"></ul>
          </div>
          <div class="callout" id="hire-notes-box" hidden>
            <strong>Heads up</strong>
            <ul id="hire-notes"></ul>
          </div>
          <details class="yaml">
            <summary>Show the agent file</summary>
            <pre id="hire-yaml"></pre>
          </details>
        </div>
      </div>

      <p class="dialog-error" id="hire-error" role="alert" hidden></p>
      <div class="dialog-actions" id="hire-actions-form">
        <button type="button" class="btn-quiet" id="hire-clear" title="Empty the whole form">Clear</button>
        <span class="spacer"></span>
        <button type="button" class="btn-secondary" id="hire-cancel">Cancel</button>
        <button type="button" class="btn-primary" id="hire-review-btn">Review</button>
      </div>
      <div class="dialog-actions" id="hire-actions-review" hidden>
        <button type="button" class="btn-secondary" id="hire-back">Back to edit</button>
        <span class="spacer"></span>
        <button type="button" class="btn-primary" id="hire-approve">Approve and hire</button>
      </div>
    </form>
  </dialog>

  <script src="/static/office.js"></script>
  <script src="/static/hire.js"></script>
  <script src="/static/nova.js"></script>''', "static/index.html #2")

texts["static/index.html"] = static_index_html

static_style_css = read("static/style.css")
static_style_css = swap(static_style_css, r'''
/* ---------- smaller screens ---------- */''', r'''
/* ---------- hiring popup ---------- */

.panel-actions { display: inline-flex; gap: 0.1rem; }
.dialog-wide { width: min(46rem, calc(100% - 2rem)); max-height: calc(100dvh - 2rem); padding: 0; overflow: hidden; }
.dialog-wide form { display: flex; flex-direction: column; max-height: calc(100dvh - 2rem); }
.hire-head { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 0.85rem; align-items: center; padding: 1rem 1.3rem 0.8rem; border-bottom: 1px solid var(--rule); }
.hire-head .avatar { --accent: #2ec4a0; width: 3rem; height: 3rem; }
.hire-head h2 { margin: 0; }
.hire-head p { margin: 0.15rem 0 0; color: var(--ink-2); font-size: var(--t-sm); }
.hire-body { overflow-y: auto; padding: 0.4rem 1.3rem 1rem; min-height: 0; }
.hire-section { padding: 0.9rem 0 0.4rem; border-bottom: 1px solid var(--rule); }
.hire-section:last-child { border-bottom: 0; }
.hire-section h3 { font-size: var(--t-md); margin-bottom: 0.6rem; color: var(--accent); }
.dialog-wide label { display: block; margin: 0.6rem 0 0.25rem; font-weight: 600; font-size: var(--t-sm); }
.dialog-wide label.check, .dialog-wide label.option, .dialog-wide label.tool, .dialog-wide label.swatch { font-weight: 400; font-size: var(--t-base); margin: 0; }
.optional { color: var(--ink-2); font-weight: 400; }
.dialog-wide input[type="text"], .dialog-wide textarea {
  width: 100%; padding: 0.5rem 0.65rem; color: var(--ink); background: var(--bg);
  border: 1px solid var(--rule); border-radius: 8px; font: inherit; resize: vertical;
}
.dialog-wide input[type="text"]:focus-visible, .dialog-wide textarea:focus-visible { border-color: var(--accent); outline-offset: 0; }
.dialog-wide [aria-invalid="true"] { border-color: var(--high); }
.dialog-wide .hint { margin: 0.3rem 0 0.2rem; color: var(--ink-2); font-size: var(--t-xs); }
.hire-row { display: flex; align-items: center; gap: 0.8rem; margin-top: 0.6rem; }
.hire-row .hint { margin: 0; }
.dialog-wide fieldset { border: 0; margin: 0.8rem 0 0; padding: 0; min-width: 0; }
.dialog-wide legend { padding: 0; font-weight: 600; font-size: var(--t-sm); margin-bottom: 0.3rem; }
.option, .tool { display: flex !important; gap: 0.6rem; align-items: flex-start; padding: 0.5rem 0.65rem; border: 1px solid var(--rule); border-radius: 8px; cursor: pointer; }
.option + .option { margin-top: 0.4rem; }
.option:hover, .tool:hover { border-color: var(--accent); }
.option:has(input:checked), .tool:has(input:checked) { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, transparent); }
.option span, .tool-text { display: grid; gap: 0.05rem; min-width: 0; }
.option small, .tool small { color: var(--ink-2); font-size: var(--t-xs); overflow-wrap: anywhere; }
.tools { display: grid; grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr)); gap: 0.4rem; }
.tool:has(input:disabled) { opacity: 0.5; cursor: not-allowed; }
.perm { margin-top: 0.6rem; }
.callout { margin: 0.8rem 0 0; padding: 0.55rem 0.75rem; border-radius: 8px; border: 1px solid var(--rule); background: var(--panel); color: var(--ink-2); font-size: var(--t-sm); }
.callout.is-warn { border-color: var(--medium); background: var(--medium-tint); color: var(--ink); }
.callout ul { margin: 0.3rem 0 0; padding-left: 1.2rem; }
.callout li + li { margin-top: 0.25rem; }

.look { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 1.2rem; align-items: center; }
.look-preview { display: grid; justify-items: center; gap: 0.4rem; width: 6.5rem; }
.look-preview .avatar, .review-top .avatar { width: 4.2rem; height: 4.2rem; --accent: var(--ink-2); }
.look-preview strong { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--t-sm); }
.swatches > div { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.swatch { position: relative; display: inline-flex; cursor: pointer; }
.swatch input { position: absolute; opacity: 0; inset: 0; margin: 0; cursor: pointer; }
.swatch span { width: 1.7rem; height: 1.7rem; border-radius: 50%; border: 2px solid var(--rule); display: grid; place-items: center; font-size: var(--t-xs); font-weight: 700; color: var(--ink-2); }
.swatch input:checked + span { border-color: var(--ink); box-shadow: 0 0 0 2px var(--bg), 0 0 0 4px var(--ink); }
.swatch input:focus-visible + span { outline: 2px solid var(--focus); outline-offset: 3px; }
.swatch.is-auto span { border-style: dashed; }

.review-top { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 1rem; align-items: center; padding-top: 0.8rem; }
.review-top h3 { font-size: var(--t-lg); }
.review-top p { margin: 0.2rem 0 0; color: var(--ink-2); overflow-wrap: anywhere; }
.summary { display: grid; grid-template-columns: 7rem minmax(0, 1fr); gap: 0.35rem 1rem; margin: 1rem 0 0; font-size: var(--t-sm); }
.summary dt { color: var(--ink-2); }
.summary dd { margin: 0; overflow-wrap: anywhere; }
.yaml { margin-top: 1rem; }
.yaml summary { cursor: pointer; color: var(--accent); font-weight: 600; font-size: var(--t-sm); }
.yaml pre { margin: 0.5rem 0 0; padding: 0.7rem; max-height: 14rem; overflow: auto; background: var(--bg); border: 1px solid var(--rule); border-radius: 8px; white-space: pre-wrap; overflow-wrap: anywhere; }

.dialog-wide .dialog-error { margin: 0 1.3rem 0.6rem; }
.dialog-wide .dialog-error div + div { margin-top: 0.2rem; }
.dialog-wide .dialog-actions { align-items: center; padding: 0.8rem 1.3rem 1rem; border-top: 1px solid var(--rule); }
.dialog-actions .spacer { flex: 1; }

/* ---------- smaller screens ---------- */''', "static/style.css #1")

static_style_css = swap(static_style_css, r'''  *, *::before, *::after { animation: none !important; transition: none !important; }
}
''', r'''  *, *::before, *::after { animation: none !important; transition: none !important; }
}

@media (max-width: 640px) {
  .look { grid-template-columns: minmax(0, 1fr); }
  .summary { grid-template-columns: minmax(0, 1fr); }
  .hire-row { flex-direction: column; align-items: flex-start; }
}
''', "static/style.css #2")

texts["static/style.css"] = static_style_css

static_nova_js = read("static/nova.js")
static_nova_js = swap(static_nova_js, r'''  const KEY = "agentfactory.intro";
  const COMMAND = "python new_agent.py";
  const LINES = [''', r'''  const KEY = "agentfactory.intro";
  const LINES = [''', "static/nova.js #1")

static_nova_js = swap(static_nova_js, r'''    markSeen();
    show({
      text: "Great! Describing your agent to me in a conversation is the next thing I am learning. " +
        `For now, run "${COMMAND}" in your terminal and answer the questions. Your new agent will walk in through the staff door on its own.`,
      actions: [
        { label: "Copy the command", run: copyCommand },
        { label: "Got it", primary: true, run: close },
      ],
    });
  }

  async function copyCommand(event) {
    const button = event.currentTarget;
    try {
      await navigator.clipboard.writeText(COMMAND);
      button.textContent = "Copied";
    } catch {
      button.textContent = "Select it above and copy";
    }
    setTimeout(() => { button.textContent = "Copy the command"; }, 1800);
  }''', r'''    markSeen();
    close();
    Office.guide.say("Tell me all about it!", 4);
    Hire.open((hired) => {
      if (hired) Office.guide.say(`Welcome aboard, ${hired.label}!`, 5);
      else Office.guide.say("No problem. I'm here when you're ready.", 4);
    });
  }''', "static/nova.js #2")

static_nova_js = swap(static_nova_js, r'''  init();
  window.Nova = { boot, menu };
})();''', r'''  init();
  window.Nova = { boot, menu, hire };
})();''', "static/nova.js #3")

texts["static/nova.js"] = static_nova_js

static_app_js = read("static/app.js")
static_app_js = swap(static_app_js, r'''    leaving: new Map(), // agents on their way out: name -> last known summary
  };''', r'''    leaving: new Map(), // agents on their way out: name -> last known summary
    hired: new Map(), // agents hired in this session: name -> goal, for their introduction
  };''', "static/app.js #1")

static_app_js = swap(static_app_js, r'''  }
  const colorOf = (name) => PALETTE[hash(name) % PALETTE.length];
  const pretty = (name) => name.split("-").map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w)).join(" ");
  const clip = (text, n) => (text.length > n ? text.slice(0, n - 1) + "…" : text);''', r'''  }
  // Looks chosen in the hiring form (display name, colours), by agent name.
  const custom = new Map();
  const colorOf = (name) => (custom.get(name) || {}).color || PALETTE[hash(name) % PALETTE.length];
  const pretty = (name) => (custom.get(name) || {}).label ||
    name.split("-").map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w)).join(" ");
  const clip = (text, n) => (text.length > n ? text.slice(0, n - 1) + "…" : text);''', "static/app.js #2")

static_app_js = swap(static_app_js, r'''    const picture = document.createElement("canvas");
    Office.portrait(picture, { name, color: colorOf(name) });
    return el("div", { class: "avatar", "aria-hidden": "true", id, style: accent(name) }, picture);''', r'''    const picture = document.createElement("canvas");
    Office.portrait(picture, { name, color: colorOf(name), hair: (custom.get(name) || {}).hair || null });
    return el("div", { class: "avatar", "aria-hidden": "true", id, style: accent(name) }, picture);''', "static/app.js #3")

static_app_js = swap(static_app_js, r'''      color: colorOf(a.name),
      mode: a.mode,''', r'''      color: colorOf(a.name),
      hair: (custom.get(a.name) || {}).hair || null,
      mode: a.mode,''', "static/app.js #4")

static_app_js = swap(static_app_js, r'''    if (!state.agents.length) {
      list.append(el("li", { class: "log-empty", text: "No agents yet. Create one with python new_agent.py, then press Refresh." }));
    }''', r'''    if (!state.agents.length) {
      list.append(el("li", { class: "log-empty", text: "No agents yet. Press New agent and Nova will help you hire one." }));
    }''', "static/app.js #5")

static_app_js = swap(static_app_js, r'''    state.signature = signature;
    const previous = new Map(state.agents.map((a) => [a.name, a]));''', r'''    state.signature = signature;
    for (const a of data.agents) custom.set(a.name, { label: a.display_name || "", color: a.color || "", hair: a.hair || "" });
    const previous = new Map(state.agents.map((a) => [a.name, a]));''', "static/app.js #6")

static_app_js = swap(static_app_js, r'''      for (const a of data.agents) {
        if (!before.has(a.name)) Office.walkIn(a.name, "staff", () => Office.say(a.name, `Hi, I'm ${pretty(a.name)}!`, 5));
      }''', r'''      for (const a of data.agents) {
        if (before.has(a.name)) continue;
        const hired = state.hired.has(a.name);
        Office.walkIn(a.name, "staff", () => {
          Office.say(a.name, `Hi, I'm ${pretty(a.name)}!`, 5);
          if (hired) selectAgent(a.name); // someone you just hired introduces themselves in their chat
        });
      }''', "static/app.js #7")

static_app_js = swap(static_app_js, r'''  function showWelcome(chat, agent) {
    addSystem(chat, `${pretty(agent.name)} is at their desk.` +''', r'''  function showWelcome(chat, agent) {
    if (state.hired.has(agent.name)) {
      addSystem(chat, `Hi, I'm ${pretty(agent.name)}. My job: ${state.hired.get(agent.name)}`);
      state.hired.delete(agent.name);
    }
    addSystem(chat, `${pretty(agent.name)} is at their desk.` +''', "static/app.js #8")

static_app_js = swap(static_app_js, r'''  $("refresh-agents").addEventListener("click", () => { loadConfig(); loadAgents(); });
  $("ollama-pill").addEventListener("click", loadConfig);''', r'''  $("refresh-agents").addEventListener("click", () => { loadConfig(); loadAgents(); });
  $("new-agent-btn").addEventListener("click", () => Nova.hire());
  document.addEventListener("agentfactory:hired", (event) => {
    state.hired.set(event.detail.name, event.detail.goal);
    loadAgents();
  });
  $("ollama-pill").addEventListener("click", loadConfig);''', "static/app.js #9")

static_app_js = swap(static_app_js, r'''  });
  loadConfig();''', r'''  });
  Hire.init({ colorOf });
  loadConfig();''', "static/app.js #10")

texts["static/app.js"] = static_app_js

if "field_validator" not in texts["factory/schema.py"] or "\nimport re\n" not in texts["factory/schema.py"]:
    problems.append("factory/schema.py does not import re and field_validator as expected")

if problems:
    print("Nothing was changed. These pieces did not match:")
    for p in problems:
        print("  -", p)
    raise SystemExit(1)

for rel, content in texts.items():
    (ROOT / rel).write_text(content, encoding="utf-8")
print("Done: schema.py, server.py, index.html, style.css, nova.js and app.js updated.")
