"""U2 upgrade: puts the office on the page. Edits index.html, style.css and app.js together,
or none of them if anything unexpected is found."""
from pathlib import Path

STATIC = Path("static")
problems = []


def load(name):
    return (STATIC / name).read_text(encoding="utf-8")


def swap(text, old, new, label):
    if text.count(old) != 1:
        problems.append(f"{label}: expected piece not found exactly once")
        return text
    return text.replace(old, new)


# ---------- index.html ----------
html = load("index.html")
start = html.find('    <main class="col col-main">')
end = html.find('    <aside class="col col-right">')
if start < 0 or end < 0 or end < start:
    problems.append("index.html: could not find the main column")
else:
    html = html[:start] + '''    <main class="col col-main" id="col-main">
      <section class="panel office-panel" aria-label="Office">
        <div class="office-stage" id="office-stage">
          <canvas id="office" tabindex="0" role="application"
            aria-label="The office. Use the arrow keys to move between agents and press Enter to open a chat."></canvas>
          <div class="office-tip" id="office-tip" hidden></div>
          <p class="office-hint" id="office-hint">Click an agent at their desk to talk to them.</p>
        </div>
        <p class="sr-only" id="office-live" aria-live="polite"></p>
      </section>

      <section class="panel chat" id="chat-section" aria-label="Chat" hidden>
        <div class="chat-live" id="chat-live">
          <header class="chat-head">
            <div class="avatar" id="chat-avatar" aria-hidden="true"></div>
            <div class="chat-title">
              <h2 id="chat-name"></h2>
              <p id="chat-sub"></p>
            </div>
            <div class="chat-actions">
              <button type="button" class="btn-secondary" id="notes-btn" aria-expanded="false" aria-controls="notes-drawer">Notes</button>
              <button type="button" class="btn-secondary" id="new-chat-btn" title="Forget this conversation and start again">New chat</button>
              <button type="button" class="btn-secondary" id="close-chat" title="Close the chat and look at the whole office">Close</button>
            </div>
          </header>
          <div class="chips" id="chat-chips"></div>
          <div class="notes-drawer" id="notes-drawer" hidden>
            <h3>Saved notes</h3>
            <pre id="notes-text"></pre>
          </div>
          <div class="messages-wrap" id="messages-wrap"></div>
          <form class="composer" id="composer">
            <label class="sr-only" for="composer-input">Message</label>
            <textarea id="composer-input" rows="1" placeholder="Write a message. Enter sends, Shift+Enter adds a new line."></textarea>
            <button type="submit" class="btn-primary" id="send-btn">Send</button>
          </form>
        </div>
      </section>
    </main>

''' + html[end:]
    html = swap(html, '  <script src="/static/app.js"></script>',
                '  <script src="/static/office.js"></script>\n  <script src="/static/app.js"></script>', "index.html script tag")

# ---------- style.css ----------
css = load("style.css")
css = swap(css, ".chat-empty { margin: auto; text-align: center; padding: 2rem; color: var(--ink-2); }\n"
                ".chat-empty h2 { color: var(--ink); font-size: var(--t-lg); margin-bottom: 0.4rem; }\n", "", "css chat-empty")
css = swap(css, ".chat { flex: 1; min-height: 0; display: flex; flex-direction: column; padding: 0; overflow: hidden; }",
           ".chat { flex: 1 1 0; min-height: 16rem; display: flex; flex-direction: column; padding: 0; overflow: hidden; }", "css chat")
office_css = '''/* ---------- office ---------- */

.office-panel { flex: 1 1 0; min-height: 14rem; padding: 0; position: relative; overflow: hidden; transition: flex-basis 0.25s ease; }
.col-main.has-chat .office-panel { flex: 0 0 42%; }
.office-stage { position: absolute; inset: 0; }
.office-stage canvas { position: absolute; inset: 0; margin: auto; display: block; border-radius: 6px; }
.office-stage canvas:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
.office-tip {
  position: absolute; left: 0; top: 0; z-index: 3; pointer-events: none; display: grid; gap: 0.1rem;
  max-width: 17rem; padding: 0.4rem 0.65rem; background: var(--panel-raised); border: 1px solid var(--border);
  border-radius: 8px; font-size: var(--t-xs); color: var(--ink-2); box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
}
.office-tip strong { color: var(--ink); font-size: var(--t-sm); }
.office-hint {
  position: absolute; left: 0.9rem; bottom: 0.6rem; margin: 0; z-index: 2; pointer-events: none;
  color: var(--ink-2); font-size: var(--t-xs); background: rgba(16, 16, 36, 0.8); padding: 0.15rem 0.55rem; border-radius: 999px;
}
.col-main.has-chat .office-hint { display: none; }

'''
css = swap(css, "/* ---------- chat ---------- */", office_css + "/* ---------- chat ---------- */", "css chat heading")
css = swap(css, "  .chat { min-height: 34rem; height: 70vh; }",
           "  .office-panel, .col-main.has-chat .office-panel { flex: none; height: 24rem; }\n"
           "  .chat { min-height: 34rem; height: 70vh; flex: none; }", "css small screens")

