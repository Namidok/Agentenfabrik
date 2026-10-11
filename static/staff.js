"use strict";

// The staff file: one agent's job, instructions, tools, permissions and limits on a single page,
// plus its saved notes and the raw agent file. Read-only. Everything is set with textContent.

(() => {
  const $ = (id) => document.getElementById(id);
  let dlg, handlers = {}, current = null, fileText = "";

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

  const section = (title, ...kids) => el("section", { class: "hire-section" }, el("h3", { text: title }), ...kids);
  const facts = (rows) => el("dl", { class: "summary" }, rows.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })]));
  const list = (items, none) => (items && items.length ? items.join(", ") : none);

  async function fetchJSON(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${response.status}`);
    return response.json();
  }

  async function copy(text, button, label) {
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = "Copied";
    } catch {
      button.textContent = "Could not copy";
    }
    setTimeout(() => { button.textContent = label; }, 1500);
  }

  // One tab per question you might have about an agent.
  let tabs = [], active = 0;

  function showTab(i, focus = false) {
    active = i;
    tabs.forEach((tab, k) => {
      tab.button.setAttribute("aria-selected", String(k === i));
      tab.button.tabIndex = k === i ? 0 : -1;
      tab.panel.hidden = k !== i;
    });
    if (focus) tabs[i].button.focus();
    $("staff-body").scrollTop = 0;
  }

  function setTabs(list) {
    tabs = list.map(([title, kids], i) => {
      const button = el("button", { type: "button", class: "tab", role: "tab", id: `staff-tab-${i}`, "aria-controls": `staff-panel-${i}`, text: title,
        onclick: () => showTab(i) });
      const panel = el("div", { class: "staff-panel", role: "tabpanel", id: `staff-panel-${i}`, "aria-labelledby": `staff-tab-${i}`, tabindex: "0" }, kids);
      return { button, panel };
    });
    $("staff-tabs").replaceChildren(...tabs.map((x) => x.button));
    $("staff-body").replaceChildren(...tabs.map((x) => x.panel));
    showTab(Math.min(active, tabs.length - 1));
  }

  function render(agent, extras, file, notes, cards) {
    const p = agent.permissions || {}, l = agent.limits || {};
    const overview = [];
    if (agent.warnings && agent.warnings.length) {
      overview.push(el("div", { class: "callout is-warn" }, el("strong", { text: "Worth knowing" }),
        el("ul", {}, agent.warnings.map((w) => el("li", { text: w })))));
    }
    overview.push(section("Job",
      el("p", { class: "staff-text", text: agent.goal }),
      facts([["Style", agent.mode === "task" ? "Task agent: every message is a fresh job" : "Chat agent: a conversation that remembers what was said"],
        ["Model", `${agent.model}, ${agent.model_source === "spec" ? "named in this agent's file" : "the default from settings.yaml"}` +
          (agent.model_installed === false ? `. Not installed: run ollama pull ${agent.model}` : "")]])));
    overview.push(section("Limits", facts([
      ["Steps per run", String(l.max_steps)],
      ["Tokens per run", Number(l.max_tokens).toLocaleString()],
      ["Time per run", `${l.max_runtime_s} seconds`],
      ["Last run", extras && extras.lastRun
        ? `${extras.lastRun.tokens.toLocaleString()} tokens, ${extras.lastRun.steps} step${extras.lastRun.steps === 1 ? "" : "s"}, ${extras.lastRun.seconds}s${extras.lastRun.ok ? "" : " (stopped early)"}`
        : "Not run in this session"],
    ])));
    const instructions = [section("Instructions",
      el("p", { class: "staff-text", text: file && file.system_prompt ? file.system_prompt : "None written. It follows its goal and nothing else." }))];
    const tools = [section("Tools",
      agent.tools.length
        ? el("div", { class: "chips" }, agent.tools.map((t) => el("span", { class: `chip${agent.missing_tools.includes(t) ? " warn" : ""}`, text: t,
          title: agent.missing_tools.includes(t) ? "Not built yet, so this agent cannot run" : `Tool: ${t}` })))
        : el("p", { class: "staff-text", text: "None. This agent can only talk." })),
    section("Permissions", facts([
      ["May read", list(p.fs_read, "Nothing")],
      ["May write", list(p.fs_write, "Nothing") + (p.allow_overwrite ? " (may replace existing files)" : "")],
      ["Websites", list(p.network, "None")],
      ["Runs code", p.shell ? "Yes, on this computer, not isolated" : "No"],
    ]))];
    const pages = [["Overview", overview], ["Instructions", instructions], ["Tools", tools]];
    if (agent.memory && agent.memory.srs && cards) {
      const listNode = el("ul", { class: "flashcards" });
      if (window.Cards) window.Cards.render(listNode, cards, { reveal: true });
      pages.push(["Cards", [section(cards.total ? `Flashcards: ${cards.total}, ${cards.due_today} due now` : "Flashcards", listNode)]]);
    }
    if (agent.memory && agent.memory.notes) {
      pages.push(["Notes", [section("Saved notes", el("pre", { class: "staff-pre", text: notes ? notes : "Nothing saved yet." }))]]);
    }
    if (file) {
      const copyYaml = el("button", { type: "button", class: "btn btn-sm btn-secondary", text: "Copy file text" });
      copyYaml.addEventListener("click", () => copy(file.yaml, copyYaml, "Copy file text"));
      const copyPath = el("button", { type: "button", class: "btn btn-sm btn-secondary", text: "Copy path" });
      copyPath.addEventListener("click", () => copy(file.path, copyPath, "Copy path"));
      pages.push(["File", [section("Agent file",
        el("p", { class: "staff-text" }, el("code", { text: file.path }), " ", el("span", { class: "hint", text: "Edit this file and press Refresh to change the agent." })),
        el("div", { class: "hire-row" }, copyPath, copyYaml),
        el("pre", { class: "staff-pre", text: file.yaml }))]]);
    }
    setTabs(pages);
  }

  async function open(agent, extras = {}) {
    if (!dlg || !agent) return;
    current = agent;
    const look = handlers.look ? handlers.look(agent.name) : { label: agent.name, color: "#8c7cf6", hair: null };
    const face = document.createElement("canvas");
    Office.portrait(face, { name: agent.name, color: look.color, hair: look.hair });
    $("staff-avatar").replaceChildren(face);
    $("staff-avatar").style.setProperty("--accent", look.color);
    $("staff-title").textContent = look.label;
    $("staff-sub").textContent = `Staff file · ${agent.mode === "task" ? "Task agent" : "Chat agent"}`;
    active = 0;
    $("staff-tabs").replaceChildren();
    $("staff-body").replaceChildren(el("div", { class: "hire-section", "aria-busy": "true" },
      el("span", { class: "skeleton skeleton-line", style: "width:40%" }), el("span", { class: "skeleton skeleton-line" }),
      el("span", { class: "skeleton skeleton-line", style: "width:85%" }), el("span", { class: "skeleton skeleton-line", style: "width:60%" })));
    if (!dlg.open) dlg.showModal();
    let file = null, notes = "";
    try { file = await fetchJSON(`/api/agents/${agent.name}/file`); } catch { /* shown without the file */ }
    if (agent.memory && agent.memory.notes) {
      try { notes = (await fetchJSON(`/api/agents/${agent.name}/notes`)).notes.trim(); } catch { /* none */ }
    }
    let cards = null;
    if (agent.memory && agent.memory.srs && window.Cards) {
      try { cards = await window.Cards.fetch(agent.name); } catch { /* shown without cards */ }
    }
    if (current !== agent) return; // closed or replaced while loading
    fileText = file ? file.yaml : "";
    render(agent, extras, file, notes, cards);
  }

  function init(options) {
    dlg = $("staff-dialog");
    handlers = options;
    $("staff-x").addEventListener("click", () => dlg.close());
    $("staff-chat").addEventListener("click", () => { const a = current; dlg.close(); if (a && handlers.onChat) handlers.onChat(a.name); });
    $("staff-remove").addEventListener("click", () => { const a = current; dlg.close(); if (a && handlers.onRemove) handlers.onRemove(a.name); });
    dlg.addEventListener("close", () => { current = null; });
    $("staff-tabs").addEventListener("keydown", (event) => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
      if (event.key === "Home" || event.key === "End") { event.preventDefault(); showTab(event.key === "Home" ? 0 : tabs.length - 1, true); }
      else if (step && tabs.length) { event.preventDefault(); showTab((active + step + tabs.length) % tabs.length, true); }
    });
  }

  window.Staff = { init, open };
})();
