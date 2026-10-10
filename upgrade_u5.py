"""Upgrade AgentFactory to U5: tool bay, status lights, token meters and queue. Run once from the project folder: python upgrade_u5.py

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

static_office_js = read("static/office.js")
static_office_js = swap(static_office_js, r'''  const PANTS = ["#2f2f46", "#3a4a5a", "#4a3a2f", "#27403a"];
''', r'''  const PANTS = ["#2f2f46", "#3a4a5a", "#4a3a2f", "#27403a"];

  // The tool bay: the Brain (the one model everybody shares) and one station per kind of tool.
  const BAY_H = 64;
  const STATIONS = {
    fs: { label: "FILES", color: "#8c7cf6", name: "File cabinet", what: "Reads and writes files, only in the folders each agent may use" },
    http: { label: "WEB", color: "#4da3ff", name: "Web terminal", what: "Reads pages, only on the websites each agent may visit" },
    notes: { label: "NOTES", color: "#fdcb6e", name: "Notes shelf", what: "Keeps notes between chats" },
    code: { label: "BUILD", color: "#ff9f5a", name: "Build machine", what: "Compiles and runs C++ on this computer" },
    srs: { label: "CARDS", color: "#7bd88f", name: "Flashcard box", what: "Flashcards that come back at the right time" },
  };
  const STATION_ORDER = ["fs", "http", "notes", "code", "srs"];
  const stationOf = (tool) => { const key = String(tool || "").split(/[._]/)[0]; return STATIONS[key] ? key : null; };
  const brain = { online: null };
  const stationLog = new Map(); // station key -> { until, by, text } for the latest call
''', "static/office.js #1")

static_office_js = swap(static_office_js, r'''  const rowCount = () => Math.max(1, Math.ceil(order.length / COLS));
  const contentHeight = () => TOP + 26 + rowCount() * ROW_H + 10;
  function relayout() { resize(); }''', r'''  const rowCount = () => Math.max(1, Math.ceil(order.length / COLS));
  const contentHeight = () => TOP + 26 + rowCount() * ROW_H + BAY_H + 6;
  function relayout() { resize(); }''', "static/office.js #2")

static_office_js = swap(static_office_js, r'''
  // ---------- people ----------''', r'''
  // ---------- tool bay ----------

  const bayTop = () => TOP + 26 + rowCount() * ROW_H + 2;
  const brainPos = () => ({ x: 96, y: bayTop() });
  function presentStations() {
    const keys = new Set();
    for (const a of agents.values()) for (const t of a.tools || []) { const k = stationOf(t); if (k) keys.add(k); }
    return STATION_ORDER.filter((k) => keys.has(k));
  }
  function stationPos(key) {
    const i = presentStations().indexOf(key);
    return { x: 196 + Math.max(0, i) * 92, y: bayTop() };
  }
  function queueList() {
    return [...agents.values()].filter((a) => a.status === "queued").sort((p, q) => (p.queuedAt || 0) - (q.queuedAt || 0));
  }
  function brainModel() {
    const list = [...agents.values()];
    const a = list.find((x) => x.status === "working") || list.find((x) => x.name === selected) || list[0];
    return a && a.model ? a.model : "model";
  }

  function plate(x, y, w, label, color, lit) {
    rect(x - w / 2, y, w, 11, lit ? alpha(color, 0.3) : "rgba(18,18,42,0.85)");
    rect(x - w / 2, y, w, 1, color);
    text(label, x, y + 8, lit ? "#ffffff" : color, 7);
  }

  function drawBrain() {
    const { x, y } = brainPos();
    const working = [...agents.values()].some((a) => a.status === "working");
    const queue = queueList();
    const down = brain.online === false;
    if (working && !down) rect(x - 30, y - 4, 60, 56, alpha("#2ec4a0", 0.1 + 0.03 * Math.sin(clock * 4)));
    rect(x - 22, y, 44, 38, "#2d3036");
    rect(x - 22, y, 44, 2, "#4a4f5a");
    for (let i = 0; i < 4; i++) {
      const sy = y + 5 + i * 8;
      rect(x - 18, sy, 36, 6, "#15161c");
      const on = !down && (working ? (reduced.matches || (Math.floor(clock * 5) + i) % 3 !== 0) : i === 0);
      rect(x - 16, sy + 2, 2, 2, down ? "#ff7d70" : on ? "#2ec4a0" : "#3a3d48");
      rect(x - 10, sy + 2, 18, 1, "#262830");
      rect(x - 10, sy + 4, 10, 1, "#262830");
    }
    plate(x, y + 40, 56, down ? "OFFLINE" : "BRAIN", down ? C.warn : "#2ec4a0", working);
    queue.slice(0, 5).forEach((a, i) => {
      rect(x + 25, y + 3 + i * 7, 9, 5, a.color);
      rect(x + 25, y + 3 + i * 7, 9, 1, "rgba(255,255,255,0.35)");
    });
    if (queue.length) text(`x${queue.length}`, x + 30, y + 3 + Math.min(queue.length, 5) * 7 + 8, C.ledWait, 7);
  }

  function drawStation(key) {
    const meta = STATIONS[key], { x, y } = stationPos(key);
    const log = stationLog.get(key), lit = !!log && log.until > clock;
    const blink = lit && !reduced.matches && Math.floor(clock * 6) % 2 === 0;
    if (lit) rect(x - 30, y - 4, 60, 56, alpha(meta.color, 0.12));
    if (key === "fs") {
      rect(x - 16, y + 2, 32, 36, "#8e94ad");
      rect(x - 16, y + 2, 32, 2, "#b3b8cf");
      for (let i = 0; i < 3; i++) {
        const dy = lit && i === 0 ? 3 : 0;
        if (lit && i === 0) rect(x - 10, y + 3, 20, 3, C.paper);
        rect(x - 14, y + 5 + i * 11 + dy, 28, 9, "#c3c8da");
        rect(x - 4, y + 8 + i * 11 + dy, 8, 2, "#5b6078");
      }
    } else if (key === "http") {
      rect(x - 18, y + 4, 36, 24, "#3a3d52");
      rect(x - 16, y + 6, 32, 20, "#0f1a33");
      rect(x - 4, y + 9, 8, 14, meta.color);
      rect(x - 6, y + 11, 12, 10, meta.color);
      rect(x - 5, y + 10, 10, 12, meta.color);
      rect(x - 6, y + 16, 12, 1, "#0f1a33");
      rect(x, y + 9, 1, 14, "#0f1a33");
      rect(x - 3, y + 28, 6, 4, "#3a3d52");
      rect(x - 8, y + 31, 16, 3, "#3a3d52");
      rect(x + 15, y - 2, 1, 9, "#9aa0b8");
      rect(x + 14, y - 4, 3, 3, blink || (lit && reduced.matches) ? "#ff7d70" : "#6b6f86");
    } else if (key === "notes") {
      rect(x - 18, y + 2, 36, 36, "#5a3d24");
      rect(x - 16, y + 4, 32, 15, "#2a1c10");
      rect(x - 16, y + 21, 32, 15, "#2a1c10");
      ["#ff7d70", "#fdcb6e", "#4da3ff", "#2ec4a0", "#f78fb3", "#8c7cf6"].forEach((c, i) => rect(x - 15 + i * 5, y + 6 + (i % 2), 4, 13 - (i % 2), c));
      ["#8c7cf6", "#7bd88f", "#ff9f5a", "#4da3ff"].forEach((c, i) => rect(x - 15 + i * 5, y + 24 + (i % 2), 4, 12 - (i % 2), c));
      if (lit) { rect(x - 9, y + 20, 18, 12, C.paper); rect(x, y + 20, 1, 12, "#9aa0b8"); rect(x - 7, y + 24, 5, 1, "#8c92a8"); rect(x + 2, y + 24, 5, 1, "#8c92a8"); }
    } else if (key === "code") {
      rect(x - 18, y + 8, 36, 30, "#2d3436");
      rect(x - 18, y + 8, 36, 2, "#4a5558");
      rect(x - 14, y + 12, 28, 14, "#101820");
      text("C++", x, y + 23, lit ? meta.color : "#a0663a", 9);
      rect(x - 16, y + 30, 32, 4, "#1a2022");
      const off2 = lit && !reduced.matches ? Math.floor(clock * 8) % 6 : 0;
      for (let i = 0; i < 5; i++) rect(x - 15 + i * 7 + off2 % 3, y + 31, 3, 2, lit ? meta.color : "#3a4548");
      if (lit && !reduced.matches) rect(x + 8 + (Math.floor(clock * 4) % 3), y + 2 - (Math.floor(clock * 4) % 3) * 2, 4, 4, "rgba(220,220,235,0.35)");
    } else if (key === "srs") {
      rect(x - 16, y + 18, 32, 20, "#3e6f4a");
      rect(x - 16, y + 18, 32, 3, "#57956a");
      rect(x - 12, y + (lit ? 4 : 8), 10, 14, C.paper);
      rect(x - 6, y + (lit ? 2 : 6), 10, 14, "#e4e2ff");
      rect(x, y + (lit ? 4 : 8), 10, 14, C.paper);
      rect(x - 10, y + (lit ? 7 : 11), 6, 1, "#8e92a8");
      rect(x - 4, y + (lit ? 5 : 9), 6, 1, "#8e92a8");
    }
    plate(x, y + 40, 52, meta.label, meta.color, lit);
  }

  function drawBay() {
    const y = bayTop();
    rect(40, y - 2, W - 80, BAY_H - 6, alpha("#4da3ff", 0.045));
    rect(40, y - 2, W - 80, 1, alpha("#8c7cf6", 0.35));
    text("TOOL BAY", W - 46, y + 6, "#6f6e98", 6, "right");
    drawBrain();
    for (const key of presentStations()) drawStation(key);
  }

  // A line of moving dots from a desk to the Brain (thinking) or to a station (using a tool).
  function drawBeams() {
    order.forEach((name, i) => {
      const a = agents.get(name);
      if (!a || !a.seated) return;
      const call = a.lastCall && a.lastCall.until > clock ? a.lastCall : null;
      let target = null, color = a.color, dim = false;
      if (call && presentStations().includes(call.key)) { const p = stationPos(call.key); target = { x: p.x, y: p.y + 4 }; }
      else if (a.status === "working") { const p = brainPos(); target = { x: p.x, y: p.y + 4 }; }
      else if (a.status === "queued") { const p = brainPos(); target = { x: p.x, y: p.y + 4 }; color = C.ledWait; dim = true; }
      if (!target) return;
      const { cx, y0 } = cellOf(i);
      const sx = cx, sy = y0 + 44;
      const dist = Math.hypot(target.x - sx, target.y - sy);
      const n = Math.max(2, Math.floor(dist / 7));
      const drift = reduced.matches || dim ? 0 : (clock * 1.2) % 1;
      for (let k = 0; k < n; k++) {
        const t = ((k + drift) % n) / n;
        const px = sx + (target.x - sx) * t, py = sy + (target.y - sy) * t;
        rect(rnd(px) - 1, rnd(py) - 1, 2, 2, alpha(color, dim ? 0.35 : 0.9));
      }
    });
  }

  // ---------- people ----------''', "static/office.js #3")

static_office_js = swap(static_office_js, r'''    const accent = a.color;
    const isSel = selected === a.name, isHot = highlighted === a.name || hover === a.name;
    const working = a.status === "working", waiting = a.status === "queued";''', r'''    const accent = a.color;
    const isSel = selected === a.name, isHot = highlighted === a.name || hover === a.name || (a.pulseUntil || 0) > clock;
    const working = a.status === "working", waiting = a.status === "queued";''', "static/office.js #4")

static_office_js = swap(static_office_js, r'''
    // status light and name plate
    const ledColor = off ? C.warn : working ? accent : waiting ? C.ledWait : C.ledIdle;
    rect(cx + 28, y0 + 37, 4, 2, working && !reduced.matches && Math.floor(clock * 3) % 2 ? shade(ledColor, 0.55) : ledColor);
    rect(cx - 38, y0 + 62, 76, 11, isSel ? alpha(accent, 0.3) : "rgba(18,18,42,0.85)");
    rect(cx - 38, y0 + 62, 76, 1, accent);
    text(clip(a.label, 16), cx, y0 + 70, isSel ? "#ffffff" : accent, 7);
    if (off) text("!", cx - 36, y0 + 12, C.warn, 10);''', r'''
    // status light, name plate, token meter and place in the queue
    const ledColor = off ? C.warn : a.alert ? "#ff7d70" : working ? accent : waiting ? C.ledWait : C.ledIdle;
    const ledOn = !(working && !reduced.matches && Math.floor(clock * 3) % 2);
    if (working || a.alert) rect(cx + 25, y0 + 34, 9, 7, alpha(ledColor, 0.18));
    rect(cx + 27, y0 + 36, 5, 3, ledOn ? ledColor : shade(ledColor, 0.55));
    rect(cx - 38, y0 + 62, 76, 11, isSel ? alpha(accent, 0.3) : "rgba(18,18,42,0.85)");
    rect(cx - 38, y0 + 62, 76, 1, a.alert ? "#ff7d70" : accent);
    text(clip(a.label, 16), cx, y0 + 70, isSel ? "#ffffff" : accent, 7);
    rect(cx - 38, y0 + 75, 76, 3, "rgba(255,255,255,0.08)");
    if (a.meter && a.meter.max > 0 && a.meter.used > 0) {
      const frac = Math.min(1, a.meter.used / a.meter.max);
      rect(cx - 38, y0 + 75, Math.max(1, rnd(76 * frac)), 3, frac < 0.6 ? C.led : frac < 0.85 ? C.warn : "#ff7d70");
    }
    if (waiting) {
      const place = queueList().indexOf(a) + 1;
      rect(cx + 20, y0 - 9, 18, 9, C.ledWait);
      text(`#${place}`, cx + 29, y0 - 2, C.ink, 7);
    }
    if (off) text("!", cx - 36, y0 + 12, C.warn, 10);''', "static/office.js #5")

static_office_js = swap(static_office_js, r'''    drawDoor("staff");
    const loungeY = TOP + 26 + rowCount() * ROW_H;
    if (H - loungeY >= 80) drawLounge(loungeY);''', r'''    drawDoor("staff");
    const loungeY = TOP + 26 + rowCount() * ROW_H + BAY_H;
    if (H - loungeY >= 80) drawLounge(loungeY);''', "static/office.js #6")

static_office_js = swap(static_office_js, r'''    drawPlant(W - 20, H - 18);
''', r'''    drawPlant(W - 20, H - 18);
    drawBay();
''', "static/office.js #7")

static_office_js = swap(static_office_js, r'''    for (const item of items) item.fn();
''', r'''    for (const item of items) item.fn();
    drawBeams();
''', "static/office.js #8")

static_office_js = swap(static_office_js, r'''    }
    return null;''', r'''    }
    const top = bayTop();
    if (p.y > top - 4 && p.y < top + 52) {
      const b = brainPos();
      if (Math.abs(p.x - b.x) < 34) return { kind: "brain" };
      for (const key of presentStations()) if (Math.abs(p.x - stationPos(key).x) < 24) return { kind: "station", key };
    }
    return null;''', "static/office.js #9")

static_office_js = swap(static_office_js, r'''        a.status === "working" ? "Working right now" : a.status === "queued" ? "Waiting for the model" : "At their desk";
      return [a.label, `${a.mode === "task" ? "Task agent" : "Chat agent"} · ${state}`, "Click to chat, right-click for more"];
    }''', r'''        a.status === "working" ? "Working right now" : a.status === "queued" ? "Waiting for the model" : "At their desk";
      const lines = [a.label, `${a.mode === "task" ? "Task agent" : "Chat agent"} · ${state}`];
      if (a.status === "queued") lines.push(`Number ${queueList().indexOf(a) + 1} in line for the model`);
      if (a.meter && a.meter.max > 0) {
        lines.push(`${a.status === "working" ? "This run" : "Last run"}: ${a.meter.used.toLocaleString()} of ${a.meter.max.toLocaleString()} tokens`);
      }
      if (a.alert) lines.push(a.alert);
      lines.push("Click to chat, right-click for more");
      return lines;
    }
    if (hit.kind === "brain") {
      const q = queueList(), now = [...agents.values()].find((x) => x.status === "working");
      const state = brain.online === false ? "Ollama is not reachable. Open the Ollama app." : now ? `Thinking for ${now.label}` : "Idle";
      const lines = ["Brain", `${brainModel()}, running on this computer`, state];
      if (q.length) lines.push(`Waiting: ${q.map((x) => x.label).join(", ")}`);
      lines.push("One agent thinks at a time. Click to see who is using it.");
      return lines;
    }
    if (hit.kind === "station") {
      const meta = STATIONS[hit.key], users = [...agents.values()].filter((a) => (a.tools || []).some((t) => stationOf(t) === hit.key));
      const log = stationLog.get(hit.key);
      const lines = [meta.name, meta.what, `Used by: ${users.map((a) => a.label).join(", ") || "nobody"}`];
      if (log) lines.push(`Last call: ${log.by} ${log.text}`);
      lines.push("Click to see who may use it");
      return lines;
    }''', "static/office.js #10")

static_office_js = swap(static_office_js, r'''    else if (hit.kind === "guide") onGuide();
    else if (hit.kind === "door") doorState[hit.key].target = doorState[hit.key].target ? 0 : 1;''', r'''    else if (hit.kind === "guide") onGuide();
    else if (hit.kind === "brain") { for (const a of agents.values()) if (a.status !== "idle") a.pulseUntil = clock + 2; }
    else if (hit.kind === "station") {
      for (const a of agents.values()) if ((a.tools || []).some((t) => stationOf(t) === hit.key)) a.pulseUntil = clock + 2;
    }
    else if (hit.kind === "door") doorState[hit.key].target = doorState[hit.key].target ? 0 : 1;''', "static/office.js #11")

static_office_js = swap(static_office_js, r'''      hover = hit && hit.kind === "agent" ? hit.name : null;
      view.style.cursor = hit && (hit.kind === "agent" || hit.kind === "door" || hit.kind === "guide") ? "pointer" : "default";
      showTip(event, hit);''', r'''      hover = hit && hit.kind === "agent" ? hit.name : null;
      view.style.cursor = hit && ["agent", "door", "guide", "brain", "station"].includes(hit.kind) ? "pointer" : "default";
      showTip(event, hit);''', "static/office.js #12")

static_office_js = swap(static_office_js, r'''        name: info.name, label: info.label, color: info.color, mode: info.mode, runnable: info.runnable !== false,
        hair: info.hair || null,
        status: info.status || "idle",
        seated: old ? old.seated : true, walker: old ? old.walker : null,''', r'''        name: info.name, label: info.label, color: info.color, mode: info.mode, runnable: info.runnable !== false,
        hair: info.hair || null, model: info.model || "", tools: info.tools || [],
        status: info.status || "idle",
        meter: old ? old.meter : null, alert: old ? old.alert : "", lastCall: old ? old.lastCall : null,
        queuedAt: old ? old.queuedAt : 0, pulseUntil: old ? old.pulseUntil : 0,
        seated: old ? old.seated : true, walker: old ? old.walker : null,''', "static/office.js #13")

static_office_js = swap(static_office_js, r'''    highlight(name) { highlighted = name; },
    setStatus(name, status) { const a = agents.get(name); if (a) a.status = status; },
    say(name, str, seconds = 4) {''', r'''    highlight(name) { highlighted = name; },
    setStatus(name, status) {
      const a = agents.get(name);
      if (!a) return;
      if (status === "queued" && a.status !== "queued") a.queuedAt = clock;
      a.status = status;
    },
    setMeter(name, used, max) { const a = agents.get(name); if (a) a.meter = { used, max }; },
    setAlert(name, message) { const a = agents.get(name); if (a) a.alert = message || ""; },
    setBrain(info) { if ("online" in info) brain.online = info.online; },
    toolCall(name, tool, detail) {
      const a = agents.get(name), key = stationOf(tool);
      if (!a || !key) return;
      a.lastCall = { key, until: clock + 1.8 };
      stationLog.set(key, { until: clock + 1.8, by: a.label, text: detail || tool });
    },
    say(name, str, seconds = 4) {''', "static/office.js #14")

texts["static/office.js"] = static_office_js

static_app_js = read("static/app.js")
static_app_js = swap(static_app_js, r'''      const config = await getJSON("/api/config");
      if (config.ollama_up) {''', r'''      const config = await getJSON("/api/config");
      Office.setBrain({ online: !!config.ollama_up });
      if (config.ollama_up) {''', "static/app.js #1")

static_app_js = swap(static_app_js, r'''      hair: (custom.get(a.name) || {}).hair || null,
      mode: a.mode,''', r'''      hair: (custom.get(a.name) || {}).hair || null,
      model: a.model,
      tools: a.tools,
      mode: a.mode,''', "static/app.js #2")

static_app_js = swap(static_app_js, r'''    chat.status = "working";
    refreshStatus(chat);''', r'''    chat.status = "working";
    chat.runTokens = 0;
    Office.setAlert(chat.agent, "");
    refreshStatus(chat);''', "static/app.js #3")

static_app_js = swap(static_app_js, r'''
  function onServerEvent(chat, msg) {''', r'''
  // The token meter on the desk counts against the agent's own limit for one run.
  function tokenLimit(chat) {
    const agent = state.agents.find((a) => a.name === chat.agent);
    return agent && agent.limits ? agent.limits.max_tokens : 0;
  }

  function onServerEvent(chat, msg) {''', "static/app.js #4")

static_app_js = swap(static_app_js, r'''        chat.status = "working";
        Office.say(chat.agent, "Thinking...", 600);''', r'''        chat.status = "working";
        chat.runTokens = 0;
        Office.setMeter(chat.agent, 0, tokenLimit(chat));
        Office.say(chat.agent, "Thinking...", 600);''', "static/app.js #5")

static_app_js = swap(static_app_js, r'''        addLog(chat.agent, payload);
        if (payload.event === "tool") { setTyping(chat, `Using ${payload.name}...`); Office.say(chat.agent, `Using ${payload.name}`, 600); }''', r'''        addLog(chat.agent, payload);
        if (payload.event === "model") {
          chat.runTokens = (chat.runTokens || 0) + (payload.tokens || 0);
          Office.setMeter(chat.agent, chat.runTokens, tokenLimit(chat));
        } else if (payload.event === "tool") {
          Office.toolCall(chat.agent, payload.name, argSummary(payload.arguments));
        }
        if (payload.event === "tool") { setTyping(chat, `Using ${payload.name}...`); Office.say(chat.agent, `Using ${payload.name}`, 600); }''', "static/app.js #6")

static_app_js = swap(static_app_js, r'''        addReply(chat, payload);
        Office.say(chat.agent, payload.ok ? "Done!" : "Stopped early", 3);''', r'''        addReply(chat, payload);
        Office.setMeter(chat.agent, payload.tokens || 0, tokenLimit(chat));
        Office.setAlert(chat.agent, payload.ok ? "" : `Last run stopped early: ${STOP_REASONS[payload.stop_reason] || payload.stop_reason}`);
        Office.say(chat.agent, payload.ok ? "Done!" : "Stopped early", 3);''', "static/app.js #7")

static_app_js = swap(static_app_js, r'''        if (chat.busy) endTurn(chat);
        Office.say(chat.agent, "Something went wrong", 4);''', r'''        if (chat.busy) endTurn(chat);
        Office.setAlert(chat.agent, "Last run failed");
        Office.say(chat.agent, "Something went wrong", 4);''', "static/app.js #8")

texts["static/app.js"] = static_app_js

static_style_css = read("static/style.css")
static_style_css = swap(static_style_css, r'''
.panel-actions { display: inline-flex; gap: 0.1rem; }
.dialog-wide { width: min(46rem, calc(100% - 2rem)); max-height: calc(100dvh - 2rem); padding: 0; overflow: hidden; }''', r'''
.panel-actions { display: inline-flex; gap: 0.1rem; flex-shrink: 0; }
.panel-actions .btn-quiet { white-space: nowrap; padding: 0.25rem 0.3rem; }
.roster-panel .panel-head h2 { white-space: nowrap; }
.dialog-wide { width: min(46rem, calc(100% - 2rem)); max-height: calc(100dvh - 2rem); padding: 0; overflow: hidden; }''', "static/style.css #1")

texts["static/style.css"] = static_style_css

if problems:
    print("Nothing was changed. These pieces did not match:")
    for p in problems:
        print("  -", p)
    raise SystemExit(1)

for rel, content in texts.items():
    (ROOT / rel).write_text(content, encoding="utf-8")
print("Done: office.js, app.js and style.css updated.")