# ---------- app.js ----------
js = load("app.js")
js = swap(js, '''        onclick: () => selectAgent(agent.name),
      },''', '''        onclick: () => selectAgent(agent.name),
        onmouseenter: () => Office.highlight(agent.name),
        onmouseleave: () => Office.highlight(null),
        onfocus: () => Office.highlight(agent.name),
        onblur: () => Office.highlight(null),
      },''', "js roster hover")
js = swap(js, '''  function renderRoster() {
    const list = $("roster");''', '''  function syncOffice() {
    Office.setAgents(state.agents.map((a) => ({
      name: a.name,
      label: pretty(a.name),
      color: colorOf(a.name),
      mode: a.mode,
      runnable: a.runnable,
      status: (state.chats.get(a.name) || {}).status || "idle",
    })));
    Office.select(state.current);
  }

  function renderRoster() {
    syncOffice();
    const list = $("roster");''', "js syncOffice")
js = swap(js, '''      dot.title = STATUS_LABELS[chat.status];
    }
  }''', '''      dot.title = STATUS_LABELS[chat.status];
    }
    Office.setStatus(chat.agent, chat.status);
  }''', "js status")
js = swap(js, '''        chat.status = "queued";
        setTyping(chat, "Waiting for the model. Another agent is using it.");''', '''        chat.status = "queued";
        Office.say(chat.agent, "Waiting for the model...", 600);
        setTyping(chat, "Waiting for the model. Another agent is using it.");''', "js queued")
js = swap(js, '''        chat.status = "working";
        setTyping(chat, "Thinking...");
        refreshStatus(chat);
        break;''', '''        chat.status = "working";
        Office.say(chat.agent, "Thinking...", 600);
        setTyping(chat, "Thinking...");
        refreshStatus(chat);
        break;''', "js started")
js = swap(js, '''        if (payload.event === "tool") setTyping(chat, `Using ${payload.name}...`);
        else if (payload.event === "nudge") setTyping(chat, "Double-checking its answer...");
        else if (chat.busy) setTyping(chat, "Thinking...");''', '''        if (payload.event === "tool") { setTyping(chat, `Using ${payload.name}...`); Office.say(chat.agent, `Using ${payload.name}`, 600); }
        else if (payload.event === "nudge") { setTyping(chat, "Double-checking its answer..."); Office.say(chat.agent, "Double-checking...", 600); }
        else if (chat.busy) setTyping(chat, "Thinking...");''', "js trace")
js = swap(js, '''        endTurn(chat);
        addReply(chat, payload);
        break;''', '''        endTurn(chat);
        addReply(chat, payload);
        Office.say(chat.agent, payload.ok ? "Done!" : "Stopped early", 3);
        break;''', "js reply")
js = swap(js, '''        if (chat.busy) endTurn(chat);
        addSystem(chat, payload.message || "Something went wrong.", "error");''', '''        if (chat.busy) endTurn(chat);
        Office.say(chat.agent, "Something went wrong", 4);
        addSystem(chat, payload.message || "Something went wrong.", "error");''', "js error")
js = swap(js, '''    $("chat-empty").hidden = true;
    $("chat-live").hidden = false;
    closeNotes();''', '''    $("chat-section").hidden = false;
    $("col-main").classList.add("has-chat");
    closeNotes();''', "js select")
js = swap(js, '''  function deselect() {
    state.current = null;
    $("chat-live").hidden = true;
    $("chat-empty").hidden = false;
  }''', '''  function deselect() {
    const previous = currentChat();
    if (previous) previous.draft = $("composer-input").value;
    state.current = null;
    $("chat-section").hidden = true;
    $("col-main").classList.remove("has-chat");
    Office.select(null);
    renderRoster();
    updateComposer();
  }''', "js deselect")
js = swap(js, '''  $("clear-log").addEventListener("click", clearLog);''', '''  $("clear-log").addEventListener("click", clearLog);
  $("close-chat").addEventListener("click", () => { closeNotes(); deselect(); $("office").focus(); });''', "js close button")
js = swap(js, '''  loadConfig();
  loadAgents();
})();''', '''  Office.init({
    canvas: $("office"),
    tip: $("office-tip"),
    live: $("office-live"),
    onPick: selectAgent,
  });
  loadConfig();
  loadAgents();
})();''', "js start")

if problems:
    print("Nothing was changed. These pieces did not match:")
    for p in problems:
        print("  -", p)
    raise SystemExit(1)

(STATIC / "index.html").write_text(html, encoding="utf-8")
(STATIC / "style.css").write_text(css, encoding="utf-8")
(STATIC / "app.js").write_text(js, encoding="utf-8")
print("Done: index.html, style.css and app.js updated.")
