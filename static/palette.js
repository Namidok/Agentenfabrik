"use strict";

// Ctrl+K / Cmd+K: type to find an agent or an action and jump straight to it.
// app.js supplies the list each time it opens, so it is always up to date.

(() => {
  const $ = (id) => document.getElementById(id);
  const MAX = 12;
  let dlg, input, listEl, provider = () => [], shown = [], active = 0;

  function matches(items, query) {
    const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) return items.slice(0, MAX);
    const scored = [];
    items.forEach((item, index) => {
      const label = item.label.toLowerCase();
      const hay = `${label} ${(item.hint || "").toLowerCase()} ${item.group.toLowerCase()}`;
      if (!terms.every((t) => hay.includes(t))) return;
      scored.push({ item, index, s: label.startsWith(terms[0]) ? 0 : label.includes(terms[0]) ? 1 : 2 });
    });
    scored.sort((a, b) => a.s - b.s || a.index - b.index);
    return scored.slice(0, MAX).map((x) => x.item);
  }

  function paint() {
    const children = shown.map((item, i) => {
      const li = document.createElement("li");
      li.id = `palette-opt-${i}`;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", String(i === active));
      if (i === active) li.classList.add("is-active");
      const main = document.createElement("span");
      main.className = "palette-main";
      const label = document.createElement("strong");
      label.textContent = item.label;
      main.append(label);
      if (item.hint) {
        const hint = document.createElement("small");
        hint.textContent = item.hint;
        main.append(hint);
      }
      const group = document.createElement("span");
      group.className = "palette-group";
      group.textContent = item.group;
      li.append(main, group);
      li.addEventListener("pointermove", () => { if (active !== i) { active = i; paint(); } });
      li.addEventListener("click", () => run(i));
      return li;
    });
    if (!children.length) {
      const li = document.createElement("li");
      li.className = "palette-empty";
      li.textContent = `Nothing matches "${input.value.trim()}"`;
      children.push(li);
    }
    listEl.replaceChildren(...children);
    if (shown.length) input.setAttribute("aria-activedescendant", `palette-opt-${active}`);
    else input.removeAttribute("aria-activedescendant");
    const current = listEl.children[active];
    if (current && current.scrollIntoView) current.scrollIntoView({ block: "nearest" });
  }

  function refresh() {
    shown = matches(provider(), input.value);
    active = Math.min(active, Math.max(0, shown.length - 1));
    paint();
  }

  function run(i) {
    const item = shown[i];
    if (!item) return;
    dlg.close();
    setTimeout(item.run, 0);
  }

  function open() {
    if (!dlg || dlg.open || document.querySelector("dialog[open]")) return;
    input.value = "";
    active = 0;
    dlg.showModal();
    refresh();
    input.focus();
  }

  function init(options) {
    provider = options.items;
    dlg = $("palette-dialog");
    input = $("palette-input");
    listEl = $("palette-list");
    const mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
    for (const node of document.querySelectorAll(".kbd-hint")) node.textContent = mac ? "⌘K" : "Ctrl K";
    input.addEventListener("input", () => { active = 0; refresh(); });
    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (!shown.length) return;
        active = (active + (event.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length;
        paint();
      } else if (event.key === "Enter" && !event.isComposing) {
        event.preventDefault();
        run(active);
      }
    });
    document.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (dlg.open) dlg.close(); else open();
      }
    });
    $("palette-btn").addEventListener("click", open);
  }

  window.Palette = { init, open };
})();
