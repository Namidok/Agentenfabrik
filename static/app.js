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
    stopped: "stopped by you",
    error: "error",
  };
  const STATUS = {
    idle: { label: "Idle", icon: "desk" },
    working: { label: "Working", icon: "bolt" },
    queued: { label: "Waiting for the model", icon: "queue" },
  };
  // Short words written in capitals in names, so "cs-tutor" reads "CS Tutor".
  const ACRONYMS = new Set(["ai", "api", "cli", "cs", "css", "db", "gpu", "hr", "html", "js", "llm", "ml", "os", "pdf", "qa", "seo", "sql", "srs", "ts", "ui", "ux"]);

  // What each tool means, in words, with the icon of its station in the office.
  const TOOL_INFO = {
    "fs.read": { icon: "folder", label: "Read files", perm: (p) => `Only in ${list(p.fs_read)}` },
    "fs.list": { icon: "folder", label: "List folders", perm: (p) => `Only in ${list(p.fs_read)}` },
    "fs.write": { icon: "folder", label: "Write files", perm: (p) => `Into ${list(p.fs_write)}${p.allow_overwrite ? ", may replace files" : ", never replaces files"}` },
    "fs.move": { icon: "folder", label: "Move files", perm: (p) => `Inside ${list(p.fs_write)}` },
    "http.fetch": { icon: "globe", label: "Visit websites", perm: (p) => `Only ${list(p.network)}` },
    "notes.read": { icon: "notes", label: "Read its notes", perm: () => "Its own notes file" },
    "notes.append": { icon: "notes", label: "Save notes", perm: () => "Its own notes file" },
    "srs.add": { icon: "card", label: "Add flashcards", perm: () => "Its own card box" },
    "srs.due": { icon: "card", label: "See due flashcards", perm: () => "Its own card box" },
    "srs.review": { icon: "card", label: "Grade flashcards", perm: () => "Its own card box" },
    "code.run": { icon: "gear", label: "Run C++ code", perm: () => "On this computer, not isolated" },
    "code.check_name": { icon: "gear", label: "Check C++ names", perm: () => "Compiles a tiny test" },
    "script.run": { icon: "gear", label: "Run job-search programs", perm: () => "Only the listed programs in scripts/, on this computer" },
  };
  // How a tool call reads inside a reply: [icon, one call, several calls]
  const CALL_WORDS = {
    notes_read: ["notes", "read notes"], notes_append: ["notes", "saved a note", "saved {n} notes"],
    srs_add: ["card", "added card", "added {n} cards"], srs_due: ["card", "checked due cards"],
    srs_review: ["card", "graded card", "graded {n} cards"], fs_read: ["folder", "read {arg}"], fs_list: ["folder", "listed {arg}"],
    fs_write: ["folder", "wrote {arg}"], fs_move: ["folder", "moved {arg}"], http_fetch: ["globe", "read {arg}"],
    code_run: ["gear", "ran code", "ran code {n} times"], code_check_name: ["gear", "checked {arg}"],
    script_run: ["gear", "ran {arg}", "ran {n} programs"],
  };

  const $ = (id) => document.getElementById(id);
  const state = {
    agents: [],
    loaded: false,
    current: null, // name of the selected agent
    chats: new Map(), // agent name -> chat object
    known: null, // names seen on the last load, so arrivals and departures can be shown
    signature: "",
    seats: loadSeats(), // desk order: everyone keeps their desk, newcomers take the next free one
    leaving: new Map(), // agents on their way out: name -> last known summary
    hired: new Map(), // agents hired in this session: name -> goal, for their introduction
    queue: [], // agents waiting for the model, in order
    ollamaUp: null,
    slots: 1, // how many agents may think at once (settings.yaml max_parallel)
    settingsWarned: false,
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
  const icon = (name, extra) => Icons.el(name, extra);

  function hash(text) {
    let h = 0;
    for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return h;
  }
  // Looks chosen in the hiring form (display name, colours), by agent name.
  const custom = new Map();
  const colorOf = (name) => (custom.get(name) || {}).color || PALETTE[hash(name) % PALETTE.length];
  const pretty = (name) => (custom.get(name) || {}).label ||
    name.split("-").map((w) => (ACRONYMS.has(w) ? w.toUpperCase() : w === "cpp" ? "C++" : w ? w[0].toUpperCase() + w.slice(1) : w)).join(" ");
  const clip = (text, n) => (text.length > n ? text.slice(0, n - 1) + "…" : text);
  const list = (items) => (items && items.length ? items.join(", ") : "nothing yet");
  const accent = (name) => `--accent:${colorOf(name)};--agent:${colorOf(name)}`;
  const number = (n) => Number(n || 0).toLocaleString();
  const short = (n) => (n >= 10000 ? `${Math.round(n / 1000)}k` : number(n));

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
  const visible = (chat) => chat && state.current === chat.agent && !$("chat-section").hidden;

  // ---------- flashcards (also used by the staff file) ----------

  function dueText(card, today) {
    const days = Math.round((Date.parse(card.due) - Date.parse(today || card.due)) / 86400000);
    const when = days <= 0 ? "Due now" : days === 1 ? "Due tomorrow" : `Due in ${days} days`;
    const seen = card.reps ? ` · right ${card.reps}x` : "";
    const missed = card.lapses ? ` · missed ${card.lapses}x` : "";
    return { text: `${when}${seen}${missed}`, now: days <= 0 };
  }

  // Cards show their front; the back stays hidden until you flip the card (or switch on reveal).
  function renderCards(listNode, data, { reveal = false } = {}) {
    if (!data.cards.length) {
      listNode.replaceChildren(el("li", { class: "empty-note", text: "No cards yet. They show up here as soon as the agent adds one." }));
      return;
    }
    listNode.replaceChildren(...data.cards.map((card) => {
      const back = el("span", { class: "back" });
      const showBack = (on) => {
        back.textContent = on ? card.back : "Click to see the answer";
        back.classList.toggle("hidden", !on);
      };
      showBack(reveal);
      const due = dueText(card, data.today);
      const button = el("button", { type: "button", class: "flashcard", "aria-pressed": String(reveal), title: card.tags ? `Tags: ${card.tags}` : null,
        onclick: () => { const on = button.getAttribute("aria-pressed") !== "true"; button.setAttribute("aria-pressed", String(on)); showBack(on); } },
      el("span", { class: "side", text: `Card ${card.id}` }), el("span", { class: "face", text: card.front }), back,
      el("span", { class: `due${due.now ? " now" : ""}`, text: due.text }));
      return el("li", {}, button);
    }));
  }
  window.Cards = { render: renderCards, fetch: (name) => getJSON(`/api/agents/${encodeURIComponent(name)}/cards`) };

  let cardsData = null;
  function closeCards() {
    $("cards-drawer").hidden = true;
    $("cards-btn").setAttribute("aria-expanded", "false");
  }
  async function loadCards() {
    const name = state.current;
    try {
      const data = await window.Cards.fetch(name);
      if (state.current !== name || $("cards-drawer").hidden) return;
      cardsData = data;
      $("cards-title").textContent = data.total ? `Flashcards: ${data.total}, ${data.due_today} due now` : "Flashcards";
      renderCards($("cards-list"), data, { reveal: $("cards-reveal").checked });
    } catch {
      $("cards-list").replaceChildren(el("li", { class: "empty-note", text: "Could not load the cards." }));
    }
  }
  function toggleCards() {
    if (!$("cards-drawer").hidden) return closeCards();
    closeNotes();
    $("cards-list").replaceChildren(el("li", {}, el("span", { class: "skeleton skeleton-line" }), el("span", { class: "skeleton skeleton-line", style: "width:60%" })));
    $("cards-drawer").hidden = false;
    $("cards-btn").setAttribute("aria-expanded", "true");
    loadCards();
  }

  // ---------- toasts ----------

  function toast(title, text, kind = "info", options = {}) {
    const box = $("toasts");
    const close = el("button", { type: "button", class: "btn btn-sm btn-icon btn-quiet", "aria-label": "Dismiss" }, icon("close"));
    const body = el("div", { class: "toast-text" }, el("strong", { text: title }), text ? el("span", { text }) : null);
    const node = el("div", { class: `toast ${kind}` },
      icon(options.icon || { ok: "check", warn: "warn", bad: "alert" }[kind] || "info"), body, close);
    if (options.action) {
      body.append(" ", el("button", { type: "button", class: "btn btn-sm btn-quiet", text: options.action.label,
        onclick: () => { dismiss(); options.action.run(); } }));
    }
    let timer = 0;
    function dismiss() {
      clearTimeout(timer);
      node.classList.add("leaving");
      setTimeout(() => node.remove(), 200);
    }
    close.addEventListener("click", dismiss);
    node.addEventListener("pointerenter", () => clearTimeout(timer));
    node.addEventListener("pointerleave", () => { timer = setTimeout(dismiss, 2500); });
    box.append(node);
    while (box.children.length > 3) box.firstElementChild.remove();
    timer = setTimeout(dismiss, kind === "bad" ? 9000 : 5000);
  }

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
    const label = el("span", { text: "Copy" });
    const copy = el("button", { type: "button", class: "btn btn-sm", "aria-label": "Copy the code" }, icon("copy"), label);
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(body);
        label.textContent = "Copied";
      } catch {
        label.textContent = "Select and copy";
      }
      setTimeout(() => { label.textContent = "Copy"; }, 1500);
    });
    return el("div", { class: "code" },
      el("div", { class: "code-head" }, el("span", { text: lang || "code" }), copy),
      el("pre", { tabindex: "0" }, el("code", { text: body })));
  }

  function textBlocks(part) {
    const blocks = [];
    let paragraph = [];
    let listNode = null;
    const flushParagraph = () => {
      if (paragraph.length) blocks.push(el("p", {}, inline(paragraph.join("\n"))));
      paragraph = [];
    };
    const flushList = () => {
      if (listNode) blocks.push(listNode);
      listNode = null;
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
        if (!listNode || listNode.tagName !== "UL") { flushList(); listNode = el("ul"); }
        listNode.append(el("li", {}, inline(m[1])));
      } else if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
        flushParagraph();
        if (!listNode || listNode.tagName !== "OL") { flushList(); listNode = el("ol"); }
        listNode.append(el("li", {}, inline(m[1])));
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
    const chip = $("runtime-chip");
    let up = null;
    pill.className = "pill";
    pill.textContent = "Checking...";
    try {
      const config = await getJSON("/api/config");
      up = !!config.ollama_up;
      state.slots = config.max_parallel || 1;
      Office.setBrain({ online: up, slots: state.slots });
      if (!state.settingsWarned) {
        state.settingsWarned = true;
        if (config.settings_error) toast("settings.yaml has a problem", config.settings_error, "warn");
        for (const w of config.warnings || []) toast("Memory", w, "warn");
      }
      if (up) {
        pill.textContent = "Connected";
        pill.classList.add("is-ok");
        pill.title = "Click to check again";
        $("model-count").textContent = `${config.models.length} installed`;
      } else {
        pill.textContent = "Not running";
        pill.classList.add("is-bad");
        pill.title = "Open the Ollama app, then click here to check again.";
        $("model-count").textContent = "-";
      }
    } catch {
      up = false;
      pill.textContent = "Server error";
      pill.classList.add("is-bad");
      $("model-count").textContent = "-";
    }
    chip.classList.toggle("is-bad", !up);
    if (state.ollamaUp !== null && up !== state.ollamaUp) {
      if (up) toast("Ollama is back", "Your agents can think again.", "ok");
      else toast("Ollama is not running", "Open the Ollama app, then click the status in the top left to check again.", "bad");
    } else if (state.ollamaUp === null && up === false) {
      toast("Ollama is not running", "Agents need it to think. Open the Ollama app, then click the status in the top left.", "bad",
        { action: { label: "Check again", run: loadConfig } });
    }
    state.ollamaUp = up;
    renderState();
    updateComposer();
  }

  // ---------- roster ----------

  function badge(text, kind, title) {
    return el("span", { class: `badge ${kind || ""}`, text, title });
  }

  function statusDot(status) {
    const info = STATUS[status] || STATUS.idle;
    return el("span", { class: `status is-${status}`, title: info.label, role: "img", "aria-label": info.label }, icon(info.icon));
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
      statusDot(status)));
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
    const listNode = $("roster");
    listNode.replaceChildren(...state.agents.map(rosterItem));
    listNode.setAttribute("aria-busy", "false");
    $("agent-count").textContent = state.agents.length ? String(state.agents.length) : "";
    if (!state.agents.length) {
      listNode.append(el("li", { class: "empty-note", text: "No agents yet. Press the + button and Nova will help you hire one." }));
    }
    const empty = state.loaded && !state.agents.length && !state.leaving.size;
    $("office-empty").hidden = !empty;
    $("office-stage").classList.toggle("is-empty", empty);
    renderLogFilter();
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
      if (!state.loaded) {
        $("roster").replaceChildren(el("li", { class: "empty-note", text: "Could not reach the server. Is serve.py still running?" }));
        toast("Could not reach the server", "Start it again with python serve.py, then reload this page.", "bad");
      }
      return;
    }
    const firstLoad = !state.loaded;
    state.loaded = true;
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
    if (firstLoad && data.problems.length) toast("Some agent files could not be loaded", "Open the crew list to see what is wrong with them.", "warn",
      { action: { label: "Show", run: () => Shell.openSheet("crew") } });
    if (state.current) renderHeader(currentAgent());
    for (const name of gone) {
      Office.say(name, "Bye!", 2);
      Office.walkOut(name, "staff", () => { state.leaving.delete(name); syncOffice(); renderRoster(); });
    }
    if (before) {
      for (const a of data.agents) {
        if (before.has(a.name)) continue;
        const hired = state.hired.has(a.name);
        if (hired) toast("New hire", `${pretty(a.name)} is walking in through the staff door.`, "ok", { icon: "crew" });
        Office.walkIn(a.name, "staff", () => {
          Office.say(a.name, `Hi, I'm ${pretty(a.name)}!`, 5);
          if (hired) selectAgent(a.name); // someone you just hired introduces themselves in their chat
        });
      }
    }
  }

  function refreshStatus(chat) {
    const dot = document.querySelector(`.agent-card[data-name="${CSS.escape(chat.agent)}"] .status`);
    if (dot) dot.replaceWith(statusDot(chat.status));
    Office.setStatus(chat.agent, chat.status);
    if (chat.status === "queued") { if (!state.queue.includes(chat.agent)) state.queue.push(chat.agent); }
    else state.queue = state.queue.filter((n) => n !== chat.agent);
    renderState();
  }

  // ---------- chat ----------

  function makeChat(agent) {
    const view = el("div", { class: "messages", role: "log", "aria-live": "polite", "aria-relevant": "additions", hidden: true });
    $("messages-wrap").append(view);
    const chat = {
      agent: agent.name, view, ws: null, open: false, busy: false, status: "idle", stick: true, unseen: false,
      outbox: [], typing: null, starters: null, draft: "", runTokens: 0, steps: 0, turnTools: [], stopping: false, lastRun: null,
      pending: [], // files attached to the next message: { name, size, content }
    };
    view.addEventListener("scroll", () => {
      chat.stick = view.scrollHeight - view.scrollTop - view.clientHeight < 60;
      if (chat.stick) { chat.unseen = false; updateJump(); }
    });
    return chat;
  }

  function addSystem(chat, text, kind) {
    chat.view.append(el("div", { class: `msg system ${kind || ""}`, role: kind === "error" ? "alert" : null },
      kind ? icon(kind === "error" ? "alert" : "warn") : null, el("span", { text })));
    scrollDown(chat);
  }

  function addUser(chat, text, files = []) {
    chat.view.append(el("div", { class: "msg user" }, text ? el("p", { text }) : null,
      files.length ? el("div", { class: "msg-files", "aria-label": "Attached files" }, files.map((f) => el("span", { title: kb(f.size) }, icon("file"), f.name))) : null));
    scrollDown(chat, true);
  }

  // Tool calls of one turn as small chips: "read notes", "added 2 cards"
  function toolChips(calls) {
    const groups = [];
    for (const c of calls) {
      const last = groups[groups.length - 1];
      const bad = c.output.startsWith("ERROR");
      if (last && last.name === c.name && !bad && !last.bad && !CALL_WORDS[c.name]?.[1].includes("{arg}")) last.n += 1;
      else groups.push({ name: c.name, arg: argSummary(c.arguments), n: 1, bad, output: c.output });
    }
    return groups.map((g) => {
      const words = CALL_WORDS[g.name] || ["tools", g.name.replace(/_/g, " ")];
      const text = (g.n > 1 && words[2] ? words[2] : words[1]).replace("{n}", g.n).replace("{arg}", clip(g.arg || "", 28) || "something");
      return el("span", { class: `chip${g.bad ? " bad" : ""}`, title: g.bad ? g.output : `${g.name}${g.arg ? ` ${g.arg}` : ""}` },
        icon(g.bad ? "alert" : words[0]), g.bad ? `${text} failed` : text);
    });
  }

  function addReply(chat, p) {
    const meta = [`${p.steps} step${p.steps === 1 ? "" : "s"}`, `${number(p.tokens)} tokens`, `${p.seconds}s`];
    if (!p.ok) meta.push(`stopped: ${STOP_REASONS[p.stop_reason] || p.stop_reason}`);
    const chips = toolChips(chat.turnTools);
    chat.view.append(el("div", { class: `msg agent${p.ok ? "" : " warn"}`, style: `--agent:${colorOf(chat.agent)}` },
      chips.length ? el("div", { class: "msg-tools", "aria-label": "What it did" }, chips) : null,
      el("div", { class: "msg-body" }, renderMarkdown(p.text || "(no reply)")),
      el("div", { class: `msg-meta${p.ok ? "" : " warn"}` }, meta.map((m) => el("span", { text: m })))));
    scrollDown(chat);
  }

  // The reply as the model writes it. Replaced by the finished reply; screen readers only hear that one.
  function liveReply(chat) {
    if (!chat.live) {
      const node = el("div", { class: "msg agent live", style: `--agent:${colorOf(chat.agent)}`, "aria-hidden": "true" },
        el("div", { class: "msg-tools" }), el("div", { class: "msg-body live-text" }));
      chat.live = { node, step: 0 };
      if (chat.typing && chat.typing.parentNode === chat.view) chat.view.insertBefore(node, chat.typing);
      else chat.view.append(node);
    }
    return chat.live;
  }
  function clearLive(chat, keepChips = false) {
    if (!chat.live) return;
    if (keepChips) { chat.live.node.querySelector(".live-text").textContent = ""; return; }
    chat.live.node.remove();
    chat.live = null;
  }

  function setTyping(chat, label) {
    if (!chat.typing) {
      chat.typing = el("div", { class: "msg typing", "aria-live": "off" },
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

  // Follow new messages only while the reader is at the bottom; otherwise offer a jump button.
  function scrollDown(chat, force = false) {
    if (force) chat.stick = true;
    if (chat.stick) {
      requestAnimationFrame(() => { chat.view.scrollTop = chat.view.scrollHeight; });
    } else {
      chat.unseen = true;
      updateJump();
    }
  }

  let jumpBtn = null;
  function updateJump() {
    if (!jumpBtn) {
      jumpBtn = el("button", { type: "button", class: "btn btn-sm btn-primary jump", hidden: true,
        onclick: () => { const c = currentChat(); if (c) { c.unseen = false; scrollDown(c, true); updateJump(); } } },
      icon("down"), "New messages");
      $("messages-wrap").append(jumpBtn);
    }
    const chat = currentChat();
    jumpBtn.hidden = !(chat && chat.unseen && !chat.stick);
  }

  // What is wrong with this agent before you even type, or null.
  function problemOf(agent) {
    if (!agent) return null;
    if (!agent.runnable) return { title: "Out of order", text: `Some of its tools are not built yet (${agent.missing_tools.join(", ")}), so it cannot start.` };
    if (agent.model_installed === false) return { title: "Model missing", text: `It thinks with ${agent.model}, which is not installed. In a terminal run: ollama pull ${agent.model}`, soft: true };
    if (state.ollamaUp === false) return { title: "Ollama is not running", text: "Open the Ollama app, then click the status in the top left to check again.", soft: true };
    return null;
  }

  function showWelcome(chat, agent) {
    const tools = agent.tools.map((t) => {
      const info = TOOL_INFO[t] || { icon: "tools", label: t };
      return el("span", { class: "chip", title: t }, icon(info.icon), info.label);
    });
    const problem = problemOf(agent);
    const prompts = agent.name === JOB_DESK ? ["Search for jobs", "What can you do?"]
      : agent.mode === "task" ? ["What can you do?"]
      : ["What can you do?", agent.has_notes ? "Let's continue where we left off." : "Let's get started."];
    chat.starters = el("div", { class: "starters" }, prompts.map((text) =>
      el("button", { type: "button", class: "btn starter", text, title: "Send this as your first message", onclick: () => sendMessage(chat, text) })));
    const intro = state.hired.has(agent.name) ? `Hi, I'm ${pretty(agent.name)}. My job: ${state.hired.get(agent.name)}` : agent.goal;
    state.hired.delete(agent.name);
    chat.view.append(el("div", { class: "welcome" },
      avatar(agent.name),
      el("h3", { class: "px-lg", text: pretty(agent.name) }),
      el("p", { text: intro }),
      tools.length ? el("div", { class: "tools-line", "aria-label": "Tools" }, tools) : el("p", { class: "muted", text: "No tools. It can only talk." }),
      agent.mode === "task" ? el("p", { class: "muted", text: "A task agent: every message starts a fresh task." }) : null,
      problem ? el("div", { class: `callout ${problem.soft ? "is-warn" : "is-bad"}` }, el("strong", { text: problem.title }), problem.text) : null,
      problem && !problem.soft ? null : chat.starters));
  }

  function beginTurn(chat) {
    chat.busy = true;
    chat.status = "working";
    chat.runTokens = 0;
    chat.steps = 0;
    chat.turnTools = [];
    chat.stopping = false;
    Office.setAlert(chat.agent, "");
    refreshStatus(chat);
    setTyping(chat, "Sending...");
    updateComposer();
  }

  function endTurn(chat) {
    chat.busy = false;
    chat.status = "idle";
    chat.stopping = false;
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
      for (const payload of chat.outbox.splice(0)) ws.send(JSON.stringify(payload));
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

  // The token meter counts against the agent's own limit for one run.
  function tokenLimit(chat) {
    const agent = state.agents.find((a) => a.name === chat.agent);
    return agent && agent.limits ? agent.limits.max_tokens : 0;
  }

  function onServerEvent(chat, msg) {
    const payload = msg.payload || {};
    const name = pretty(chat.agent);
    switch (msg.event) {
      case "queued":
        chat.status = "queued";
        chat.queuePos = payload.position || 0;
        Office.say(chat.agent, "Waiting for the model...", 600);
        setTyping(chat, payload.reason === "model"
          ? `Waiting in line${chat.queuePos ? `, number ${chat.queuePos}` : ""}: another model is busy, and swapping models is slower than waiting.`
          : `Waiting in line${chat.queuePos ? `, number ${chat.queuePos}` : ""}: ${state.slots > 1 ? `all ${state.slots} model slots are busy` : "another agent is using the model"}.`);
        refreshStatus(chat);
        break;
      case "loading":
        setTyping(chat, `Loading ${payload.model} into memory. The first reply after a break takes a little longer.`);
        Office.say(chat.agent, "Waking the model...", 600);
        chat.loadingModel = true;
        renderState();
        break;
      case "started":
        chat.status = "working";
        chat.queuePos = 0;
        chat.runTokens = 0;
        Office.setMeter(chat.agent, 0, tokenLimit(chat));
        Office.say(chat.agent, "Thinking...", 600);
        setTyping(chat, chat.stopping ? "Stopping..." : "Thinking...");
        refreshStatus(chat);
        break;
      case "trace":
        if (payload.event === "delta") {
          const live = liveReply(chat);
          const text = live.node.querySelector(".live-text");
          if (payload.step !== live.step) { live.step = payload.step; text.textContent = ""; }
          text.textContent += payload.text;
          if (chat.loadingModel) { chat.loadingModel = false; renderState(); }
          scrollDown(chat);
          break;
        }
        addLog(chat.agent, payload);
        if (payload.event === "nudge") clearLive(chat, true); // that draft is being redone
        if (payload.event === "summary") chat.summarized = true;
        if (payload.event === "model") {
          chat.steps += 1;
          chat.runTokens = (chat.runTokens || 0) + (payload.tokens || 0);
          Office.setMeter(chat.agent, chat.runTokens, tokenLimit(chat));
        } else if (payload.event === "tool") {
          chat.turnTools.push({ name: payload.name, arguments: payload.arguments, output: String(payload.output || "") });
          Office.toolCall(chat.agent, payload.name, argSummary(payload.arguments));
          liveReply(chat).node.querySelector(".msg-tools").replaceChildren(...toolChips(chat.turnTools));
        }
        if (chat.stopping) setTyping(chat, "Stopping after the current step...");
        else if (payload.event === "tool") {
          const words = (CALL_WORDS[payload.name] || [0, `using ${payload.name}`])[1].replace("{arg}", clip(argSummary(payload.arguments), 28));
          setTyping(chat, `${words[0].toUpperCase()}${words.slice(1)}...`);
          Office.say(chat.agent, `Using ${payload.name}`, 600);
        } else if (payload.event === "nudge") { setTyping(chat, "Double-checking its answer..."); Office.say(chat.agent, "Double-checking...", 600); }
        else if (chat.busy) setTyping(chat, `Thinking, step ${chat.steps + 1}...`);
        renderState();
        break;
      case "reply":
        clearLive(chat);
        chat.loadingModel = false;
        endTurn(chat);
        addReply(chat, payload);
        chat.lastRun = payload;
        if (visible(chat) && !$("cards-drawer").hidden) loadCards();
        if (chat.agent === JOB_DESK) pollRun(800);
        Office.setMeter(chat.agent, payload.tokens || 0, tokenLimit(chat));
        Office.setAlert(chat.agent, payload.ok ? "" : `Last run stopped early: ${STOP_REASONS[payload.stop_reason] || payload.stop_reason}`);
        Office.say(chat.agent, payload.ok ? "Done!" : payload.stop_reason === "stopped" ? "OK, stopped" : "Stopped early", 3);
        if (!visible(chat)) toast(`${name} replied`, clip(String(payload.text || ""), 90), payload.ok ? "ok" : "warn",
          { icon: "chat", action: { label: "Open", run: () => selectAgent(chat.agent) } });
        renderState();
        break;
      case "error":
        clearLive(chat);
        chat.loadingModel = false;
        if (chat.busy) endTurn(chat);
        Office.setAlert(chat.agent, "Last run failed");
        Office.say(chat.agent, "Something went wrong", 4);
        addSystem(chat, payload.message || "Something went wrong.", "error");
        if (!visible(chat)) toast(`${name} ran into a problem`, clip(payload.message || "", 90), "bad",
          { action: { label: "Open", run: () => selectAgent(chat.agent) } });
        break;
      default:
        break; // "ready" needs no action
    }
  }

  function sendMessage(chat, text) {
    text = String(text).trim();
    if ((!text && !chat.pending.length) || chat.busy) return;
    const files = chat.pending.splice(0);
    if (chat.starters) { chat.starters.remove(); chat.starters = null; }
    addUser(chat, text, files);
    if (chat === currentChat()) renderPending();
    beginTurn(chat);
    const payload = { type: "message", text };
    if (files.length) payload.attachments = files.map((f) => ({ name: f.name, content: f.content }));
    if (chat.ws && chat.open) {
      chat.ws.send(JSON.stringify(payload));
    } else {
      chat.outbox.push(payload);
      if (!chat.ws) connect(chat);
    }
  }

  // ---------- attachments: text files sent with the next message ----------

  const ATTACH = { files: 5, fileBytes: 400_000, totalBytes: 600_000 };
  const kb = (n) => (n < 1024 ? `${n} B` : `${Math.round(n / 102.4) / 10} KB`);

  async function addFiles(chat, list) {
    if (!chat || chat.busy) return;
    for (const file of list) {
      if (chat.pending.length >= ATTACH.files) { toast("Too many files", `Attach at most ${ATTACH.files} files to one message.`, "warn"); break; }
      if (file.size > ATTACH.fileBytes) {
        toast("File too large", `${file.name} is ${kb(file.size)}; the limit is ${kb(ATTACH.fileBytes)}. Attach the part that matters, or put the file in a folder the agent may read.`, "warn");
        continue;
      }
      if (chat.pending.reduce((n, f) => n + f.size, 0) + file.size > ATTACH.totalBytes) {
        toast("Too much at once", `Attach at most ${kb(ATTACH.totalBytes)} to one message.`, "warn");
        continue;
      }
      let content = "";
      try { content = await file.text(); } catch { toast("Could not read the file", file.name, "bad"); continue; }
      const head = content.slice(0, 8000);
      if (head.includes("\u0000") || head.startsWith("%PDF") || (head.match(/\uFFFD/g) || []).length > head.length / 20) {
        toast("Not a text file", `${file.name} is not text. Attach code, logs, Markdown, CSV, JSON or other text files.`, "warn");
        continue;
      }
      chat.pending.push({ name: file.name, size: file.size, content });
    }
    if (chat === currentChat()) renderPending();
  }

  function renderPending() {
    const chat = currentChat();
    const files = chat ? chat.pending : [];
    const box = $("attach-list");
    box.hidden = !files.length;
    box.replaceChildren(...files.map((f, i) => el("span", { class: "attach-chip", title: `${f.name}, ${kb(f.size)}` }, icon("file"),
      el("span", { text: `${f.name} · ${kb(f.size)}` }),
      el("button", { type: "button", class: "btn btn-sm btn-icon btn-quiet", "aria-label": `Remove ${f.name}`,
        onclick: () => { chat.pending.splice(i, 1); renderPending(); } }, icon("close")))));
  }

  function stopTurn() {
    const chat = currentChat();
    if (!chat || !chat.busy || chat.stopping) return;
    if (chat.ws && chat.open) {
      chat.ws.send(JSON.stringify({ type: "stop" }));
      chat.stopping = true;
      setTyping(chat, chat.status === "queued" ? "Stopping..." : "Stopping after the current step...");
    } else {
      chat.outbox = []; // never sent, so nothing to stop
      endTurn(chat);
      addSystem(chat, "Stopped before it was sent.");
    }
    updateComposer();
    renderState();
  }

  // ---------- chat header: state, tools, meter, menu ----------

  function renderState() {
    const chat = currentChat();
    const agent = currentAgent();
    if (!chat || !agent) return;
    let ico = "desk", text = "At their desk", cls = "";
    const problem = problemOf(agent);
    if (chat.status === "working" && chat.loadingModel) {
      ico = "queue"; cls = "is-queued"; text = "Loading the model";
    } else if (chat.status === "working") {
      ico = "bolt"; cls = "is-working";
      text = chat.stopping ? "Stopping after this step" : `Working${chat.steps ? `, step ${chat.steps}` : ""}`;
    } else if (chat.status === "queued") {
      const pos = chat.queuePos || state.queue.indexOf(chat.agent) + 1;
      ico = "queue"; cls = "is-queued"; text = pos ? `Waiting in line, number ${pos}` : "Waiting in line";
    } else if (problem) {
      ico = problem.soft ? "warn" : "alert"; cls = "is-bad"; text = problem.title;
    } else {
      const where = Office.where(chat.agent);
      // same words as the office tooltip, so the two never disagree
      if (where && where.place === "lounge") { ico = "coffee"; text = where.label; }
      else if (where && where.place === "walking") { ico = "desk"; text = where.label; }
    }
    $("chat-state").className = `chat-state ${cls}`;
    $("chat-state-icon").className = `ico ico-${ico}`;
    const label = $("chat-state-text");
    if (label.textContent !== text) label.textContent = text;

    const max = tokenLimit(chat);
    const used = chat.busy ? chat.runTokens : chat.lastRun ? chat.lastRun.tokens : 0;
    const fill = max ? Math.min(1, used / max) : 0;
    const meter = $("chat-meter");
    meter.className = `meter${fill >= 1 ? " is-full" : fill > 0.75 ? " is-high" : ""}${chat.summarized ? " is-summarized" : ""}`;
    meter.querySelector("i").style.setProperty("--fill", fill.toFixed(3));
    meter.querySelector(".meter-text").textContent = `${short(used)} / ${short(max)}`;
    meter.setAttribute("aria-valuenow", fill.toFixed(2));
    meter.setAttribute("aria-valuetext", `${number(used)} of ${number(max)} tokens ${chat.busy ? "in this run" : "in the last run"}`);
    meter.title = `${chat.busy ? "This run" : chat.lastRun ? "Last run" : "No run yet"}: ${number(used)} of ${number(max)} tokens` +
      (chat.summarized ? ". Older turns of this chat were folded into a short summary to keep replies fast." : "");
  }

  function renderHeader(agent) {
    const avatarNode = avatar(agent.name, "chat-avatar");
    $("chat-avatar").replaceWith(avatarNode);
    $("chat-live").style.setProperty("--agent", colorOf(agent.name));
    $("chat-name").textContent = pretty(agent.name);
    $("chat-sub").textContent = ` · ${agent.mode === "task" ? "Task agent" : "Chat agent"}`;
    const modelChip = $("chat-model");
    const missing = agent.model_installed === false;
    modelChip.className = `chip${missing ? " warn" : ""}`;
    modelChip.querySelector("span").textContent = agent.model;
    modelChip.title = missing
      ? `${agent.model} is not installed. In a terminal run: ollama pull ${agent.model}`
      : `Thinks with ${agent.model}${agent.model_source === "spec" ? ", named in this agent's file" : ", the default from settings.yaml"}`;
    modelChip.querySelector(".ico").className = `ico ico-${missing ? "warn" : "brain"}`;
    const p = agent.permissions || {};
    const rows = agent.tools.map((t) => {
      const info = TOOL_INFO[t] || { icon: "tools", label: t, perm: () => "" };
      return el("li", {}, icon(info.icon), el("span", {}, info.label, " ", el("code", { text: t })), el("small", { text: info.perm(p) }));
    });
    const pop = $("tools-pop");
    pop.replaceChildren(el("h3", { class: "px", text: agent.tools.length ? "What it may use" : "No tools: it can only talk" }), el("ul", { id: "chat-chips" }, rows));
    if (agent.warnings.length) {
      pop.append(el("h3", { class: "px", text: "Worth knowing" }),
        el("ul", {}, agent.warnings.map((w) => el("li", { class: "warn" }, icon("warn"), el("span", { text: w })))));
    }
    $("tools-label").textContent = agent.tools.length ? `${agent.tools.length} tool${agent.tools.length === 1 ? "" : "s"}` : "No tools";
    const warn = $("chat-warn");
    warn.hidden = !agent.warnings.length;
    warn.querySelector("span").textContent = `${agent.warnings.length} to know`;
    warn.title = agent.warnings.join("\n");
    $("notes-btn").disabled = !agent.memory.notes;
    $("cards-btn").hidden = !agent.memory.srs;
    $("notes-btn").setAttribute("data-tip", agent.memory.notes ? "Notes: what it remembers" : "This agent keeps no notes");
    closeTools();
    renderState();
  }

  function closeTools() {
    $("tools-pop").hidden = true;
    $("tools-btn").setAttribute("aria-expanded", "false");
  }
  function toggleTools() {
    const open = $("tools-pop").hidden;
    $("tools-pop").hidden = !open;
    $("tools-btn").setAttribute("aria-expanded", String(open));
  }

  const chatMenu = $("chat-menu");
  function closeChatMenu(focusBack = false) {
    if (chatMenu.hidden) return;
    chatMenu.hidden = true;
    $("chat-more").setAttribute("aria-expanded", "false");
    if (focusBack) $("chat-more").focus();
  }
  function openChatMenu() {
    const chat = currentChat();
    $("new-chat-btn").disabled = !!(chat && chat.busy);
    $("remove-btn").disabled = !!(chat && chat.busy);
    chatMenu.hidden = false;
    $("chat-more").setAttribute("aria-expanded", "true");
    const r = $("chat-more").getBoundingClientRect();
    chatMenu.style.left = `${Math.max(8, Math.min(r.right - chatMenu.offsetWidth, window.innerWidth - chatMenu.offsetWidth - 8))}px`;
    chatMenu.style.top = `${Math.min(r.bottom + 10, window.innerHeight - chatMenu.offsetHeight - 8)}px`;
    chatMenu.querySelector("button:not(:disabled)")?.focus();
  }

  function closeNotes() {
    $("notes-drawer").hidden = true;
    $("notes-btn").setAttribute("aria-expanded", "false");
  }

  async function toggleNotes() {
    const drawer = $("notes-drawer");
    if (!drawer.hidden) return closeNotes();
    closeCards();
    const name = state.current;
    $("notes-text").replaceChildren(el("span", { class: "skeleton skeleton-line" }), el("span", { class: "skeleton skeleton-line", style: "width:60%" }));
    drawer.hidden = false;
    $("notes-btn").setAttribute("aria-expanded", "true");
    try {
      const data = await getJSON(`/api/agents/${encodeURIComponent(name)}/notes`);
      if (state.current === name) $("notes-text").textContent = data.notes.trim() || "No notes yet. It writes here when it wants to remember something.";
    } catch {
      $("notes-text").textContent = "Could not load the notes.";
    }
  }

  function updateComposer() {
    const chat = currentChat();
    const agent = currentAgent();
    const problem = problemOf(agent);
    const blocked = !!(problem && !problem.soft);
    $("send-btn").hidden = !!(chat && chat.busy);
    $("stop-btn").hidden = !(chat && chat.busy);
    $("stop-btn").disabled = !!(chat && chat.stopping);
    $("stop-btn").querySelector("span").textContent = chat && chat.stopping ? "Stopping" : "Stop";
    $("send-btn").disabled = !chat || blocked;
    $("composer-input").disabled = !chat || blocked;
    $("attach-btn").disabled = !chat || blocked || !!(chat && chat.busy);
    const note = $("composer-note");
    note.hidden = !problem;
    note.textContent = problem ? `${problem.title}. ${problem.text}` : "";
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
    chat.pending = [];
    renderPending();
    chat.typing = null;
    chat.lastRun = null;
    chat.summarized = false;
    chat.stick = true;
    chat.unseen = false;
    showWelcome(chat, agent);
    connect(chat);
    updateComposer();
    updateJump();
    renderState();
    toast("New chat", `${pretty(agent.name)} starts with a clean slate. Saved notes stay.`, "info", { icon: "refresh" });
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
      const problem = problemOf(agent);
      if (!problem || problem.soft) connect(chat);
    }
    for (const c of state.chats.values()) c.view.hidden = c !== chat;
    $("chat-section").hidden = false;
    $("col-main").classList.add("has-chat");
    closeNotes();
    closeCards();
    closeChatMenu();
    renderHeader(agent);
    renderRun();
    renderRoster();
    $("composer-input").value = chat.draft;
    renderPending();
    autosize();
    updateComposer();
    updateJump();
    scrollDown(chat, true);
    $("composer-input").focus();
  }

  function deselect() {
    const previous = currentChat();
    if (previous) previous.draft = $("composer-input").value;
    state.current = null;
    $("chat-section").hidden = true;
    $("col-main").classList.remove("has-chat");
    closeChatMenu();
    closeTools();
    closeCards();
    Office.select(null);
    renderRoster();
    updateComposer();
  }

  // ---------- job search run (the panel in Job Desk's chat) ----------
  //
  // One run does the whole search: Job Desk searches, Job Matcher ranks, then the good matches wait for your OK;
  // after it, CV Writer, CV Reviewer and the PDF printer go one after another. The run is a separate process on
  // the server (scripts/jobs/pipeline.py); this panel starts it, follows data/jobs/run_status.json, sends the OK
  // and shows the agent at work in the office.

  const JOB_DESK = "job-desk";
  const RUN_STEPS = [
    { key: "job-desk", label: "Search" }, { key: "job-matcher", label: "Match" }, { key: "ok", label: "Your OK" },
    { key: "application-writer", label: "Write" }, { key: "application-reviewer", label: "Review" }, { key: "pdf", label: "PDFs" },
  ];
  const jobRun = { status: null, timer: 0, atWork: null, sending: false, picks: new Map(), seen: "", drawn: "", logOpen: false };

  // Which step of the strip the run is on: 0-5, and how far it got.
  function runStep(s) {
    if (!s || s.state === "idle") return -1;
    if (s.state === "waiting") return 2;
    if (s.kind === "documents") {
      if (s.state !== "running") return 6;
      if (s.agent === "application-writer") return 3;
      if (s.agent === "application-reviewer") return 4;
      return /printing/.test(s.detail || "") ? 5 : 3;
    }
    if (s.state !== "running") return 2;
    return s.agent === "job-matcher" ? 1 : 0;
  }

  async function pollRun(soon) {
    clearTimeout(jobRun.timer);
    if (soon) { jobRun.timer = setTimeout(() => pollRun(), soon); return; }
    try {
      jobRun.status = await getJSON("/api/jobs/run");
    } catch { /* the server is restarting: try again below */ }
    const s = jobRun.status || { state: "idle" };
    showRunInOffice(s);
    announceRun(s);
    const drawn = JSON.stringify(s);
    if (drawn !== jobRun.drawn || s.state === "running") renderRun(); // a quiet panel keeps your focus and ticks
    jobRun.drawn = drawn;
    jobRun.timer = setTimeout(() => pollRun(), s.state === "running" ? 2500 : document.hidden ? 60000 : 15000);
  }

  function showRunInOffice(s) {
    const agent = s.state === "running" ? s.agent : null;
    if (jobRun.atWork && jobRun.atWork !== agent) {
      const chat = state.chats.get(jobRun.atWork);
      Office.setStatus(jobRun.atWork, chat ? chat.status : "idle");
    }
    jobRun.atWork = agent;
    if (!agent) return;
    const chat = state.chats.get(agent);
    if (chat && chat.busy) return; // its own chat turn shows instead
    Office.setStatus(agent, "working");
    Office.say(agent, clip(String(s.detail || "Working").replace(/^[A-Za-z ]+: /, ""), 40), 4);
  }

  // A toast once when a run needs you or has finished, wherever you are in the app.
  function announceRun(s) {
    const key = `${s.state}|${s.updated || ""}`;
    const first = jobRun.seen === "";
    if (key === jobRun.seen) return;
    jobRun.seen = key;
    const open = { label: "Open Job Desk", run: () => selectAgent(JOB_DESK) };
    const here = state.current === JOB_DESK && !$("chat-section").hidden;
    if (s.state === "waiting" && !here) toast("Job search: your OK needed", clip(s.detail || "", 120), "info", { icon: "search", action: open });
    else if (first) return; // an old result is no news
    else if (s.state === "done" && !here) toast("Job search finished", clip(s.detail || "", 120), "ok", { icon: "check", action: open });
    else if (s.state === "failed" && !here) toast("Job search stopped", clip(s.detail || "", 120), "bad", { action: open });
  }

  async function postRun(url, body) {
    jobRun.sending = true;
    renderRun();
    try {
      const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-AgentFactory": "1" },
        body: JSON.stringify(body || {}) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `The server answered ${response.status}.`);
      jobRun.status = { ...(jobRun.status || {}), state: "running", agent: "job-desk", detail: "Starting", log: [],
        kind: body && (body.approve || body.decline) ? "documents" : "search", started: new Date().toISOString() };
    } catch (e) {
      toast("Could not start the run", e.message, "bad");
    } finally {
      jobRun.sending = false;
      renderRun();
      pollRun(1200);
    }
  }

  const startSearch = () => postRun("/api/jobs/run");
  function sendChoice(all) {
    const waiting = (jobRun.status && jobRun.status.waiting) || [];
    const approve = all ? [] : waiting.filter((w) => jobRun.picks.get(w.id)).map((w) => w.id);
    const decline = waiting.map((w) => w.id).filter((id) => !approve.includes(id));
    postRun("/api/jobs/choose", { approve, decline });
  }

  const fileLink = (path, text) => el("a", { class: "btn btn-sm", href: `/api/jobs/file?path=${encodeURIComponent(path)}`, target: "_blank", rel: "noopener" }, icon("file"), text);

  function elapsed(s) {
    const from = Date.parse(s.started || "");
    if (!from) return "";
    const end = s.state === "running" ? Date.now() : Date.parse(s.updated || "") || Date.now();
    const min = Math.max(0, Math.round((end - from) / 60000));
    return min < 1 ? "under a minute" : `${min} min`;
  }

  function renderRun() {
    const box = $("jobrun");
    const show = state.current === JOB_DESK;
    box.hidden = !show;
    if (!show) return;
    const s = jobRun.status || { state: "idle" };
    const running = s.state === "running";
    const step = runStep(s);
    const strip = el("ol", { class: "run-steps", "aria-label": "Steps of the run" }, RUN_STEPS.map((r, i) => {
      const cls = step < 0 ? "" : i < step ? "done" : i === step ? (s.state === "waiting" ? "ask" : running ? "now" : "done") : "";
      return el("li", { class: cls, style: r.key.includes("-") ? `--agent:${colorOf(r.key)}` : null, "aria-current": i === step ? "step" : null },
        r.key.includes("-") ? el("span", { class: "run-dot", "aria-hidden": "true" }) : icon(r.key === "ok" ? "check" : "file"),
        el("span", { text: r.label }));
    }));

    let title = "Job search", line = "Searches LinkedIn, ranks the jobs, then asks before writing any CV.", body = null;
    const actions = [];
    const search = (label) => el("button", { type: "button", class: "btn btn-sm btn-primary", disabled: jobRun.sending || running,
      onclick: startSearch }, icon("search"), label);
    if (running) {
      title = s.kind === "documents" ? "Writing your documents" : "Searching";
      line = `${s.detail || "Starting"} · ${elapsed(s)}`;
      const lines = (s.log || []).slice(-6);
      if (lines.length) body = el("details", { class: "run-log", open: jobRun.logOpen, ontoggle: (e) => { jobRun.logOpen = e.target.open; } },
        el("summary", { text: "What happened so far" }), el("pre", { text: lines.join("\n") }));
    } else if (s.state === "waiting") {
      title = "Make CVs?";
      line = s.detail || "";
      for (const w of s.waiting || []) if (!jobRun.picks.has(w.id)) jobRun.picks.set(w.id, !!w.pick);
      const count = (s.waiting || []).filter((w) => jobRun.picks.get(w.id)).length;
      body = el("div", {},
        el("ul", { class: "run-jobs" }, (s.waiting || []).map((w) => {
          const box = el("input", { type: "checkbox", checked: !!jobRun.picks.get(w.id),
            onchange: () => { jobRun.picks.set(w.id, box.checked); renderRun(); } });
          return el("li", {}, el("label", { class: "run-job" }, box,
            el("span", {}, el("strong", { text: `${w.company} – ${w.title}` }),
              el("small", { text: [w.fit != null ? `fit ${w.fit}` : "", (w.location || "").split(",")[0], w.reason].filter(Boolean).join(" · ") }))),
          w.link ? el("a", { class: "btn btn-sm btn-quiet", href: w.link, target: "_blank", rel: "noopener noreferrer", title: "Open the posting" }, icon("globe")) : null);
        })),
        el("p", { class: "muted run-note", text: "Unticked jobs are skipped and not offered again. Nothing is sent anywhere." }));
      actions.push(el("button", { type: "button", class: "btn btn-sm btn-primary", disabled: jobRun.sending || !count,
        onclick: () => sendChoice(false) }, icon("check"), count === 1 ? "Make 1 CV" : `Make ${count} CVs`));
      actions.push(el("button", { type: "button", class: "btn btn-sm", disabled: jobRun.sending, onclick: () => sendChoice(true) }, "Skip all"));
    } else if (s.state === "done" || s.state === "idle" && s.detail) {
      title = s.kind === "documents" ? "Documents ready" : "Search done";
      line = `${s.detail || ""}${s.updated ? ` · ${new Date(s.updated).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}` : ""}`;
      const files = (s.result && s.result.files) || [];
      const report = s.result && s.result.report;
      body = el("div", {},
        files.length ? el("ul", { class: "run-jobs" }, files.map((f) => el("li", { class: "run-file" },
          el("span", {}, el("strong", { text: `${f.company} – ${f.title}` }),
            f.problems && f.problems.length ? el("small", { class: "warn", text: `Check: ${f.problems.join("; ")}` }) : el("small", { text: "Checked, no problems found" })),
          el("span", { class: "run-links" }, f.cv ? fileLink(f.cv, "CV") : null, f.cover_letter ? fileLink(f.cover_letter, "Letter") : null)))) : null,
        report ? el("p", { class: "run-note" }, fileLink(report, "Full report")) : null,
        (s.result && s.result.problems || []).length ? el("div", { class: "callout is-warn" }, el("strong", { text: "Problems" }), s.result.problems.join("; ")) : null);
      actions.push(search("Search again"));
    } else if (s.state === "failed") {
      title = "The run stopped";
      body = el("div", { class: "callout is-bad" }, s.detail || "Something went wrong.");
      line = "";
      actions.push(search("Try again"));
    } else {
      actions.push(search("Search for jobs"));
    }
    box.replaceChildren(
      el("div", { class: "run-head" },
        el("div", { class: "run-title" }, el("h3", { class: "px", text: title }), line ? el("p", { class: "muted", text: line }) : null),
        el("div", { class: "run-actions" }, actions)),
      strip, body);
  }

  // ---------- activity log ----------

  function argSummary(args) {
    if (!args || typeof args !== "object") return "";
    if (typeof args.path === "string") return args.path;
    if (typeof args.url === "string") { try { return new URL(args.url).host || args.url; } catch { return args.url; } }
    if (typeof args.name === "string") return args.header ? `${args.name} (${args.header})` : args.name;
    if (typeof args.code === "string") return `(${args.code.split("\n").length} lines of C++)`;
    if (typeof args.front === "string") return clip(args.front, 40);
    if (typeof args.script === "string") return args.script;
    if (typeof args.text === "string") return clip(args.text, 60);
    if (args.id != null) return `card ${args.id}${args.grade ? `: ${args.grade}` : ""}`;
    return Object.keys(args).length ? clip(JSON.stringify(args), 60) : "";
  }

  function describe(entry) {
    switch (entry.event) {
      case "model": {
        const calls = (entry.calls || []).map((c) => c.name);
        return {
          tone: "neutral", icon: "brain",
          text: calls.length ? `Decided to use ${calls.join(", ")}` : `Wrote its answer (${number(entry.tokens)} tokens)`,
          sub: entry.content ? clip(String(entry.content), 400) : "",
        };
      }
      case "tool": {
        const output = String(entry.output || "");
        const bad = output.startsWith("ERROR");
        return { tone: bad ? "error" : "ok", icon: bad ? "alert" : (CALL_WORDS[entry.name] || ["tools"])[0], text: `${entry.name} ${argSummary(entry.arguments)}`.trim(), sub: output };
      }
      case "nudge": return { tone: "warn", icon: "warn", text: entry.message || "Asked the model to double-check" };
      case "hint": return { tone: "neutral", icon: "info", text: entry.message || "Gave the model a hint" };
      case "trim": return { tone: "neutral", icon: "info", text: entry.message || "Forgot old messages to fit the model's memory" };
      case "warning": return { tone: "warn", icon: "warn", text: entry.message || "Warning" };
      case "stopped": return { tone: "warn", icon: "stop", text: entry.message || "Stopped by you" };
      case "error": return { tone: "error", icon: "alert", text: entry.message || "Error" };
      default: return { tone: "neutral", icon: "info", text: String(entry.event || "event") };
    }
  }

  function toggleRow(row) {
    const open = row.classList.toggle("is-open");
    row.setAttribute("aria-expanded", String(open));
  }

  function renderLogFilter() {
    const select = $("log-filter");
    const keep = select.value;
    const names = [...new Set([...state.agents.map((a) => a.name), ...[...$("log").querySelectorAll(".log-row")].map((r) => r.dataset.agent)])];
    select.replaceChildren(el("option", { value: "", text: "Every agent" }), ...names.map((n) => el("option", { value: n, text: pretty(n) })));
    select.value = names.includes(keep) ? keep : "";
  }

  function applyLogFilter() {
    const want = $("log-filter").value;
    for (const row of $("log").querySelectorAll(".log-row")) row.hidden = !!want && row.dataset.agent !== want;
  }

  function addLog(agentName, entry) {
    const log = $("log");
    const info = describe(entry);
    const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    const row = el("li", {
      class: `log-row is-${info.tone}`,
      style: accent(agentName),
      "data-agent": agentName,
      title: `${entry.t}s into the turn. Click for more.`,
      tabindex: "0",
      role: "button",
      "aria-expanded": "false",
    },
    icon(info.icon),
    el("div", { class: "body" },
      el("span", { class: "who", text: pretty(agentName) }),
      info.text,
      info.sub ? el("span", { class: "sub", text: info.sub }) : null),
    el("span", { class: "when", text: new Date().toTimeString().slice(0, 8) }));
    row.addEventListener("click", () => toggleRow(row));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggleRow(row); }
    });
    const want = $("log-filter").value;
    row.hidden = !!want && want !== agentName;
    log.querySelector(".log-empty")?.remove();
    log.append(row);
    while (log.children.length > MAX_LOG_ROWS) log.firstElementChild.remove();
    if (nearBottom) log.scrollTop = log.scrollHeight;
  }

  function clearLog() {
    $("log").replaceChildren(el("li", { class: "log-empty" }, icon("log"), "Cleared. New steps will show up here."));
  }

  // ---------- removing an agent ----------

  const removeDialog = $("remove-dialog");
  const deskMenu = $("desk-menu");
  let removing = null;

  function setConfirmLabel(text) {
    const button = $("remove-confirm");
    button.replaceChildren(icon("trash"), text);
  }

  function askRemove(name) {
    const agent = state.agents.find((a) => a.name === name);
    if (!agent) return;
    const chat = state.chats.get(name);
    if (chat && chat.busy) {
      addSystem(chat, "Wait until the agent has finished before removing it.", "warn");
      toast("Still working", `Wait until ${pretty(name)} has finished, or press Stop.`, "warn");
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
    setConfirmLabel("Move to Trash");
    removeDialog.showModal();
  }

  async function confirmRemove(event) {
    event.preventDefault();
    const name = removing;
    if (!name) return;
    const button = $("remove-confirm");
    button.disabled = true;
    setConfirmLabel("Moving...");
    try {
      const url = `/api/agents/${encodeURIComponent(name)}?notes=${$("remove-notes").checked ? "true" : "false"}`;
      const response = await fetch(url, { method: "DELETE", headers: { "X-AgentFactory": "1" } });
      if (!response.ok) {
        let detail = "";
        try { detail = (await response.json()).detail; } catch { /* no details */ }
        throw new Error(detail || `The server answered ${response.status}.`);
      }
      const result = await response.json().catch(() => ({}));
      removeDialog.close();
      if (state.current === name) deselect();
      toast(`${pretty(name)} has left`, `specs/${result.file || `${name}.yaml`} is in the Trash${result.notes_moved ? ", with its notes" : ""}.`, "info", { icon: "trash" });
      await loadAgents();
    } catch (error) {
      $("remove-error").textContent = error.message;
      $("remove-error").hidden = false;
      button.disabled = false;
      setConfirmLabel("Try again");
    }
  }

  function hideMenu() {
    deskMenu.hidden = true;
  }

  function showDeskMenu(name, x, y) {
    deskMenu.replaceChildren(
      el("button", { type: "button", role: "menuitem", onclick: () => { hideMenu(); selectAgent(name); } }, icon("chat"), `Chat with ${pretty(name)}`),
      el("button", { type: "button", role: "menuitem", onclick: () => { hideMenu(); openStaff(name); } }, icon("file"), "Staff file"),
      el("hr"),
      el("button", { type: "button", role: "menuitem", class: "danger", onclick: () => { hideMenu(); askRemove(name); } }, icon("trash"), "Remove agent..."));
    deskMenu.hidden = false;
    // open beside the point so the desk it belongs to stays visible
    const left = x + 14 + deskMenu.offsetWidth > window.innerWidth - 8 ? x - deskMenu.offsetWidth - 14 : x + 14;
    deskMenu.style.left = `${Math.max(8, left)}px`;
    deskMenu.style.top = `${Math.max(8, Math.min(y - 12, window.innerHeight - deskMenu.offsetHeight - 8))}px`;
    deskMenu.firstElementChild.focus();
  }

  function menuKeys(menu, onClose) {
    menu.addEventListener("keydown", (event) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); onClose(); return; }
      if (event.key === "Tab") { onClose(); return; }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const items = [...menu.querySelectorAll("button:not(:disabled)")];
      let next = items.indexOf(document.activeElement);
      if (event.key === "Home") next = 0;
      else if (event.key === "End") next = items.length - 1;
      else next = (next + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      items[next].focus();
    });
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
      { group: "Do", label: "Open the crew list", hint: "Every agent in the office", run: () => Shell.openSheet("crew") },
      { group: "Do", label: "Open the activity log", hint: "Every step the agents took", run: () => Shell.openSheet("log") },
      { group: "Do", label: "Refresh the agent list", hint: "Look for new or removed agent files", run: () => { loadConfig(); loadAgents(); } },
      { group: "Do", label: "Check Ollama again", run: loadConfig },
      { group: "Do", label: "Next time of day", hint: "Morning, afternoon, sunset, dusk, night", run: () => Office.cycleTime() },
      { group: "Do", label: "Clear the activity log", run: clearLog },
      { group: "Help", label: "Keyboard shortcuts", hint: "Press ? any time", run: () => Shell.openHelp() },
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
    if (!text.trim() && !chat.pending.length) return;
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
  $("stop-btn").addEventListener("click", stopTurn);
  $("notes-btn").addEventListener("click", toggleNotes);
  $("cards-btn").addEventListener("click", toggleCards);
  $("cards-reveal").addEventListener("change", () => { if (cardsData) renderCards($("cards-list"), cardsData, { reveal: $("cards-reveal").checked }); });
  $("staff-btn").addEventListener("click", () => { if (state.current) openStaff(state.current); });
  $("tools-btn").addEventListener("click", toggleTools);
  $("chat-more").addEventListener("click", () => (chatMenu.hidden ? openChatMenu() : closeChatMenu()));
  $("new-chat-btn").addEventListener("click", () => { closeChatMenu(); newChat(); $("composer-input").focus(); });
  $("clear-log").addEventListener("click", clearLog);
  $("log-filter").addEventListener("change", applyLogFilter);
  $("close-chat").addEventListener("click", () => { closeChatMenu(); closeNotes(); deselect(); $("office").focus(); });
  $("refresh-agents").addEventListener("click", () => { loadConfig(); loadAgents(); });
  $("new-agent-btn").addEventListener("click", () => Nova.hire());
  $("attach-btn").addEventListener("click", () => $("attach-input").click());
  $("attach-input").addEventListener("change", (event) => { addFiles(currentChat(), [...event.target.files]); event.target.value = ""; });
  const chatBox = $("chat-section");
  const hasFiles = (event) => [...((event.dataTransfer && event.dataTransfer.types) || [])].includes("Files");
  chatBox.addEventListener("dragover", (event) => { if (hasFiles(event) && currentChat()) { event.preventDefault(); chatBox.classList.add("is-dropping"); } });
  chatBox.addEventListener("dragleave", (event) => { if (!chatBox.contains(event.relatedTarget)) chatBox.classList.remove("is-dropping"); });
  chatBox.addEventListener("drop", (event) => {
    chatBox.classList.remove("is-dropping");
    if (!hasFiles(event)) return;
    event.preventDefault();
    addFiles(currentChat(), [...event.dataTransfer.files]);
  });
  // a file dropped anywhere else must not make the browser leave the page
  window.addEventListener("dragover", (event) => { if (hasFiles(event)) event.preventDefault(); });
  window.addEventListener("drop", (event) => { if (hasFiles(event)) event.preventDefault(); });
  $("empty-hire").addEventListener("click", () => Nova.hire());
  $("empty-nova-btn").addEventListener("click", () => Nova.menu());
  document.addEventListener("agentfactory:hired", (event) => {
    state.hired.set(event.detail.name, event.detail.goal);
    loadAgents();
  });
  $("ollama-pill").addEventListener("click", loadConfig);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!chatMenu.hidden) { closeChatMenu(true); return; }
    if (!$("tools-pop").hidden) { closeTools(); $("tools-btn").focus(); return; }
    closeNotes();
    closeCards();
    hideMenu();
  });
  document.addEventListener("pointerdown", (event) => {
    if (!deskMenu.hidden && !deskMenu.contains(event.target)) hideMenu();
    if (!chatMenu.hidden && !chatMenu.contains(event.target) && !$("chat-more").contains(event.target)) closeChatMenu();
    if (!$("tools-pop").hidden && !$("tools-pop").contains(event.target) && !$("tools-btn").contains(event.target)) closeTools();
  });
  menuKeys(deskMenu, hideMenu);
  menuKeys(chatMenu, () => closeChatMenu(true));
  $("remove-btn").addEventListener("click", () => { closeChatMenu(); if (state.current) askRemove(state.current); });
  $("remove-form").addEventListener("submit", confirmRemove);
  $("remove-cancel").addEventListener("click", () => removeDialog.close());
  removeDialog.addEventListener("close", () => { removing = null; });
  window.addEventListener("focus", () => { loadConfig(); loadAgents(); });
  // the state line follows the agent as it walks between the lounge and its desk
  setInterval(() => { if (state.current && !document.hidden) renderState(); }, 1000);

  Office.init({
    canvas: $("office"),
    tip: $("office-tip"),
    live: $("office-live"),
    onPick: selectAgent,
    onGuide: () => Nova.menu(),
    onMenu: showDeskMenu,
    onBoard: () => Shell.openSheet("crew"),
  });
  Office.portrait($("empty-nova"), Office.guide.look);
  Hire.init({ colorOf });
  Staff.init({
    onChat: selectAgent,
    onRemove: askRemove,
    look: (name) => ({ label: pretty(name), color: colorOf(name), hair: (custom.get(name) || {}).hair || null }),
  });
  Palette.init({ items: paletteItems });
  loadConfig();
  loadAgents().then(() => { Nova.boot(); pollRun(); });
  setInterval(() => { if (!document.hidden) loadAgents(); }, 8000); // new or removed spec files show up on their own
})();
