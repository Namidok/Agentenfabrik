"use strict";

// The hiring popup. You fill in a form (or describe the agent and let Nova fill it in), review
// the blueprint with its permission warnings, and approve. Only then is the agent file written.
// Everything the model drafts goes into form fields or textContent, never innerHTML.

(() => {
  const $ = (id) => document.getElementById(id);
  const COLORS = [
    ["#8c7cf6", "Violet"], ["#2ec4a0", "Teal"], ["#ff7d70", "Coral"], ["#fdcb6e", "Amber"],
    ["#4da3ff", "Blue"], ["#f78fb3", "Pink"], ["#7bd88f", "Green"], ["#ff9f5a", "Orange"],
  ];
  const HAIRS = [
    ["#3b2a20", "Brown"], ["#2d1f17", "Dark brown"], ["#8a4b2b", "Auburn"], ["#e0b34a", "Blond"],
    ["#1c1c28", "Black"], ["#a03a6a", "Magenta"], ["#4b6fd6", "Blue"], ["#d8d8e8", "Silver"],
  ];
  const TOOL_NAMES = {
    "fs.list": "Look inside folders", "fs.read": "Read text files", "fs.write": "Create files",
    "fs.move": "Move files", "http.fetch": "Read web pages", "notes.read": "Read its own notes",
    "notes.append": "Remember things", "code.run": "Compile and run C++", "code.check_name": "Check C++ names",
    "srs.add": "Add flashcards", "srs.due": "Find due flashcards", "srs.review": "Record reviews",
  };
  const FIELD_IDS = {
    name: "hire-name", display_name: "hire-name", goal: "hire-goal", system_prompt: "hire-prompt",
    mode: "hire-mode-chat", fs_read: "hire-read", fs_write: "hire-write", network: "hire-net",
    color: "hire-colors", hair: "hire-hairs", tools: "hire-tools",
  };
  const FIELD_LABELS = {
    name: "Name", display_name: "Name", goal: "Goal", system_prompt: "Instructions", mode: "Style",
    fs_read: "Folders it may read", fs_write: "Folders it may write", network: "Websites", tools: "Tools",
    color: "Shirt colour", hair: "Hair colour",
  };

  let blocked = false, dlg, form, options = null, colorOf = () => "#8c7cf6", callback = null, draftAbort = null, busy = false, inited = false;

  const slugOf = (text) => {
    let s = text.toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    if (s && !/^[a-z]/.test(s)) s = `agent-${s}`;
    return s.slice(0, 41).replace(/-+$/, "");
  };
  const prettySlug = (slug) => slug.split("-").map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w)).join(" ");
  const lines = (text) => text.split("\n").map((l) => l.trim()).filter(Boolean);

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

  // ---------- reading and writing the form ----------

  const toolBoxes = () => [...document.querySelectorAll("#hire-tools input[type=checkbox]")];
  const picked = () => toolBoxes().filter((b) => b.checked).map((b) => b.value);
  const needsOf = () => new Set(toolBoxes().filter((b) => b.checked).map((b) => b.dataset.needs).filter(Boolean));
  const radio = (name) => { const r = document.querySelector(`input[name="${name}"]:checked`); return r ? r.value : ""; };

  function payload() {
    const needs = needsOf();
    const display = $("hire-name").value.trim();
    return {
      name: slugOf(display),
      display_name: display,
      goal: $("hire-goal").value.trim(),
      system_prompt: $("hire-prompt").value.trim(),
      mode: radio("hire-mode") || "conversational",
      tools: picked(),
      fs_read: needs.has("fs_read") ? lines($("hire-read").value) : [],
      fs_write: needs.has("fs_write") ? lines($("hire-write").value) : [],
      network: needs.has("network") ? lines($("hire-net").value) : [],
      allow_overwrite: needs.has("fs_write") && $("hire-overwrite").checked,
      color: radio("hire-color") || null,
      hair: radio("hire-hair") || null,
    };
  }

  function fill(fields) {
    if (fields.name) $("hire-name").value = fields.display_name || prettySlug(fields.name);
    if (fields.goal) $("hire-goal").value = fields.goal;
    $("hire-prompt").value = fields.system_prompt || "";
    const mode = document.querySelector(`input[name="hire-mode"][value="${fields.mode}"]`);
    if (mode) mode.checked = true;
    const wanted = new Set(fields.tools || []);
    for (const box of toolBoxes()) box.checked = wanted.has(box.value);
    $("hire-read").value = (fields.fs_read || []).join("\n");
    $("hire-write").value = (fields.fs_write || []).join("\n");
    $("hire-net").value = (fields.network || []).join("\n");
    $("hire-overwrite").checked = !!fields.allow_overwrite;
    refresh();
  }

  // Shows only the permission boxes the chosen tools need, and keeps the preview current.
  function refresh() {
    const needs = needsOf();
    const names = picked();
    $("hire-read-row").hidden = !needs.has("fs_read");
    $("hire-write-row").hidden = !needs.has("fs_write");
    $("hire-net-row").hidden = !needs.has("network");
    $("hire-shell-note").hidden = !needs.has("shell");
    $("hire-notes-note").hidden = !names.some((n) => n.startsWith("notes."));
    const slug = slugOf($("hire-name").value);
    $("hire-slug").textContent = slug ? `Saved as ${slug}.yaml` : "Use letters or numbers. This becomes the file name.";
    const max = options ? options.max_tools : 6;
    const full = names.length >= max;
    $("hire-tool-count").textContent = `${names.length} of ${max} chosen`;
    for (const box of toolBoxes()) box.disabled = full && !box.checked;
    const label = $("hire-name").value.trim() || "New agent";
    Office.portrait($("hire-preview-face"), { name: slug || "new-agent", color: radio("hire-color") || colorOf(slug || "new-agent"), hair: radio("hire-hair") || null });
    $("hire-preview-name").textContent = label;
  }

  // ---------- messages ----------

  function showError(message, errors = []) {
    const box = $("hire-error");
    box.replaceChildren();
    const shown = errors.length ? errors : [{ field: "", message }];
    box.append(...shown.map((e) => el("div", { text: (FIELD_LABELS[e.field] ? `${FIELD_LABELS[e.field]}: ` : "") + e.message })));
    box.hidden = false;
    for (const input of document.querySelectorAll("#hire-form [aria-invalid]")) input.removeAttribute("aria-invalid");
    const first = errors.find((e) => FIELD_IDS[e.field]);
    if (first) {
      const target = $(FIELD_IDS[first.field]);
      const focusable = target.matches("input, textarea, select, button") ? target : target.querySelector("input, textarea");
      if (focusable) { focusable.setAttribute("aria-invalid", "true"); focusable.focus(); }
    }
  }
  const clearError = () => { $("hire-error").hidden = true; $("hire-error").replaceChildren(); };

  async function post(url, body, signal) {
    let response;
    try {
      response = await fetch(url, {
        method: "POST", signal,
        headers: { "Content-Type": "application/json", "X-AgentFactory": "1" },
        body: JSON.stringify(body),
      });
    } catch (e) {
      if (e.name === "AbortError") throw e;
      throw Object.assign(new Error("Could not reach the server."), { errors: [] });
    }
    let data = {};
    try { data = await response.json(); } catch { /* not JSON */ }
    if (!response.ok) {
      const detail = typeof data.detail === "string" ? data.detail : "Some of the answers are not valid.";
      throw Object.assign(new Error(detail), { errors: Array.isArray(data.errors) ? data.errors : [], status: response.status });
    }
    return data;
  }

  // ---------- local checks, so mistakes are caught before a round trip ----------

  function localProblems(p) {
    const problems = [];
    if (!p.name) problems.push({ field: "name", message: "Give the agent a name. It needs at least 3 letters or numbers." });
    else if (p.name.length < 3) problems.push({ field: "name", message: "The name needs at least 3 letters or numbers." });
    if (p.goal.length < 10) problems.push({ field: "goal", message: "Say what it should do in at least one short sentence." });
    const needs = needsOf();
    if (needs.has("fs_read") && !p.fs_read.length) problems.push({ field: "fs_read", message: "Add at least one folder, or switch off the tools that read files." });
    if (needs.has("fs_write") && !p.fs_write.length) problems.push({ field: "fs_write", message: "Add at least one folder, or switch off the tools that create files." });
    if (needs.has("network") && !p.network.length) problems.push({ field: "network", message: "Add at least one website, or switch off the web tool." });
    return problems;
  }

  // ---------- steps ----------

  function setStep(step) {
    $("hire-step-form").hidden = step !== "form";
    $("hire-step-review").hidden = step !== "review";
    $("hire-actions-form").hidden = step !== "form";
    $("hire-actions-review").hidden = step !== "review";
    $("hire-title").textContent = step === "form" ? "Hire a new agent" : "Review the blueprint";
    $("hire-sub").textContent = step === "form"
      ? "Tell Nova what you need. You can change everything later in the agent's file."
      : "Nothing is saved until you approve. Check the permissions first.";
    $("hire-body").scrollTop = 0;
  }

  function setBusy(on, label) {
    busy = on;
    for (const id of ["hire-review-btn", "hire-approve", "hire-back"]) $(id).disabled = on;
    $("hire-approve").replaceChildren(window.Icons ? Icons.el(on ? "queue" : "check") : "", on && label ? label : "Approve and hire");
  }

  async function review() {
    clearError();
    const p = payload();
    const problems = localProblems(p);
    if (problems.length) return showError("", problems);
    setBusy(true);
    blocked = false;
    try {
      const data = await post("/api/hire/preview", p);
      renderReview(p, data);
      setStep("review");
    } catch (e) {
      showError(e.message, e.errors || []);
    } finally {
      setBusy(false);
      $("hire-approve").disabled = blocked;
    }
    if (!$("hire-step-review").hidden) (blocked ? $("hire-back") : $("hire-approve")).focus();
  }

  function renderReview(p, data) {
    Office.portrait($("hire-review-face"), { name: data.name, color: p.color || colorOf(data.name), hair: p.hair });
    $("hire-review-name").textContent = p.display_name || prettySlug(data.name);
    $("hire-review-goal").textContent = p.goal;
    const rows = [
      ["File", `specs/${data.file}`],
      ["Style", p.mode === "task" ? "Task agent: every message is a fresh job" : "Chat agent: a conversation that remembers what was said"],
      ["Tools", p.tools.length ? p.tools.join(", ") : "None. It can only talk."],
      ["May read", p.fs_read.length ? p.fs_read.join(", ") : "Nothing"],
      ["May write", p.fs_write.length ? p.fs_write.join(", ") : "Nothing"],
      ["Websites", p.network.length ? p.network.join(", ") : "None"],
    ];
    $("hire-summary").replaceChildren(...rows.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })]));
    const warn = $("hire-warnings");
    warn.replaceChildren(...data.warnings.map((w) => el("li", { text: w })));
    $("hire-warn-box").hidden = !data.warnings.length;
    const notes = $("hire-notes");
    notes.replaceChildren(...data.notes.map((n) => el("li", { text: n })));
    $("hire-notes-box").hidden = !data.notes.length;
    $("hire-yaml").textContent = data.yaml;
    if (data.exists) showError(`An agent called ${data.name} already exists. Go back and choose another name.`);
    blocked = !!data.exists;
  }

  async function approve() {
    clearError();
    const p = payload();
    setBusy(true, "Hiring...");
    try {
      const agent = await post("/api/hire", p);
      const done = callback;
      callback = null;
      setBusy(false);
      resetForm();
      dlg.close("hired");
      document.dispatchEvent(new CustomEvent("agentfactory:hired", { detail: { name: agent.name, goal: agent.goal, label: p.display_name } }));
      if (done) done({ name: agent.name, label: p.display_name || prettySlug(agent.name), goal: agent.goal });
    } catch (e) {
      setBusy(false);
      if (e.status === 409) setStep("form");
      showError(e.message, e.errors || []);
    }
  }

  async function draft() {
    clearError();
    const description = $("hire-describe").value.trim();
    if (description.length < 10) return showError("Describe in a sentence or two what the agent should do.");
    if (draftAbort) { draftAbort.abort(); return; }
    draftAbort = new AbortController();
    const button = $("hire-draft");
    button.textContent = "Stop";
    $("hire-draft-status").textContent = "Nova is thinking. The first answer can take a minute while the model loads.";
    try {
      const data = await post("/api/hire/draft", { description }, draftAbort.signal);
      fill(data.fields);
      const notes = data.notes && data.notes.length ? ` Heads up: ${data.notes.join(" ")}` : "";
      $("hire-draft-status").textContent = `Done. Please check the tools and folders below, then press Review.${notes}`;
    } catch (e) {
      $("hire-draft-status").textContent = "";
      if (e.name !== "AbortError") showError(e.message, []);
    } finally {
      draftAbort = null;
      button.textContent = "Let Nova fill in the form";
    }
  }

  function resetForm() {
    form.reset();
    $("hire-draft-status").textContent = "";
    clearError();
    setStep("form");
    refresh();
  }

  // ---------- setup ----------

  function swatches(container, name, list, withAuto) {
    const items = [];
    if (withAuto) {
      items.push(el("label", { class: "swatch is-auto", title: "Chosen from the name" },
        el("input", { type: "radio", name, value: "", checked: true, "aria-label": "Automatic" }), el("span", { text: "A" })));
    }
    for (const [value, label] of list) {
      items.push(el("label", { class: "swatch", title: label },
        el("input", { type: "radio", name, value, "aria-label": label }), el("span", { style: `background:${value}` })));
    }
    container.replaceChildren(...items);
  }

  async function loadOptions() {
    if (options) return;
    try {
      const response = await fetch("/api/hire/options");
      if (!response.ok) throw new Error(String(response.status));
      options = await response.json();
    } catch {
      showError("Could not load the list of tools. Is the server still running?");
      return;
    }
    $("hire-tools").replaceChildren(...options.tools.map((tool) =>
      el("label", { class: "tool" },
        el("input", { type: "checkbox", value: tool.id, "data-needs": tool.needs || (tool.id.startsWith("code.") ? "shell" : "") }),
        el("span", { class: "tool-text" },
          el("strong", { text: TOOL_NAMES[tool.id] || tool.id }),
          el("small", { text: `${tool.id}: ${tool.description}` })))));
    for (const box of toolBoxes()) box.addEventListener("change", refresh);
    refresh();
  }

  function open(cb) {
    if (!inited) return;
    callback = cb || null;
    if (!dlg.open) dlg.showModal();
    setStep("form");
    loadOptions();
    refresh();
    $("hire-describe").focus();
  }

  function init(helpers) {
    if (inited) return;
    colorOf = helpers.colorOf;
    dlg = $("hire-dialog");
    form = $("hire-form");
    swatches($("hire-colors"), "hire-color", COLORS, true);
    swatches($("hire-hairs"), "hire-hair", HAIRS, true);
    Office.portrait($("hire-nova"), Office.guide.look);
    form.addEventListener("submit", (event) => event.preventDefault());
    form.addEventListener("input", refresh);
    form.addEventListener("change", refresh);
    $("hire-draft").addEventListener("click", draft);
    $("hire-review-btn").addEventListener("click", review);
    $("hire-back").addEventListener("click", () => { clearError(); setStep("form"); $("hire-name").focus(); });
    $("hire-approve").addEventListener("click", approve);
    $("hire-cancel").addEventListener("click", () => dlg.close("cancel"));
    $("hire-x").addEventListener("click", () => dlg.close("cancel"));
    $("hire-clear").addEventListener("click", () => { resetForm(); $("hire-describe").focus(); });
    dlg.addEventListener("cancel", (event) => { if (busy) event.preventDefault(); });
    dlg.addEventListener("close", () => {
      if (draftAbort) draftAbort.abort();
      if (dlg.returnValue !== "hired" && callback) { const done = callback; callback = null; done(null); }
      dlg.returnValue = "";
    });
    inited = true;
    refresh();
  }

  window.Hire = { init, open };
})();
