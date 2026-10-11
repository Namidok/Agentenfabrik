"use strict";

// The shell around the full-screen office: the sheets that slide in, the time-of-day chip, the colour
// theme that follows the office's own clock, the keyboard shortcuts and the shortcut list.

(() => {
  const $ = (id) => document.getElementById(id);
  const html = document.documentElement;

  // ---------- sheets ----------

  const sheets = {
    crew: { btn: "dock-crew", box: () => document.querySelector(".col-left") },
    log: { btn: "dock-log", box: () => document.querySelector(".col-right") },
  };
  let returnFocus = null;

  const isOpen = (key) => sheets[key].box().classList.contains("open");

  function setSheet(key, open, { focus = true } = {}) {
    const s = sheets[key], box = s.box(), btn = $(s.btn);
    if (box.classList.contains("open") === open) return;
    box.classList.toggle("open", open);
    btn.setAttribute("aria-expanded", String(open));
    if (open) {
      if (key === "log") btn.classList.remove("ping");
      returnFocus = document.activeElement;
      // wait for the slide-in to make the sheet visible, then move focus into it
      if (focus) setTimeout(() => box.querySelector(".agent-card, select, button")?.focus({ preventScroll: true }), 60);
    } else if (box.contains(document.activeElement)) {
      (returnFocus && document.contains(returnFocus) ? returnFocus : btn).focus({ preventScroll: true });
    }
  }

  function closeSheets(except) {
    for (const key of Object.keys(sheets)) if (key !== except) setSheet(key, false);
  }

  function toggleSheet(key, options) {
    const open = !isOpen(key);
    if (open) closeSheets(key);
    setSheet(key, open, options);
  }

  // ---------- time ----------

  function applyTime(d) {
    html.dataset.time = d.theme;
    // the area around the picture continues the room's own wall and floor
    if (d.wall) html.style.setProperty("--world-wall", d.wall);
    if (d.floor) {
      html.style.setProperty("--world-floor", d.floor);
      html.style.setProperty("--world-trim", window.Pixel ? Pixel.shade(d.floor, 0.62) : d.floor);
    }
    const chip = $("time-chip");
    if (!chip) return;
    const icon = chip.querySelector(".ico");
    icon.classList.toggle("ico-moon", d.dark > 0.5);
    icon.classList.toggle("ico-sun", !(d.dark > 0.5));
    chip.querySelector("b").textContent = d.label;
    chip.querySelector("small").textContent = d.preview ? "Preview" : d.clock;
    chip.title = d.preview
      ? "Showing a preview of the time of day. Click for the next one; it ends with the live clock."
      : "Click to preview morning, afternoon, sunset, dusk and night";
    chip.setAttribute("aria-label", `Time of day: ${d.label.toLowerCase()}${d.preview ? " (preview)" : ""}. Click to change.`);
  }

  document.addEventListener("agentfactory:time", (e) => applyTime(e.detail));

  // ---------- keyboard shortcuts ----------

  const typing = (t) => t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
  const dialogOpen = () => !!document.querySelector("dialog[open]");

  function openHelp() {
    const dlg = $("help-dialog");
    if (dlg && !dlg.open) dlg.showModal();
  }

  function onKey(e) {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "Escape") { closeSheets(null); return; }
    if (typing(e.target) || dialogOpen()) return;
    if (e.key === "?") { e.preventDefault(); openHelp(); }
    else if (e.key === "c" || e.key === "C") { e.preventDefault(); toggleSheet("crew"); }
    else if (e.key === "l" || e.key === "L") { e.preventDefault(); toggleSheet("log"); }
    else if (e.key === "h" || e.key === "H") { e.preventDefault(); if (window.Nova) Nova.hire(); }
  }

  function init() {
    for (const [key, s] of Object.entries(sheets)) {
      $(s.btn).addEventListener("click", () => toggleSheet(key));
      s.box().querySelector("[data-sheet-close]")?.addEventListener("click", () => setSheet(key, false));
    }
    $("dock-hire").addEventListener("click", () => { if (window.Nova) Nova.hire(); });
    $("time-chip").addEventListener("click", () => { if (window.Office) Office.cycleTime(); });
    $("help-btn")?.addEventListener("click", openHelp);
    $("help-close")?.addEventListener("click", () => $("help-dialog").close());
    document.addEventListener("keydown", onKey);

    // an agent picked from the crew list: get the sheet out of the way on small screens
    document.querySelector(".col-left").addEventListener("click", (e) => {
      if (e.target.closest(".agent-card") && window.innerWidth < 900) closeSheets(null);
    });
    // a dot on the Activity button when something new is logged while it is closed
    const log = $("log");
    if (log) new MutationObserver((changes) => {
      if (isOpen("log")) return;
      if (changes.some((c) => [...c.addedNodes].some((n) => n.classList && n.classList.contains("log-row")))) $("dock-log").classList.add("ping");
    }).observe(log, { childList: true });

    if (window.Office && Office.getTime) {
      const t = Office.getTime(), d = new Date();
      applyTime({ theme: t.theme, label: t.label, preview: t.preview, dark: t.theme === "night" ? 1 : 0,
        clock: `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}` });
    }
  }

  window.Shell = { openSheet: (key) => { closeSheets(key); setSheet(key, true); }, toggleSheet, closeSheets, openHelp };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
