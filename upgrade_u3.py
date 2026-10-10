"""U3 upgrade: Nova (front-desk guide), pixel avatars, automatic arrival of new agents, and
removing an agent (its spec file goes to the Trash).

Edits factory/server.py and static/{office.js,index.html,style.css,app.js} together, or none of
them if anything unexpected is found. nova.js is a separate new file.
Usage: python upgrade_u3.py   (run it in the project folder)"""
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
STATIC = ROOT / "static"
SERVER = ROOT / "factory" / "server.py"
problems = []


def load(path):
    return path.read_text(encoding="utf-8")


def swap(text, old, new, label):
    if text.count(old) != 1:
        problems.append(f"{label}: expected piece not found exactly once")
        return text
    return text.replace(old, new)


# =====================================================================
# factory/server.py
# =====================================================================
server = load(SERVER)

server = swap(server, "from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect",
              "from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect", "server import")

server = swap(server, "def summarize(spec: AgentSpec, models: list[str] | None) -> dict[str, Any]:",
              "def spec_files() -> dict[str, Path]:\n"
              '    """Which file defines each agent (the first valid file wins, as in load_all)."""\n'
              "    found: dict[str, Path] = {}\n"
              "    if SPECS_DIR.is_dir():\n"
              '        for path in sorted(SPECS_DIR.glob("*.yaml")):\n'
              "            try:\n"
              "                spec = load_spec(path)\n"
              "            except (ValidationError, OSError, UnicodeDecodeError, yaml.YAMLError):\n"
              "                continue\n"
              "            found.setdefault(spec.name, path)\n"
              "    return found\n\n\n"
              "def summarize(spec: AgentSpec, models: list[str] | None, file: Path | None = None) -> dict[str, Any]:",
              "server summarize head")
server = swap(server, '        "has_notes": ToolContext(spec, ROOT).notes_file.is_file(),\n    }',
              '        "has_notes": ToolContext(spec, ROOT).notes_file.is_file(),\n        "file": file.name if file else "",\n    }',
              "server summarize file")
server = swap(server, '    return {"agents": [summarize(s, models) for s in specs], "problems": problems}',
              "    files = spec_files()\n"
              '    return {"agents": [summarize(s, models, files.get(s.name)) for s in specs], "problems": problems}',
              "server api_agents")

server = swap(server, "# ---------- chat websocket ----------", '''# ---------- removing an agent ----------
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


# ---------- chat websocket ----------''', "server remove route")

# =====================================================================
# static/office.js
# =====================================================================
office = load(STATIC / "office.js")

office = swap(office, '''    const phase = reduced.matches ? "stand" : (Math.floor(clock * 6) % 2 ? "stepA" : "stepB");
    const bob = reduced.matches ? 0 : (Math.floor(clock * 6) % 2 ? 0 : -1);''',
'''    const stepping = w.moving && !reduced.matches;
    const phase = stepping ? (Math.floor(clock * 6) % 2 ? "stepA" : "stepB") : "stand";
    const bob = reduced.matches ? 0 : stepping ? (Math.floor(clock * 6) % 2 ? 0 : -1) : (Math.floor(clock * 1.5) % 2 ? 0 : -1);''',
    "office walker animation")
office = swap(office, "...LEGS[w.moving ? phase : \"stand\"]]", "...LEGS[phase]]", "office legs")

office = swap(office, '''  function stepWalker(a, dt) {
    const w = a.walker;
    if (!w) return;
    if (w.door && w.y > TOP + 22) { doorState[w.door].target = 0; w.door = null; }
    let budget = SPEED * dt;''', '''  // Moves a walker along its path. True once it has arrived.
  function advance(w, dt) {
    if (w.door && (w.y > TOP + 22 || Math.abs(w.x - DOORS[w.door].x) > 40)) { doorState[w.door].target = 0; w.door = null; }
    let budget = SPEED * dt;''', "office advance head")
