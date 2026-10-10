"""Upgrade AgentFactory to U6: staff file, search (Ctrl+K), tooltips and small screens. Run once from the project folder: python upgrade_u6.py

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

factory_server_py = read("factory/server.py")
factory_server_py = swap(factory_server_py, r'''    return {"name": spec.name, "notes": text}
''', r'''    return {"name": spec.name, "notes": text}


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
''', "factory/server.py #1")

texts["factory/server.py"] = factory_server_py

static_index_html = read("static/index.html")
static_index_html = swap(static_index_html, r'''        </dl>
        <button type="button" class="btn-secondary nova-btn" id="nova-btn" title="Chat with the front-desk guide">Talk to Nova</button>
      </header>''', r'''        </dl>
        <div class="brand-actions">
          <button type="button" class="btn-secondary nova-btn" id="nova-btn" title="Chat with the front-desk guide">Talk to Nova</button>
          <button type="button" class="btn-secondary" id="palette-btn" title="Search for an agent or an action and jump to it">Search <kbd class="kbd-hint">Ctrl K</kbd></button>
        </div>
      </header>''', "static/index.html #1")

static_index_html = swap(static_index_html, r'''            <div class="chat-actions">
              <button type="button" class="btn-secondary" id="notes-btn" aria-expanded="false" aria-controls="notes-drawer">Notes</button>''', r'''            <div class="chat-actions">
              <button type="button" class="btn-secondary" id="staff-btn" title="See this agent's file: instructions, permissions and limits">Staff file</button>
              <button type="button" class="btn-secondary" id="notes-btn" aria-expanded="false" aria-controls="notes-drawer">Notes</button>''', "static/index.html #2")

static_index_html = swap(static_index_html, r'''            <textarea id="composer-input" rows="1" placeholder="Write a message. Enter sends, Shift+Enter adds a new line."></textarea>
            <button type="submit" class="btn-primary" id="send-btn">Send</button>
          </form>''', r'''            <textarea id="composer-input" rows="1" placeholder="Write a message. Enter sends, Shift+Enter adds a new line."></textarea>
            <button type="submit" class="btn-primary" id="send-btn" title="Send the message (Enter)">Send</button>
          </form>''', "static/index.html #3")

static_index_html = swap(static_index_html, r'''          <h2 id="log-title">Activity</h2>
          <button type="button" class="btn-quiet" id="clear-log">Clear</button>
        </div>''', r'''          <h2 id="log-title">Activity</h2>
          <button type="button" class="btn-quiet" id="clear-log" title="Remove every row from the activity log">Clear</button>
        </div>''', "static/index.html #4")

static_index_html = swap(static_index_html, r'''  <script src="/static/office.js"></script>
  <script src="/static/hire.js"></script>
  <script src="/static/nova.js"></script>''', r'''  <script src="/static/office.js"></script>
  <dialog class="dialog dialog-wide" id="staff-dialog" aria-labelledby="staff-title">
    <form id="staff-form" method="dialog" onsubmit="return false">
      <header class="hire-head">
        <div class="avatar" aria-hidden="true" id="staff-avatar"></div>
        <div class="hire-head-text">
          <h2 id="staff-title"></h2>
          <p id="staff-sub"></p>
        </div>
        <button type="button" class="btn-quiet" id="staff-x" aria-label="Close" title="Close (Esc)">&#10005;</button>
      </header>
      <div class="hire-body" id="staff-body"></div>
      <div class="dialog-actions">
        <button type="button" class="btn-danger" id="staff-remove" title="Move this agent's file to the Trash">Remove...</button>
        <span class="spacer"></span>
        <button type="button" class="btn-primary" id="staff-chat">Open chat</button>
      </div>
    </form>
  </dialog>

  <dialog class="dialog palette" id="palette-dialog" aria-label="Search">
    <input type="text" id="palette-input" role="combobox" aria-expanded="true" aria-controls="palette-list" aria-autocomplete="list"
      placeholder="Type an agent's name or an action..." autocomplete="off" spellcheck="false">
    <ul id="palette-list" role="listbox" aria-label="Results"></ul>
    <p class="palette-foot">Up and down to move, Enter to choose, Esc to close</p>
  </dialog>

  <script src="/static/hire.js"></script>
  <script src="/static/staff.js"></script>
  <script src="/static/palette.js"></script>
  <script src="/static/nova.js"></script>''', "static/index.html #5")

texts["static/index.html"] = static_index_html

static_style_css = read("static/style.css")
static_style_css = swap(static_style_css, r'''
.nova-btn { width: 100%; margin-top: 0.85rem; }
.nova-card {''', r'''
.nova-btn { width: 100%; }
.nova-card {''', "static/style.css #1")

static_style_css = swap(static_style_css, r'''
.chat-head { display: flex; align-items: center; gap: 0.8rem; padding: 0.9rem 1.1rem; border-bottom: 1px solid var(--rule); }
.chat-title { flex: 1; min-width: 0; }
.chat-title h2 { font-size: var(--t-md); color: var(--accent); }''', r'''
.chat-head { display: flex; flex-wrap: wrap; align-items: center; gap: 0.6rem 0.8rem; padding: 0.9rem 1.1rem; border-bottom: 1px solid var(--rule); }
.chat-title { flex: 1 1 9rem; min-width: 0; }
.chat-title h2 { font-size: var(--t-md); color: var(--accent); }''', "static/style.css #2")

static_style_css = swap(static_style_css, r'''.chat-title p { margin: 0; color: var(--ink-2); font-size: var(--t-xs); }
.chat-actions { display: flex; gap: 0.5rem; }
''', r'''.chat-title p { margin: 0; color: var(--ink-2); font-size: var(--t-xs); }
.chat-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 0.5rem; }
.chat-actions button { white-space: nowrap; }
''', "static/style.css #3")

static_style_css = swap(static_style_css, r'''
/* ---------- smaller screens ---------- */''', r'''
/* ---------- staff file, search ---------- */

.brand-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; margin-top: 0.85rem; }
.brand-actions .btn-secondary { width: 100%; margin: 0; white-space: nowrap; }
kbd { font: 600 var(--t-xs) var(--mono); padding: 0.05rem 0.35rem; margin-left: 0.3rem; color: var(--ink-2); border: 1px solid var(--rule); border-radius: 4px; }
.staff-text { margin: 0 0 0.5rem; overflow-wrap: anywhere; white-space: pre-wrap; }
.staff-pre { margin: 0; padding: 0.7rem; max-height: 12rem; overflow: auto; background: var(--bg); border: 1px solid var(--rule); border-radius: 8px; white-space: pre-wrap; overflow-wrap: anywhere; }
.hire-body .chips { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-bottom: 0.5rem; }
#staff-form { display: flex; flex-direction: column; max-height: calc(100dvh - 2rem); }
.palette { width: min(36rem, calc(100% - 2rem)); margin-top: 12vh; padding: 0; overflow: hidden; }
.palette input { width: 100%; padding: 0.9rem 1.1rem; color: var(--ink); background: var(--bg); border: 0; border-bottom: 1px solid var(--rule); font: inherit; font-size: var(--t-md); }
.palette input:focus-visible { outline: none; border-bottom-color: var(--accent); }
.palette ul { list-style: none; margin: 0; padding: 0.35rem; max-height: min(24rem, 55vh); overflow-y: auto; }
.palette li { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 0.5rem 0.7rem; border-radius: 8px; cursor: pointer; }
.palette li.is-active { background: color-mix(in srgb, var(--accent) 18%, transparent); }
.palette-main { display: grid; min-width: 0; }
.palette-main small { color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.palette-group { flex-shrink: 0; color: var(--ink-2); font-size: var(--t-xs); text-transform: uppercase; letter-spacing: 0.06em; }
.palette li.palette-empty { color: var(--ink-2); cursor: default; justify-content: center; }
.palette-foot { margin: 0; padding: 0.45rem 1rem; color: var(--ink-2); font-size: var(--t-xs); border-top: 1px solid var(--rule); }

/* ---------- smaller screens ---------- */''', "static/style.css #4")

static_style_css = swap(static_style_css, r'''  .app { grid-template-columns: minmax(0, 1fr); height: auto; min-height: 100dvh; }
  .col-left { max-height: 26rem; }
  .office-panel, .col-main.has-chat .office-panel { flex: none; height: 24rem; }''', r'''  .app { grid-template-columns: minmax(0, 1fr); height: auto; min-height: 100dvh; }
  .col-left { max-height: none; }
  .roster-panel { flex: none; }
  .roster { max-height: 22rem; }
  .office-panel, .col-main.has-chat .office-panel { flex: none; height: 24rem; }''', "static/style.css #5")

texts["static/style.css"] = static_style_css

static_app_js = read("static/app.js")
static_app_js = swap(static_app_js, r'''    chat.starters = el("div", { class: "starters" }, prompts.map((text) =>
      el("button", { type: "button", class: "starter", text, onclick: () => sendMessage(chat, text) })));
    chat.view.append(chat.starters);''', r'''    chat.starters = el("div", { class: "starters" }, prompts.map((text) =>
      el("button", { type: "button", class: "starter", text, title: "Send this as your first message", onclick: () => sendMessage(chat, text) })));
    chat.view.append(chat.starters);''', "static/app.js #1")

static_app_js = swap(static_app_js, r'''        addReply(chat, payload);
        Office.setMeter(chat.agent, payload.tokens || 0, tokenLimit(chat));''', r'''        addReply(chat, payload);
        chat.lastRun = payload;
        Office.setMeter(chat.agent, payload.tokens || 0, tokenLimit(chat));''', "static/app.js #2")

static_app_js = swap(static_app_js, r'''      el("button", { type: "button", role: "menuitem", text: `Open ${pretty(name)}`, onclick: () => { hideMenu(); selectAgent(name); } }),
      el("button", { type: "button", role: "menuitem", class: "danger", text: "Remove agent...", onclick: () => { hideMenu(); askRemove(name); } }));''', r'''      el("button", { type: "button", role: "menuitem", text: `Open ${pretty(name)}`, onclick: () => { hideMenu(); selectAgent(name); } }),
      el("button", { type: "button", role: "menuitem", text: "Staff file", onclick: () => { hideMenu(); openStaff(name); } }),
      el("button", { type: "button", role: "menuitem", class: "danger", text: "Remove agent...", onclick: () => { hideMenu(); askRemove(name); } }));''', "static/app.js #3")

static_app_js = swap(static_app_js, r'''    deskMenu.firstElementChild.focus();
  }''', r'''    deskMenu.firstElementChild.focus();
  }

  // ---------- staff file and search ----------

  function openStaff(name) {
    const agent = state.agents.find((a) => a.name === name);
    if (agent) Staff.open(agent, { lastRun: (state.chats.get(name) || {}).lastRun });
  }

  function paletteItems() {
    const items = [
      { group: "Do", label: "Hire a new agent", hint: "Open the hiring form", run: () => Nova.hire() },
      { group: "Do", label: "Talk to Nova", hint: "The front desk", run: () => Nova.menu() },
      { group: "Do", label: "Refresh the agent list", hint: "Look for new or removed agent files", run: () => { loadConfig(); loadAgents(); } },
      { group: "Do", label: "Check Ollama again", run: loadConfig },
      { group: "Do", label: "Clear the activity log", run: clearLog },
    ];
    if (state.current) {
      items.push({ group: "Do", label: "Close the chat", hint: "Back to the whole office", run: deselect });
      items.push({ group: "Do", label: "Start a new chat", hint: `Forget the conversation with ${pretty(state.current)}`, run: newChat });
    }
    for (const a of state.agents) {
      items.push({ group: "Agent", label: `Chat with ${pretty(a.name)}`, hint: a.goal, run: () => selectAgent(a.name) });
      items.push({ group: "Staff file", label: `Staff file: ${pretty(a.name)}`, hint: "Instructions, permissions, limits", run: () => openStaff(a.name) });
      items.push({ group: "Remove", label: `Remove ${pretty(a.name)}...`, hint: "Moves the agent's file to the Trash", run: () => askRemove(a.name) });
    }
    return items;
  }''', "static/app.js #4")

static_app_js = swap(static_app_js, r'''  $("notes-btn").addEventListener("click", toggleNotes);
  $("new-chat-btn").addEventListener("click", newChat);''', r'''  $("notes-btn").addEventListener("click", toggleNotes);
  $("staff-btn").addEventListener("click", () => { if (state.current) openStaff(state.current); });
  $("new-chat-btn").addEventListener("click", newChat);''', "static/app.js #5")

static_app_js = swap(static_app_js, r'''  Hire.init({ colorOf });
  loadConfig();''', r'''  Hire.init({ colorOf });
  Staff.init({
    onChat: selectAgent,
    onRemove: askRemove,
    look: (name) => ({ label: pretty(name), color: colorOf(name), hair: (custom.get(name) || {}).hair || null }),
  });
  Palette.init({ items: paletteItems });
  loadConfig();''', "static/app.js #6")

texts["static/app.js"] = static_app_js

if problems:
    print("Nothing was changed. These pieces did not match:")
    for p in problems:
        print("  -", p)
    raise SystemExit(1)

for rel, content in texts.items():
    (ROOT / rel).write_text(content, encoding="utf-8")
print("Done: server.py, index.html, style.css and app.js updated.")
