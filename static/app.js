"use strict";

// AgentFactory web UI: a roster of agents, a chat for each, and a live activity log.
// Everything the model writes is shown with textContent / DOM nodes, never innerHTML,
// because model output (and the web pages it reads) is untrusted.

(() => {
  const PALETTE = ["#8c7cf6", "#2ec4a0", "#ff7d70", "#fdcb6e", "#4da3ff", "#f78fb3", "#7bd88f", "#ff9f5a"];
  const MAX_LOG_ROWS = 300;
  const STOP_REASONS = {
    max_steps: "step limit",
    max_tokens: "token limit",
    timeout: "time limit",
    loop_detected: "repeated actions",
    error: "error",
  };
  const STATUS_LABELS = { idle: "Idle", working: "Working", queued: "Waiting for the model" };

  const $ = (id) => document.getElementById(id);
  const state = {
    agents: [],
    current: null, // name of the selected agent
    chats: new Map(), // agent name -> chat object
    known: null, // names seen on the last load, so arrivals and departures can be shown
    signature: "",
    seats: loadSeats(), // desk order: everyone keeps their desk, newcomers take the next free one
    leaving: new Map(), // agents on their way out: name -> last known summary
    hired: new Map(), // agents hired in this session: name -> goal, for their introduction
  };

  // Desk order is remembered between visits (this browser only).
  function loadSeats() {
    try {
      const saved = JSON.parse(localStorage.getItem("agentfactory.seats") || "[]");
      return Array.isArray(saved) ? saved.filter((n) => typeof n === "string") : [];
    } catch { return []; }
  }
  function saveSeats(seats) {
    try { localStorage.setItem("agentfactory.seats", JSON.stringify(seats)); } catch { /* not saved, no harm */ }
  }

  // ---------- small helpers ----------

  function el(tag, props = {}, ...kids) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (value === true) node.setAttribute(key, "");
      else if (value !== false && value != null) node.setAttribute(key, value);
    }
    for (const kid of kids.flat()) if (kid != null) node.append(kid);
    return node;
  }

  function hash(text) {
    let h = 0;
    for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return h;
  }
  // Looks chosen in the hiring form (display name, colours), by agent name.
  const custom = new Map();
  const colorOf = (name) => (custom.get(name) || {}).color || PALETTE[hash(name) % PALETTE.length];
  const pretty = (name) => (custom.get(name) || {}).label ||
    name.split("-").map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w)).join(" ");
  const clip = (text, n) => (text.length > n ? text.slice(0, n - 1) + "…" : text);
  const accent = (name) => `--accent:${colorOf(name)}`;

  async function getJSON(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${url} returned ${response.status}`);
    return response.json();
  }

  function avatar(name, id) {
    const picture = document.createElement("canvas");
    Office.portrait(picture, { name, color: colorOf(name), hair: (custom.get(name) || {}).hair || null });
    return el("div", { class: "avatar", "aria-hidden": "true", id, style: accent(name) }, picture);
  }

  const currentAgent = () => state.agents.find((a) => a.name === state.current) || null;
  const currentChat = () => (state.current ? state.chats.get(state.current) || null : null);

  // ---------- markdown (safe: builds DOM nodes, never HTML strings) ----------

  function inline(text) {
    const out = [];
    for (const token of text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/)) {
      if (!token) continue;
      if (token.length > 4 && token.startsWith("**") && token.endsWith("**")) out.push(el("strong", { text: token.slice(2, -2) }));
      else if (token.length > 2 && token.startsWith("`") && token.endsWith("`")) out.push(el("code", { text: token.slice(1, -1) }));
      else out.push(token);
    }
    return out;
  }

  function codeBlock(raw) {
    let lang = "";
    let body = raw;
    const newline = raw.indexOf("\n");
    if (newline !== -1) {
      const first = raw.slice(0, newline).trim();
      if (/^[\w+#.-]{0,20}$/.test(first)) {
        lang = first;
        body = raw.slice(newline + 1);
      }
    }
    body = body.replace(/\n+$/, "");
    const copy = el("button", { type: "button", class: "btn-copy", text: "Copy" });
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(body);
        copy.textContent = "Copied";
      } catch {
        copy.textContent = "Select and copy";
      }
      setTimeout(() => { copy.textContent = "Copy"; }, 1500);
    });
    return el("div", { class: "code" },
      el("div", { class: "code-head" }, el("span", { text: lang || "code" }), copy),
      el("pre", {}, el("code", { text: body })));
  }

  function textBlocks(part) {
    const blocks = [];
    let paragraph = [];
    let list = null;
    const flushParagraph = () => {
      if (paragraph.length) blocks.push(el("p", {}, inline(paragraph.join("\n"))));
      paragraph = [];
    };
    const flushList = () => {
      if (list) blocks.push(list);
      list = null;
    };
    for (const raw of part.split("\n")) {
      const line = raw.replace(/\s+$/, "");
      let m;
      if (!line.trim()) {
        flushParagraph();
        flushList();
      } else if ((m = line.match(/^#{1,4}\s+(.*)$/))) {
        flushParagraph();
        flushList();
        blocks.push(el("p", { class: "md-h" }, inline(m[1])));
      } else if ((m = line.match(/^\s*[-*]\s+(.*)$/))) {
        flushParagraph();
        if (!list || list.tagName !== "UL") { flushList(); list = el("ul"); }
        list.append(el("li", {}, inline(m[1])));
      } else if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
        flushParagraph();
        if (!list || list.tagName !== "OL") { flushList(); list = el("ol"); }
        list.append(el("li", {}, inline(m[1])));
      } else {
        flushList();
        paragraph.push(line);
      }
    }
    flushParagraph();
    flushList();
    return blocks;
  }

  function renderMarkdown(text) {
    const fragment = document.createDocumentFragment();
    String(text).split("```").forEach((part, i) => {
      if (i % 2 === 1) fragment.append(codeBlock(part));
      else fragment.append(...textBlocks(part));
    });
    return fragment;
  }

  // ---------- runtime status ----------

  async function loadConfig() {
    const pill = $("ollama-pill");
    pill.className = "pill";
    pill.textContent = "Checking...";
    try {
      const config = await getJSON("/api/config");
      Office.setBrain({ online: !!config.ollama_up });
      if (config.ollama_up) {
        pill.textContent = "Connected";
        pill.classList.add("is-ok");
        pill.title = "Click to check again";
        $("model-count").textContent = `${config.models.length} installed`;
      } else {
        pill.textContent = "Not reachable";
        pill.classList.add("is-bad");
        pill.title = "Open the Ollama app, then click here to check again.";
        $("model-count").textContent = "-";
      }
    } catch {
      pill.textContent = "Server error";
      pill.classList.add("is-bad");
      $("model-count").textContent = "-";
    }
  }

  // ---------- roster ----------

  function badge(text, kind, title) {
    return el("span", { class: `badge ${kind || ""}`, text, title });
  }

  function rosterItem(agent) {
    const chat = state.chats.get(agent.name);
    const status = chat ? chat.status : "idle";
    const flags = [badge(agent.mode === "task" ? "Task" : "Chat", "", agent.mode === "task"
      ? "Task agent: every message starts a fresh task" : "Chat agent: remembers the conversation")];
    if (!agent.runnable) flags.push(badge("Needs tools", "warn", `Not built yet: ${agent.missing_tools.join(", ")}`));
    else if (agent.model_installed === false) flags.push(badge("Model missing", "warn", `Run: ollama pull ${agent.model}`));
    const selected = agent.name === state.current;
    return el("li", {},
      el("button", {
        type: "button",
        class: `agent-card${selected ? " is-selected" : ""}${agent.runnable ? "" : " is-disabled"}`,
        style: accent(agent.name),
        "data-name": agent.name,
        "aria-pressed": String(selected),
        title: agent.goal,
        onclick: () => selectAgent(agent.name),
        onmouseenter: () => Office.highlight(agent.name),
        onmouseleave: () => Office.highlight(null),
        onfocus: () => Office.highlight(agent.name),
        onblur: () => Office.highlight(null),
        oncontextmenu: (event) => { event.preventDefault(); showDeskMenu(agent.name, event.clientX, event.clientY); },
      },
      avatar(agent.name),
      el("div", { class: "agent-text" },
        el("div", { class: "agent-name", text: pretty(agent.name) }),
        el("div", { class: "agent-goal", text: agent.goal }),
        el("div", { class: "agent-flags" }, flags)),
      el("span", { class: `status is-${status}`, title: STATUS_LABELS[status] })));
  }

  function syncOffice() {
    const pool = [...state.agents, ...state.leaving.values()];
    const names = pool.map((a) => a.name);
    state.seats = [...state.seats.filter((n) => names.includes(n)), ...names.filter((n) => !state.seats.includes(n))];
    saveSeats(state.seats);
    const byName = new Map(pool.map((a) => [a.name, a]));
    Office.setAgents(state.seats.map((n) => byName.get(n)).map((a) => ({
      name: a.name,
      label: pretty(a.name),
      color: colorOf(a.name),
      hair: (custom.get(a.name) || {}).hair || null,
      model: a.model,
      tools: a.tools,
      mode: a.mode,
      runnable: a.runnable,
      status: (state.chats.get(a.name) || {}).status || "idle",
    })));
    Office.select(state.current);
  }

  function renderRoster() {
    syncOffice();
    const list = $("roster");
    list.replaceChildren(...state.agents.map(rosterItem));
    $("agent-count").textContent = state.agents.length ? String(state.agents.length) : "";
    if (!state.agents.length) {
      list.append(el("li", { class: "log-empty", text: "No agents yet. Press New agent and Nova will help you hire one." }));
    }
  }

  function renderProblems(problems) {
    const box = $("problems");
    box.hidden = !problems.length;
    if (!problems.length) return;
    $("problems-summary").textContent = `${problems.length} spec file${problems.length === 1 ? "" : "s"} could not be loaded`;
    $("problems-list").replaceChildren(...problems.map((p) =>
      el("li", {}, el("code", { text: p.file }), ` ${p.error}`)));
  }

  async function loadAgents() {
    let data;
    try {
      data = await getJSON("/api/agents");
    } catch {
      $("roster").replaceChildren(el("li", { class: "log-empty", text: "Could not reach the server." }));
      return;
    }
    const signature = JSON.stringify(data);
    if (signature === state.signature) return; // nothing changed, so leave the page alone
    state.signature = signature;
    for (const a of data.agents) custom.set(a.name, { label: a.display_name || "", color: a.color || "", hair: a.hair || "" });
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
        if (before.has(a.name)) continue;
        const hired = state.hired.has(a.name);
        Office.walkIn(a.name, "staff", () => {
          Office.say(a.name, `Hi, I'm ${pretty(a.name)}!`, 5);
          if (hired) selectAgent(a.name); // someone you just hired introduces themselves in their chat
        });
      }
    }
  }

  function refreshStatus(chat) {
    const dot = document.querySelector(`.agent-card[data-name="${chat.agent}"] .status`);
    if (dot) {
      dot.className = `status is-${chat.status}`;
      dot.title = STATUS_LABELS[chat.status];
    }
    Office.setStatus(chat.agent, chat.status);
  }

  // ---------- chat ----------

  function makeChat(agent) {
    const view = el("div", { class: "messages", "aria-live": "polite", hidden: true });
    $("messages-wrap").append(view);
    return {
      agent: agent.name, view, ws: null, open: false, busy: false, status: "idle",
      outbox: [], typing: null, starters: null, draft: "",
    };
  }

  function addSystem(chat, text, kind) {
    chat.view.append(el("div", { class: `msg system ${kind || ""}`, role: kind === "error" ? "alert" : null, text }));
    scrollDown(chat);
  }

  function addUser(chat, text) {
    chat.view.append(el("div", { class: "msg user" }, el("p", { text })));
    scrollDown(chat);
  }

  function addReply(chat, p) {
    const meta = [`${p.steps} step${p.steps === 1 ? "" : "s"}`, `${p.tokens} tokens`, `${p.seconds}s`];
    if (!p.ok) meta.push(`stopped: ${STOP_REASONS[p.stop_reason] || p.stop_reason}`);
    chat.view.append(el("div", { class: `msg agent${p.ok ? "" : " warn"}` },
      el("div", { class: "msg-body" }, renderMarkdown(p.text || "(no reply)")),
      el("div", { class: `msg-meta${p.ok ? "" : " warn"}`, text: meta.join(" · ") })));
    scrollDown(chat);
  }

  function setTyping(chat, label) {
    if (!chat.typing) {
      chat.typing = el("div", { class: "msg typing" },
        el("span", { class: "dots", "aria-hidden": "true" }, el("i"), el("i"), el("i")),
        el("span", { class: "typing-label" }));
      chat.view.append(chat.typing);
    }
    chat.typing.querySelector(".typing-label").textContent = label;
    chat.view.append(chat.typing); // keep it last
    scrollDown(chat);
  }

  function clearTyping(chat) {
    if (chat.typing) chat.typing.remove();
    chat.typing = null;
  }

  function scrollDown(chat) {
    requestAnimationFrame(() => { chat.view.scrollTop = chat.view.scrollHeight; });
  }

  function showWelcome(chat, agent) {
    if (state.hired.has(agent.name)) {
      addSystem(chat, `Hi, I'm ${pretty(agent.name)}. My job: ${state.hired.get(agent.name)}`);
      state.hired.delete(agent.name);
    }
    addSystem(chat, `${pretty(agent.name)} is at their desk.` +
      (agent.mode === "task" ? " This is a task agent, so every message starts a fresh task." : ""));
    const prompts = ["What can you do?", agent.has_notes ? "Let's continue where we left off." : "Let's get started."];
    chat.starters = el("div", { class: "starters" }, prompts.map((text) =>
      el("button", { type: "button", class: "starter", text, title: "Send this as your first message", onclick: () => sendMessage(chat, text) })));
    chat.view.append(chat.starters);
  }

  function beginTurn(chat) {
    chat.busy = true;
    chat.status = "working";
    chat.runTokens = 0;
    Office.setAlert(chat.agent, "");
    refreshStatus(chat);
    setTyping(chat, "Sending...");
    updateComposer();
  }

  function endTurn(chat) {
    chat.busy = false;
    chat.status = "idle";
    clearTyping(chat);
    refreshStatus(chat);
    updateComposer();
  }

  function connect(chat) {
    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${scheme}//${location.host}/ws/chat/${encodeURIComponent(chat.agent)}`);
    chat.ws = ws;
    chat.open = false;
    ws.addEventListener("open", () => {
      if (chat.ws !== ws) return;
      chat.open = true;
      for (const text of chat.outbox.splice(0)) ws.send(JSON.stringify({ type: "message", text }));
    });
    ws.addEventListener("message", (event) => {
      if (chat.ws !== ws) return;
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }
      onServerEvent(chat, msg);
    });
    ws.addEventListener("close", () => {
      if (chat.ws !== ws) return;
      chat.open = false;
      chat.ws = null; // the next message reconnects
      if (chat.busy) {
        endTurn(chat);
        addSystem(chat, "The connection dropped while the agent was working. Your last message may not have been handled.", "warn");
      }
    });
  }

  // The token meter on the desk counts against the agent's own limit for one run.
  function tokenLimit(chat) {
    const agent = state.agents.find((a) => a.name === chat.agent);
    return agent && agent.limits ? agent.limits.max_tokens : 0;
  }

  function onServerEvent(chat, msg) {
    const payload = msg.payload || {};
    switch (msg.event) {
      case "queued":
        chat.status = "queued";
        Office.say(chat.agent, "Waiting for the model...", 600);
        setTyping(chat, "Waiting for the model. Another agent is using it.");
        refreshStatus(chat);
        break;
      case "started":
        chat.status = "working";
        chat.runTokens = 0;
        Office.setMeter(chat.agent, 0, tokenLimit(chat));
        Office.say(chat.agent, "Thinking...", 600);
        setTyping(chat, "Thinking...");
        refreshStatus(chat);
        break;
      case "trace":
        addLog(chat.agent, payload);
        if (payload.event === "model") {
          chat.runTokens = (chat.runTokens || 0) + (payload.tokens || 0);
          Office.setMeter(chat.agent, chat.runTokens, tokenLimit(chat));
        } else if (payload.event === "tool") {
          Office.toolCall(chat.agent, payload.name, argSummary(payload.arguments));
        }
        if (payload.event === "tool") { setTyping(chat, `Using ${payload.name}...`); Office.say(chat.agent, `Using ${payload.name}`, 600); }
        else if (payload.event === "nudge") { setTyping(chat, "Double-checking its answer..."); Office.say(chat.agent, "Double-checking...", 600); }
        else if (chat.busy) setTyping(chat, "Thinking...");
        break;
      case "reply":
        endTurn(chat);
        addReply(chat, payload);
        chat.lastRun = payload;
        Office.setMeter(chat.agent, payload.tokens || 0, tokenLimit(chat));
        Office.setAlert(chat.agent, payload.ok ? "" : `Last run stopped early: ${STOP_REASONS[payload.stop_reason] || payload.stop_reason}`);
        Office.say(chat.agent, payload.ok ? "Done!" : "Stopped early", 3);
        break;
      case "error":
        if (chat.busy) endTurn(chat);
        Office.setAlert(chat.agent, "Last run failed");
        Office.say(chat.agent, "Something went wrong", 4);
        addSystem(chat, payload.message || "Something went wrong.", "error");
        break;
      default:
        break; // "ready" needs no action
    }
  }

  function sendMessage(chat, text) {
    text = String(text).trim();
    if (!text || chat.busy) return;
    if (chat.starters) { chat.starters.remove(); chat.starters = null; }
    addUser(chat, text);
    beginTurn(chat);
    if (chat.ws && chat.open) {
      chat.ws.send(JSON.stringify({ type: "message", text }));
    } else {
      chat.outbox.push(text);
      if (!chat.ws) connect(chat);
    }
  }

  // ---------- chat header, notes, composer ----------

  function renderHeader(agent) {
    const avatarNode = avatar(agent.name, "chat-avatar");
    $("chat-avatar").replaceWith(avatarNode);
    $("chat-live").style.setProperty("--accent", colorOf(agent.name));
    $("chat-name").textContent = pretty(agent.name);
    $("chat-sub").textContent = `${agent.mode === "task" ? "Task agent" : "Chat agent"} · ${agent.model}`;
    const chips = agent.tools.map((t) => el("span", { class: "chip", text: t, title: `Tool: ${t}` }));
    for (const warning of agent.warnings) chips.push(el("span", { class: "chip warn", text: clip(warning, 60), title: warning }));
    $("chat-chips").replaceChildren(...chips);
    $("notes-btn").disabled = !agent.memory.notes;
    $("notes-btn").title = agent.memory.notes ? "See what this agent remembers" : "This agent does not keep notes";
  }

  function closeNotes() {
    $("notes-drawer").hidden = true;
    $("notes-btn").setAttribute("aria-expanded", "false");
  }

  async function toggleNotes() {
    const drawer = $("notes-drawer");
    if (!drawer.hidden) return closeNotes();
    const name = state.current;
    $("notes-text").textContent = "Loading...";
    drawer.hidden = false;
    $("notes-btn").setAttribute("aria-expanded", "true");
    try {
      const data = await getJSON(`/api/agents/${encodeURIComponent(name)}/notes`);
      if (state.current === name) $("notes-text").textContent = data.notes.trim() || "No notes yet.";
    } catch {
      $("notes-text").textContent = "Could not load the notes.";
    }
  }

  function updateComposer() {
    const chat = currentChat();
    $("send-btn").disabled = !chat || chat.busy;
    $("composer-input").disabled = !chat;
  }

  function autosize() {
    const input = $("composer-input");
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
  }

  function newChat() {
    const chat = currentChat();
    const agent = currentAgent();
    if (!chat || !agent || chat.busy) return;
    if (chat.ws) {
      const old = chat.ws;
      chat.ws = null;
      chat.open = false;
      old.close();
    }
    chat.view.replaceChildren();
    chat.outbox = [];
    chat.typing = null;
    showWelcome(chat, agent);
    connect(chat);
    updateComposer();
  }

  function selectAgent(name) {
    const agent = state.agents.find((a) => a.name === name);
    if (!agent) return;
    const previous = currentChat();
    if (previous) previous.draft = $("composer-input").value;
    state.current = name;
    let chat = state.chats.get(name);
    if (!chat) {
      chat = makeChat(agent);
      state.chats.set(name, chat);
      showWelcome(chat, agent);
      connect(chat);
    }
    for (const c of state.chats.values()) c.view.hidden = c !== chat;
    $("chat-section").hidden = false;
    $("col-main").classList.add("has-chat");
    closeNotes();
    renderHeader(agent);
    renderRoster();
    $("composer-input").value = chat.draft;
    autosize();
    updateComposer();
    scrollDown(chat);
    $("composer-input").focus();
  }

  function deselect() {
    const previous = currentChat();
    if (previous) previous.draft = $("composer-input").value;
    state.current = null;
    $("chat-section").hidden = true;
    $("col-main").classList.remove("has-chat");
    Office.select(null);
    renderRoster();
    updateComposer();
  }

  // ---------- activity log ----------

  function argSummary(args) {
    if (!args || typeof args !== "object") return "";
    if (typeof args.path === "string") return args.path;
    if (typeof args.url === "string") return args.url;
    if (typeof args.name === "string") return args.header ? `${args.name} (${args.header})` : args.name;
    if (typeof args.code === "string") return `(${args.code.split("\n").length} lines of C++)`;
    if (typeof args.text === "string") return clip(args.text, 60);
    return clip(JSON.stringify(args), 60);
  }

  function describe(entry) {
    switch (entry.event) {
      case "model": {
        const calls = (entry.calls || []).map((c) => c.name);
        return {
          tone: "neutral",
          text: calls.length ? `Decided to use ${calls.join(", ")}` : `Model replied (${entry.tokens || 0} tokens)`,
          sub: entry.content ? clip(String(entry.content), 400) : "",
        };
      }
      case "tool": {
        const output = String(entry.output || "");
        return {
          tone: output.startsWith("ERROR") ? "error" : "ok",
          text: `${entry.name} ${argSummary(entry.arguments)}`.trim(),
          sub: output,
        };
      }
      case "nudge": return { tone: "warn", text: entry.message || "Asked the model to double-check" };
      case "trim": return { tone: "neutral", text: entry.message || "Forgot old messages to fit the model's memory" };
      case "warning": return { tone: "warn", text: entry.message || "Warning" };
      case "error": return { tone: "error", text: entry.message || "Error" };
      default: return { tone: "neutral", text: String(entry.event || "event") };
    }
  }

  function toggleRow(row) {
    const open = row.classList.toggle("is-open");
    row.setAttribute("aria-expanded", String(open));
  }

  function addLog(agentName, entry) {
    const log = $("log");
    const info = describe(entry);
    const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    const row = el("li", {
      class: `log-row is-${info.tone}`,
      style: accent(agentName),
      title: `${entry.t}s into the turn. Click for more.`,
      tabindex: "0",
      role: "button",
      "aria-expanded": "false",
    },
    el("span", { class: "dot" }),
    el("div", { class: "body" },
      el("span", { class: "who", text: pretty(agentName) }),
      info.text,
      info.sub ? el("span", { class: "sub", text: info.sub }) : null));
    row.addEventListener("click", () => toggleRow(row));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggleRow(row); }
    });
    log.querySelector(".log-empty")?.remove();
    log.append(row);
    while (log.children.length > MAX_LOG_ROWS) log.firstElementChild.remove();
    if (nearBottom) log.scrollTop = log.scrollHeight;
  }

  function clearLog() {
    $("log").replaceChildren(el("li", { class: "log-empty", text: "Cleared. New steps will show up here." }));
  }

  // ---------- removing an agent ----------

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
      el("button", { type: "button", role: "menuitem", text: "Staff file", onclick: () => { hideMenu(); openStaff(name); } }),
      el("button", { type: "button", role: "menuitem", class: "danger", text: "Remove agent...", onclick: () => { hideMenu(); askRemove(name); } }));
    deskMenu.hidden = false;
    deskMenu.style.left = `${Math.max(8, Math.min(x, window.innerWidth - deskMenu.offsetWidth - 8))}px`;
    deskMenu.style.top = `${Math.max(8, Math.min(y, window.innerHeight - deskMenu.offsetHeight - 8))}px`;
    deskMenu.firstElementChild.focus();
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
  }

  // ---------- wiring ----------

  $("composer").addEventListener("submit", (event) => {
    event.preventDefault();
    const chat = currentChat();
    if (!chat || chat.busy) return;
    const input = $("composer-input");
    const text = input.value;
    if (!text.trim()) return;
    input.value = "";
    autosize();
    sendMessage(chat, text);
  });
  $("composer-input").addEventListener("input", autosize);
  $("composer-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      $("composer").requestSubmit();
    }
  });
  $("notes-btn").addEventListener("click", toggleNotes);
  $("staff-btn").addEventListener("click", () => { if (state.current) openStaff(state.current); });
  $("new-chat-btn").addEventListener("click", newChat);
  $("clear-log").addEventListener("click", clearLog);
  $("close-chat").addEventListener("click", () => { closeNotes(); deselect(); $("office").focus(); });
  $("refresh-agents").addEventListener("click", () => { loadConfig(); loadAgents(); });
  $("new-agent-btn").addEventListener("click", () => Nova.hire());
  document.addEventListener("agentfactory:hired", (event) => {
    state.hired.set(event.detail.name, event.detail.goal);
    loadAgents();
  });
  $("ollama-pill").addEventListener("click", loadConfig);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") { closeNotes(); hideMenu(); } });
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
  removeDialog.addEventListener("close", () => { removing = null; });
  window.addEventListener("focus", () => { loadConfig(); loadAgents(); });

  Office.init({
    canvas: $("office"),
    tip: $("office-tip"),
    live: $("office-live"),
    onPick: selectAgent,
    onGuide: () => Nova.menu(),
    onMenu: showDeskMenu,
  });
  Hire.init({ colorOf });
  Staff.init({
    onChat: selectAgent,
    onRemove: askRemove,
    look: (name) => ({ label: pretty(name), color: colorOf(name), hair: (custom.get(name) || {}).hair || null }),
  });
  Palette.init({ items: paletteItems });
  loadConfig();
  loadAgents().then(() => Nova.boot());
  setInterval(() => { if (!document.hidden) loadAgents(); }, 8000); // new or removed spec files show up on their own
})();