office = swap(office, '''    if (!w.path.length) {
      a.seated = true;
      a.walker = null;
      if (w.door) doorState[w.door].target = 0;
      if (w.done) w.done(a.name);
    }
  }
''', '''    return !w.path.length;
  }

  function stepWalker(a, dt) {
    const w = a.walker;
    if (!w || !advance(w, dt)) return;
    a.walker = null;
    if (w.leave) {
      doorState[w.leaveDoor].target = 0;
      if (w.done) w.done(a.name);
      return;
    }
    a.seated = true;
    if (w.door) doorState[w.door].target = 0;
    if (w.done) w.done(a.name);
  }

  // The agent stands up, walks to a door and leaves.
  function walkOut(name, door, done) {
    const a = agents.get(name);
    const index = order.indexOf(name);
    if (!a || index < 0 || !DOORS[door]) {
      if (done) done(name);
      return false;
    }
    const { cx, y0, col } = cellOf(index);
    const dx = DOORS[door].x;
    const aisle = col < COLS - 1 ? cx + 73 : cx - 73;
    a.seated = false;
    a.walker = {
      x: cx, y: y0 + 52, dir: "down", moving: true, done, leave: true, leaveDoor: door,
      path: reduced.matches ? [] : [
        { x: cx, y: y0 + 56 }, { x: aisle, y: y0 + 56 }, { x: aisle, y: TOP + 18 },
        { x: dx, y: TOP + 18 }, { x: dx, y: TOP + 4 },
      ],
    };
    doorState[door].target = 1;
    return true;
  }

  // A small face-and-shoulders picture for avatars elsewhere on the page.
  function portrait(canvas, info) {
    const pal = look({ name: info.name, color: info.color, hair: info.hair || null });
    const rows = [...HEAD_DOWN, ...TORSO.slice(0, 3)];
    canvas.width = 10;
    canvas.height = rows.length;
    const c = canvas.getContext("2d");
    c.clearRect(0, 0, canvas.width, canvas.height);
    rows.forEach((row, y) => {
      for (let x = 0; x < row.length; x++) {
        const ch = row[x];
        if (ch !== "." && pal[ch]) { c.fillStyle = pal[ch]; c.fillRect(x, y, 1, 1); }
      }
    });
  }

  // ---------- the front-desk guide ----------

  const GUIDE_NAME = "Nova";
  const GUIDE_SPOT = { x: 320, y: TOP + 19 };
  const GUIDE_LOOK = { name: "nova", color: "#2ec4a0", hair: "#a03a6a" };
  const guide = { on: false, x: GUIDE_SPOT.x, y: GUIDE_SPOT.y, walker: null, done: null, bubbleText: "", bubbleUntil: 0 };

  function finishGuideWalk() {
    const w = guide.walker;
    guide.x = w.x;
    guide.y = w.y;
    guide.walker = null;
    if (w.door) doorState[w.door].target = 0;
    const done = guide.done;
    guide.done = null;
    if (done) done();
  }

  function drawGuide() {
    const w = guide.walker || { x: guide.x, y: guide.y, dir: "down", moving: false };
    drawWalker(GUIDE_LOOK, w);
    text(GUIDE_NAME.toUpperCase(), w.x, w.y + 9, GUIDE_LOOK.color, 6);
    if (guide.bubbleUntil > clock && guide.bubbleText) bubble(w.x, w.y - 32, guide.bubbleText);
  }

  const guideApi = {
    look: GUIDE_LOOK,
    enter(done) {
      guide.on = true;
      guide.done = done || null;
      const w = {
        x: DOORS.front.x, y: TOP + 4, dir: "down", moving: true, door: "front",
        path: [{ x: DOORS.front.x, y: GUIDE_SPOT.y }, { x: GUIDE_SPOT.x, y: GUIDE_SPOT.y }],
      };
      if (reduced.matches) { w.x = GUIDE_SPOT.x; w.y = GUIDE_SPOT.y; w.path = []; }
      guide.walker = w;
      doorState.front.target = 1;
    },
    present() {
      guide.on = true;
      guide.walker = null;
      guide.x = GUIDE_SPOT.x;
      guide.y = GUIDE_SPOT.y;
    },
    say(str, seconds = 4) {
      guide.bubbleText = str;
      guide.bubbleUntil = clock + seconds;
    },
  };
''', "office advance tail")

