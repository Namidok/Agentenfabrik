"use strict";

// Nova, the front-desk guide. On the very first visit she walks in, introduces the app and
// asks whether you want to create an agent. After that she stays at the desk, and clicking
// her opens a small menu. All her words are plain text set with textContent.

(() => {
  const KEY = "agentfactory.intro";
  const LINES = [
    "Hi! I'm Nova. I look after the front desk here at AgentFactory.",
    "Every desk in this office belongs to an agent. Click one to chat, hover to see what they are up to, or use the arrow keys.",
    "Everything runs on this computer with Ollama, so nothing you type ever leaves it.",
  ];

  const $ = (id) => document.getElementById(id);
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  let card, textEl, actionsEl, srEl, stage;
  let typer = null;
  let returnFocus = null;
  let booted = false;

  const seen = () => { try { return localStorage.getItem(KEY) === "done"; } catch { return false; } };
  const markSeen = () => { try { localStorage.setItem(KEY, "done"); } catch { /* private window: ask again next time */ } };
  const isOpen = () => !!card && !card.hidden;

  function stopTyping() {
    if (typer) clearInterval(typer.timer);
    typer = null;
  }

  function finishTyping() {
    if (!typer) return;
    textEl.textContent = typer.text;
    const done = typer.done;
    stopTyping();
    done();
  }

  function say(text, done) {
    stopTyping();
    actionsEl.replaceChildren();
    srEl.textContent = text;
    if (reduced.matches) {
      textEl.textContent = text;
      done();
      return;
    }
    textEl.textContent = "";
    let shown = 0;
    typer = { text, done, timer: setInterval(() => {
      shown += 2;
      textEl.textContent = text.slice(0, shown);
      if (shown >= text.length) finishTyping();
    }, 24) };
  }

  function show(step) {
    open();
    say(step.text, () => {
      const buttons = step.actions.map((action) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = action.primary ? "btn-primary" : "btn-secondary";
        button.textContent = action.label;
        button.addEventListener("click", action.run);
        return button;
      });
      actionsEl.replaceChildren(...buttons);
      const primary = buttons.find((b) => b.classList.contains("btn-primary")) || buttons[0];
      if (primary) primary.focus({ preventScroll: true });
    });
  }

  function open() {
    if (isOpen()) return;
    returnFocus = document.activeElement;
    card.hidden = false;
    stage.classList.add("nova-open");
  }

  function close() {
    stopTyping();
    card.hidden = true;
    stage.classList.remove("nova-open");
    const target = returnFocus && document.contains(returnFocus) ? returnFocus : $("office");
    returnFocus = null;
    target.focus?.({ preventScroll: true });
  }

  // ---------- the conversation ----------

  function intro(i = 0) {
    if (i < LINES.length) {
      show({ text: LINES[i], actions: [
        { label: "Next", primary: true, run: () => intro(i + 1) },
        { label: "Skip intro", run: finish },
      ] });
    } else {
      show({ text: "So, do you want to create your own agent?", actions: [
        { label: "Yes, let's do it", primary: true, run: hire },
        { label: "Not now", run: finish },
      ] });
    }
  }

  function hire() {
    markSeen();
    close();
    Office.guide.say("Tell me all about it!", 4);
    Hire.open((hired) => {
      if (hired) Office.guide.say(`Welcome aboard, ${hired.label}!`, 5);
      else Office.guide.say("No problem. I'm here when you're ready.", 4);
    });
  }

  function menu() {
    show({ text: "Hi again! What can I do for you?", actions: [
      { label: "Create an agent", primary: true, run: hire },
      { label: "Replay the intro", run: () => intro(0) },
      { label: "Never mind", run: close },
    ] });
  }

  function finish() {
    markSeen();
    close();
    Office.guide.say("Click me any time you need me.", 5);
  }

  // ---------- start-up ----------

  function boot() {
    if (booted) return;
    booted = true;
    if (seen()) {
      Office.guide.present();
    } else {
      Office.guide.enter(() => {
        Office.guide.say("Hi there!", 3);
        intro(0);
      });
    }
  }

  function init() {
    card = $("nova-card");
    textEl = $("nova-text");
    actionsEl = $("nova-actions");
    srEl = $("nova-sr");
    stage = $("office-stage");
    Office.portrait($("nova-portrait"), Office.guide.look);
    $("nova-close").addEventListener("click", () => { markSeen(); close(); });
    $("nova-btn").addEventListener("click", menu);
    card.addEventListener("click", (event) => { if (!event.target.closest("button")) finishTyping(); });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && isOpen()) { markSeen(); close(); }
    });
  }

  init();
  window.Nova = { boot, menu, hire };
})();