office = swap(office, "    for (const a of agents.values()) stepWalker(a, dt);",
              "    for (const a of agents.values()) stepWalker(a, dt);\n    if (guide.walker && advance(guide.walker, dt)) finishGuideWalk();", "office frame")
office = swap(office, "    items.sort((p, q) => p.depth - q.depth);",
              "    if (guide.on) items.push({ depth: guide.walker ? guide.walker.y : guide.y, fn: drawGuide });\n    items.sort((p, q) => p.depth - q.depth);", "office draw")
office = swap(office, '    if (p.x > 248 && p.x < 392 && p.y > 12 && p.y < 42) return { kind: "sign" };',
              '    if (p.x > 248 && p.x < 392 && p.y > 12 && p.y < 42) return { kind: "sign" };\n'
              '    if (guide.on) {\n'
              '      const g = guide.walker || guide;\n'
              '      if (Math.abs(p.x - g.x) < 14 && p.y > g.y - 34 && p.y < g.y + 12) return { kind: "guide" };\n'
              '    }', "office hit test")
office = swap(office, '    if (hit.kind === "clock") return ["Office clock"',
              '    if (hit.kind === "guide") return [GUIDE_NAME, "Front desk guide", "Click to talk to her"];\n'
              '    if (hit.kind === "clock") return ["Office clock"', "office tooltip")
office = swap(office, '      return [a.label, `${a.mode === "task" ? "Task agent" : "Chat agent"} · ${state}`, "Click to chat"];',
              '      return [a.label, `${a.mode === "task" ? "Task agent" : "Chat agent"} · ${state}`, "Click to chat, right-click for more"];',
              "office agent tooltip")
office = swap(office, '    if (hit.kind === "agent") onPick(hit.name);\n    else if (hit.kind === "door")',
              '    if (hit.kind === "agent") onPick(hit.name);\n    else if (hit.kind === "guide") onGuide();\n    else if (hit.kind === "door")', "office click")
office = swap(office, 'view.style.cursor = hit && (hit.kind === "agent" || hit.kind === "door") ? "pointer" : "default";',
              'view.style.cursor = hit && (hit.kind === "agent" || hit.kind === "door" || hit.kind === "guide") ? "pointer" : "default";', "office cursor")
office = swap(office, "  let onPick = () => {};", "  let onPick = () => {};\n  let onGuide = () => {};\n  let onMenu = () => {};", "office callbacks")
office = swap(office, "    onPick = options.onPick || onPick;",
              "    onPick = options.onPick || onPick;\n    onGuide = options.onGuide || onGuide;\n    onMenu = options.onMenu || onMenu;", "office options")
office = swap(office, '    view.addEventListener("click", (event) => activate(hitTest(toLogical(event))));',
              '    view.addEventListener("click", (event) => activate(hitTest(toLogical(event))));\n'
              '    view.addEventListener("contextmenu", (event) => {\n'
              '      const hit = hitTest(toLogical(event));\n'
              '      if (hit && hit.kind === "agent") {\n'
              '        event.preventDefault();\n'
              '        onMenu(hit.name, event.clientX, event.clientY);\n'
              '      }\n'
              '    });', "office context menu")
office = swap(office, '''    } else if ((event.key === "Enter" || event.key === " ") && focusName) {
      event.preventDefault();
      onPick(focusName);
    }
  }''', '''    } else if ((event.key === "Enter" || event.key === " ") && focusName) {
      event.preventDefault();
      onPick(focusName);
    } else if ((event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) && focusName) {
      event.preventDefault();
      const r = view.getBoundingClientRect();
      const { cx, y0 } = cellOf(order.indexOf(focusName));
      onMenu(focusName, r.left + (cx / W) * r.width, r.top + ((y0 + 30) / H) * r.height);
    }
  }''', "office keyboard menu")
office = swap(office, "    walkIn,\n    resize,", "    walkIn,\n    walkOut,\n    portrait,\n    guide: guideApi,\n    resize,", "office api")

# =====================================================================
# static/index.html
# =====================================================================
html = load(STATIC / "index.html")
html = swap(html, '''          <p class="office-hint" id="office-hint">Click an agent at their desk to talk to them.</p>
        </div>''', '''          <p class="office-hint" id="office-hint">Click an agent at their desk to talk to them. Right-click for more.</p>
          <div class="nova-card" id="nova-card" role="dialog" aria-labelledby="nova-title" hidden>
            <div class="avatar" aria-hidden="true"><canvas id="nova-portrait"></canvas></div>
            <div class="nova-body">
              <h3 id="nova-title">Nova <span>front desk</span></h3>
              <p id="nova-text"></p>
              <div class="nova-actions" id="nova-actions"></div>
            </div>
            <button type="button" class="btn-quiet" id="nova-close" aria-label="Close this and skip the intro" title="Close (Esc)">&#10005;</button>
          </div>
        </div>''', "html card")
html = swap(html, '        <p class="sr-only" id="office-live" aria-live="polite"></p>',
            '        <p class="sr-only" id="office-live" aria-live="polite"></p>\n        <p class="sr-only" id="nova-sr" aria-live="polite"></p>', "html live region")
html = swap(html, "        </dl>\n      </header>",
            '        </dl>\n        <button type="button" class="btn-secondary nova-btn" id="nova-btn" title="Chat with the front-desk guide">Talk to Nova</button>\n      </header>', "html button")
html = swap(html, '''              <button type="button" class="btn-secondary" id="close-chat" title="Close the chat and look at the whole office">Close</button>''',
            '''              <button type="button" class="btn-danger" id="remove-btn" title="Remove this agent. Its spec file goes to the Trash.">Remove</button>
              <button type="button" class="btn-secondary" id="close-chat" title="Close the chat and look at the whole office">Close</button>''',
            "html remove button")
html = swap(html, '  <script src="/static/office.js"></script>', '''  <div class="menu" id="desk-menu" role="menu" hidden></div>

  <dialog class="dialog" id="remove-dialog" aria-labelledby="remove-title">
    <form id="remove-form" method="dialog">
      <h2 id="remove-title"></h2>
      <p id="remove-text"></p>
      <label class="check" id="remove-notes-row"><input type="checkbox" id="remove-notes"> Also move its saved notes to the Trash</label>
      <p class="dialog-error" id="remove-error" role="alert" hidden></p>
      <div class="dialog-actions">
        <button type="button" class="btn-secondary" id="remove-cancel" autofocus>Cancel</button>
        <button type="submit" class="btn-danger" id="remove-confirm">Move to Trash</button>
      </div>
    </form>
  </dialog>

  <script src="/static/office.js"></script>
  <script src="/static/nova.js"></script>''', "html dialog and scripts")

# =====================================================================
# static/style.css
# =====================================================================
css = load(STATIC / "style.css")
css = swap(css, ".office-stage canvas { position: absolute;", ".office-stage > canvas { position: absolute;", "css office canvas scope")
css = swap(css, ".office-stage canvas:focus-visible", ".office-stage > canvas:focus-visible", "css office canvas focus scope")
css = swap(css, ".col-main.has-chat .office-hint { display: none; }\n", '''.col-main.has-chat .office-hint { display: none; }
.office-stage.nova-open .office-hint { display: none; }

.nova-btn { width: 100%; margin-top: 0.85rem; }
.nova-card {
  --accent: #2ec4a0;
  position: absolute; left: 50%; bottom: 0.9rem; transform: translateX(-50%); z-index: 4;
  width: min(38rem, calc(100% - 1.8rem)); display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 0.85rem; align-items: start;
  padding: 0.9rem 1rem; background: var(--panel); border: 1px solid var(--accent); border-radius: 12px; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.55);
}
.nova-card .avatar { width: 3.4rem; height: 3.4rem; }
.nova-body h3 { font-size: var(--t-base); color: var(--accent); }
.nova-body h3 span { margin-left: 0.4rem; color: var(--ink-2); font-size: var(--t-xs); font-weight: 500; }
.nova-body p { margin: 0.3rem 0 0.8rem; min-height: 2.9em; font-size: var(--t-md); line-height: 1.45; overflow-wrap: anywhere; }
.nova-actions { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.nova-actions:empty { display: none; }

/* pixel portraits */
.avatar { padding: 3px; overflow: hidden; }
.avatar canvas { display: block; width: 100%; height: 100%; image-rendering: pixelated; }

/* removing an agent */
.btn-danger {
  display: inline-flex; align-items: center; justify-content: center; min-height: 2.1rem; padding: 0 0.85rem;
  border: 1px solid var(--high); border-radius: 8px; background: var(--high-tint); color: var(--high);
  font-size: var(--t-sm); font-weight: 700;
}
.btn-danger:not(:disabled):hover { background: var(--high); color: #12122a; }

.dialog {
  width: min(28rem, calc(100% - 2rem)); padding: 1.2rem 1.3rem; color: var(--ink);
  background: var(--panel-raised); border: 1px solid var(--border); border-radius: 12px; box-shadow: 0 16px 50px rgba(0, 0, 0, 0.6);
}
.dialog::backdrop { background: rgba(8, 8, 20, 0.72); }
.dialog h2 { font-size: var(--t-lg); margin-bottom: 0.5rem; }
.dialog p { margin: 0 0 0.9rem; color: var(--ink-2); overflow-wrap: anywhere; }
.dialog .check { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.9rem; }
.dialog-error { color: var(--high); background: var(--high-tint); border-radius: 6px; padding: 0.4rem 0.6rem; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 0.6rem; }

.menu {
  position: fixed; z-index: 20; min-width: 12rem; display: grid; padding: 0.3rem;
  background: var(--panel-raised); border: 1px solid var(--border); border-radius: 10px; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
}
.menu button { border: 0; background: none; color: var(--ink); text-align: left; padding: 0.45rem 0.7rem; border-radius: 6px; font-size: var(--t-sm); }
.menu button:hover, .menu button:focus-visible { background: var(--panel); }
.menu button.danger { color: var(--high); }
''', "css additions")

# =====================================================================
# static/app.js
# =====================================================================
js = load(STATIC / "app.js")

js = swap(js, "    chats: new Map(), // agent name -> chat object\n  };",
          "    chats: new Map(), // agent name -> chat object\n"
          "    known: null, // names seen on the last load, so arrivals and departures can be shown\n"
          "    signature: \"\",\n"
          "    seats: loadSeats(), // desk order: everyone keeps their desk, newcomers take the next free one\n"
          "    leaving: new Map(), // agents on their way out: name -> last known summary\n"
          "  };", "js state")
js = swap(js, "  // ---------- small helpers ----------\n",
          "  // Desk order is remembered between visits (this browser only).\n"
          "  function loadSeats() {\n"
          "    try {\n"
          "      const saved = JSON.parse(localStorage.getItem(\"agentfactory.seats\") || \"[]\");\n"
          "      return Array.isArray(saved) ? saved.filter((n) => typeof n === \"string\") : [];\n"
          "    } catch { return []; }\n"
          "  }\n"
          "  function saveSeats(seats) {\n"
          "    try { localStorage.setItem(\"agentfactory.seats\", JSON.stringify(seats)); } catch { /* not saved, no harm */ }\n"
          "  }\n\n"
          "  // ---------- small helpers ----------\n", "js seat storage")

js = swap(js, '''  function avatar(name, id) {
    return el("div", { class: "avatar", "aria-hidden": "true", id, style: accent(name), text: name[0].toUpperCase() });
  }''', '''  function avatar(name, id) {
    const picture = document.createElement("canvas");
    Office.portrait(picture, { name, color: colorOf(name) });
    return el("div", { class: "avatar", "aria-hidden": "true", id, style: accent(name) }, picture);
  }''', "js avatar")

js = swap(js, "    Office.setAgents(state.agents.map((a) => ({",
          "    const pool = [...state.agents, ...state.leaving.values()];\n"
          "    const names = pool.map((a) => a.name);\n"
          "    state.seats = [...state.seats.filter((n) => names.includes(n)), ...names.filter((n) => !state.seats.includes(n))];\n"
          "    saveSeats(state.seats);\n"
          "    const byName = new Map(pool.map((a) => [a.name, a]));\n"
          "    Office.setAgents(state.seats.map((n) => byName.get(n)).map((a) => ({", "js seats")

js = swap(js, '''    state.agents = data.agents;
    if (state.current && !currentAgent()) deselect();
    renderRoster();
    renderProblems(data.problems);
    if (state.current) renderHeader(currentAgent());
  }''', '''    const signature = JSON.stringify(data);
    if (signature === state.signature) return; // nothing changed, so leave the page alone
    state.signature = signature;
    const previous = new Map(state.agents.map((a) => [a.name, a]));
    const before = state.known;
    state.known = new Set(data.agents.map((a) => a.name));
    const gone = before ? [...before].filter((n) => !state.known.has(n) && !state.leaving.has(n) && previous.has(n)) : [];
    for (const name of gone) {
      state.leaving.set(name, previous.get(name));
      const chat = state.chats.get(name);
      if (chat) {
        const ws = chat.ws;
        chat.ws = null;
        if (ws) ws.close();
        chat.view.remove();
        state.chats.delete(name);
      }
    }
    state.agents = data.agents;
    if (state.current && !currentAgent()) deselect();
    renderRoster();
    renderProblems(data.problems);
    if (state.current) renderHeader(currentAgent());
    for (const name of gone) {
      Office.say(name, "Bye!", 2);
      Office.walkOut(name, "staff", () => { state.leaving.delete(name); syncOffice(); });
    }
    if (before) {
      for (const a of data.agents) {
        if (!before.has(a.name)) Office.walkIn(a.name, "staff", () => Office.say(a.name, `Hi, I'm ${pretty(a.name)}!`, 5));
      }
    }
  }''', "js load agents")

js = swap(js, "  // ---------- wiring ----------\n", '''  // ---------- removing an agent ----------

  const removeDialog = $("remove-dialog");
  const deskMenu = $("desk-menu");
  let removing = null;

  function askRemove(name) {
    const agent = state.agents.find((a) => a.name === name);
    if (!agent) return;
    const chat = state.chats.get(name);
    if (chat && chat.busy) {
      addSystem(chat, "Wait until the agent has finished before removing it.", "warn");
      return;
    }
    removing = name;
    $("remove-title").textContent = `Remove ${pretty(name)}?`;
    $("remove-text").textContent = `Its spec file (specs/${agent.file || `${name}.yaml`}) will be moved to the Trash, ` +
      "so you can put it back from there. The conversation on screen is not saved.";
    $("remove-notes-row").hidden = !agent.has_notes;
    $("remove-notes").checked = false;
    $("remove-error").hidden = true;
    $("remove-confirm").disabled = false;
    $("remove-confirm").textContent = "Move to Trash";
    removeDialog.showModal();
  }

  async function confirmRemove(event) {
    event.preventDefault();
    const name = removing;
    if (!name) return;
    const button = $("remove-confirm");
    button.disabled = true;
    button.textContent = "Moving...";
    try {
      const url = `/api/agents/${encodeURIComponent(name)}?notes=${$("remove-notes").checked ? "true" : "false"}`;
      const response = await fetch(url, { method: "DELETE", headers: { "X-AgentFactory": "1" } });
      if (!response.ok) {
        let detail = "";
        try { detail = (await response.json()).detail; } catch { /* no details */ }
        throw new Error(detail || `The server answered ${response.status}.`);
      }
      removeDialog.close();
      if (state.current === name) deselect();
      await loadAgents();
    } catch (error) {
      $("remove-error").textContent = error.message;
      $("remove-error").hidden = false;
      button.disabled = false;
      button.textContent = "Try again";
    }
  }

  function hideMenu() {
    deskMenu.hidden = true;
  }

  function showDeskMenu(name, x, y) {
    deskMenu.replaceChildren(
      el("button", { type: "button", role: "menuitem", text: `Open ${pretty(name)}`, onclick: () => { hideMenu(); selectAgent(name); } }),
      el("button", { type: "button", role: "menuitem", class: "danger", text: "Remove agent...", onclick: () => { hideMenu(); askRemove(name); } }));
    deskMenu.hidden = false;
    deskMenu.style.left = `${Math.max(8, Math.min(x, window.innerWidth - deskMenu.offsetWidth - 8))}px`;
    deskMenu.style.top = `${Math.max(8, Math.min(y, window.innerHeight - deskMenu.offsetHeight - 8))}px`;
    deskMenu.firstElementChild.focus();
  }

  // ---------- wiring ----------
''', "js remove code")

js = swap(js, '''  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeNotes(); });''',
          '''  document.addEventListener("keydown", (event) => { if (event.key === "Escape") { closeNotes(); hideMenu(); } });
  document.addEventListener("pointerdown", (event) => { if (!deskMenu.hidden && !deskMenu.contains(event.target)) hideMenu(); });
  deskMenu.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const items = [...deskMenu.querySelectorAll("button")];
    const next = items.indexOf(document.activeElement) + (event.key === "ArrowDown" ? 1 : -1);
    items[(next + items.length) % items.length].focus();
  });
  $("remove-btn").addEventListener("click", () => { if (state.current) askRemove(state.current); });
  $("remove-form").addEventListener("submit", confirmRemove);
  $("remove-cancel").addEventListener("click", () => removeDialog.close());
  removeDialog.addEventListener("close", () => { removing = null; });''', "js remove wiring")
js = swap(js, '  window.addEventListener("focus", loadConfig);', '  window.addEventListener("focus", () => { loadConfig(); loadAgents(); });', "js focus")
js = swap(js, '''    onPick: selectAgent,
  });
  loadConfig();
  loadAgents();
})();''', '''    onPick: selectAgent,
    onGuide: () => Nova.menu(),
    onMenu: showDeskMenu,
  });
  loadConfig();
  loadAgents().then(() => Nova.boot());
  setInterval(() => { if (!document.hidden) loadAgents(); }, 8000); // new or removed spec files show up on their own
})();''', "js start")

js = swap(js, """        onblur: () => Office.highlight(null),
      },""", """        onblur: () => Office.highlight(null),
        oncontextmenu: (event) => { event.preventDefault(); showDeskMenu(agent.name, event.clientX, event.clientY); },
      },""", "js roster context menu")

# =====================================================================
if problems:
    print("Nothing was changed. These pieces did not match:")
    for p in problems:
        print("  -", p)
    raise SystemExit(1)

for path, content in ((SERVER, server), (STATIC / "office.js", office), (STATIC / "index.html", html),
                      (STATIC / "style.css", css), (STATIC / "app.js", js)):
    path.write_text(content, encoding="utf-8")
print("Done: server.py, office.js, index.html, style.css and app.js updated.")
