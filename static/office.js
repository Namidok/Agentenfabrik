"use strict";

// The pixel-art office. Plain canvas calls, no images and no libraries, so it works offline.
// app.js tells it who works here and what they are doing; this file draws the room, moves
// people around and reports clicks. Everything is drawn on a small logical grid (W x H) and
// scaled up, which is what keeps the pixels sharp.

(() => {
  const DESK_W = 640; // the desks and the back wall decorations
  const W = 760; // 640 for the desks plus a 120 wide tool column on the right
  const TOP = 72; // where the back wall ends and the floor starts
  const ROW_H = 92;
  const COLS = 4;
  const MIN_H = 360;
  const SPEED = 80; // logical pixels per second
  const DOORS = { front: { x: 36, label: "Front door" }, staff: { x: W - 36, label: "Staff door" } };

  const C = {
    bg: "#1a1a2e", wall: "#20203a", wallTrim: "#3a3a60", wallDark: "#17172b",
    floorA: "#23233a", floorB: "#272741", rug: "#2c2c4d",
    wood: "#8a6440", woodTop: "#a47a4f", woodDark: "#5a3d24",
    metal: "#7f8c8d", metalDark: "#2d3436",
    screenOff: "#10101e", ink: "#1a1a2e", paper: "#eef0f4",
    led: "#2ec4a0", ledWait: "#fdcb6e", ledIdle: "#6b6f86", warn: "#fdcb6e", focus: "#ffd166",
  };
  const SKIN = ["#f1c27d", "#d9a066", "#a8714a", "#6b4429", "#f6d5b8"];
  const HAIR = ["#3b2a20", "#2d1f17", "#8a4b2b", "#e0b34a", "#1c1c28", "#a03a6a", "#4b6fd6", "#d8d8e8"];
  const PANTS = ["#2f2f46", "#3a4a5a", "#4a3a2f", "#27403a"];

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

  // Sprites: one character per pixel, drawn at 2 x 2 logical pixels each.
  const PX = 2;
  const HEAD_DOWN = ["...HHHH...", "..HHHHHH..", "..HSSSSH..", "..SESSES..", "..SSSSSS..", "...SSSS..."];
  const HEAD_UP = ["...HHHH...", "..HHHHHH..", "..HHHHHH..", "..HHHHHH..", "..SHHHHS..", "...SSSS..."];
  const TORSO = ["..TTTTTT..", ".TTTTTTTT.", ".STTTTTTS.", ".STtTTtTS.", "..WWWWWW.."];
  const TORSO_TYPE = ["..TTTTTT..", ".TTTTTTTT.", ".TTTTTTTT.", ".STtTTtTS.", "..WWWWWW.."];
  const LEGS = {
    stand: ["..PP..PP..", "..PP..PP..", "..BB..BB.."],
    stepA: ["..PP..PP..", "..PP..BB..", "..BB......"],
    stepB: ["..PP..PP..", "..BB..PP..", "......BB.."],
  };

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const agents = new Map(); // name -> agent
  let order = []; // names in desk order
  let view, vctx, buffer, bctx, tipEl, liveEl;
  let scaleCss = 1, bufScale = 1, H = MIN_H;
  let onPick = () => {};
  let onGuide = () => {};
  let onMenu = () => {};
  let selected = null, highlighted = null, hover = null, focusName = null;
  let lastFrame = 0, clock = 0;
  const doorState = { front: { open: 0, target: 0 }, staff: { open: 0, target: 0 } };

  // ---------- small helpers ----------

  const rnd = Math.round;
  function hash(text) {
    let h = 2166136261;
    for (const ch of text) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0;
    return h;
  }
  function shade(hex, f) {
    const n = parseInt(hex.slice(1), 16);
    const mix = (c) => Math.max(0, Math.min(255, rnd(c * f)));
    const r = mix((n >> 16) & 255), g = mix((n >> 8) & 255), b = mix(n & 255);
    return `#${((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1)}`;
  }
  function alpha(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }
  function rect(x, y, w, h, color) {
    bctx.fillStyle = color;
    bctx.fillRect(rnd(x), rnd(y), rnd(w), rnd(h));
  }
  function grid(rows, x, y, pal) {
    for (let r = 0; r < rows.length; r++) {
      const row = rows[r];
      for (let c = 0; c < row.length; c++) {
        const ch = row[c];
        if (ch !== "." && pal[ch]) rect(x + c * PX, y + r * PX, PX, PX, pal[ch]);
      }
    }
  }
  function text(str, x, y, color, size = 7, align = "center", bold = true) {
    bctx.font = `${bold ? "bold " : ""}${size}px ui-monospace, "SF Mono", Menlo, Consolas, monospace`;
    bctx.textAlign = align;
    bctx.textBaseline = "alphabetic";
    bctx.fillStyle = color;
    bctx.fillText(str, rnd(x), rnd(y));
  }
  const clip = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

  function look(agent) {
    const h = hash(agent.name);
    return {
      H: agent.hair || HAIR[h % HAIR.length],
      S: SKIN[(h >> 5) % SKIN.length],
      E: "#15151f",
      T: agent.color,
      t: shade(agent.color, 0.72),
      W: PANTS[(h >> 9) % PANTS.length],
      P: PANTS[(h >> 9) % PANTS.length],
      B: "#15151f",
    };
  }

  // ---------- layout ----------

  function cellOf(index) {
    return { cx: 100 + (index % COLS) * 147, y0: TOP + 26 + Math.floor(index / COLS) * ROW_H, col: index % COLS };
  }
  const rowCount = () => Math.max(1, Math.ceil(order.length / COLS));
  const contentHeight = () => Math.max(TOP + 26 + rowCount() * ROW_H + 6, bayBottom());
  function relayout() { resize(); }

  function resize() {
    if (!view) return;
    const box = view.parentElement;
    const cw = box.clientWidth, ch = box.clientHeight;
    if (!cw || !ch) return;
    H = Math.max(MIN_H, contentHeight(), Math.min(rnd((W * ch) / cw), 500));
    scaleCss = Math.min(cw / W, ch / H, 3);
    const dpr = window.devicePixelRatio || 1;
    view.style.width = `${W * scaleCss}px`;
    view.style.height = `${H * scaleCss}px`;
    view.width = Math.max(1, rnd(W * scaleCss * dpr));
    view.height = Math.max(1, rnd(H * scaleCss * dpr));
    bufScale = Math.max(1, Math.min(6, Math.ceil(scaleCss * dpr)));
    buffer.width = W * bufScale;
    buffer.height = H * bufScale;
    vctx.imageSmoothingEnabled = Number.isInteger(scaleCss * dpr) ? false : true;
    vctx.imageSmoothingQuality = "high";
    draw();
  }

  // ---------- scene pieces ----------

  function drawFloorAndWall() {
    rect(0, 0, W, H, C.bg);
    rect(0, 0, W, TOP, C.wall);
    rect(0, TOP - 6, W, 6, C.wallDark); // baseboard
    rect(0, TOP, W, 2, C.wallTrim);
    for (let y = TOP + 2; y < H; y += 16) {
      for (let x = 0; x < W; x += 16) {
        rect(x, y, 16, 16, ((x + y) / 16) % 2 ? C.floorA : C.floorB);
      }
    }
    // a soft rug under each row of desks
    const rows = Math.ceil(order.length / COLS);
    for (let r = 0; r < rows; r++) {
      const y = TOP + 18 + r * ROW_H;
      rect(40, y, DESK_W - 80, ROW_H - 12, alpha("#8c7cf6", 0.07));
    }
  }

  function drawWindow(x, w) {
    rect(x - 2, 10, w + 4, 40, C.wallTrim);
    rect(x, 12, w, 36, "#0d1030");
    rect(x, 12, w, 14, "#161a45");
    const seed = Math.floor(clock * 1.5);
    for (let i = 0; i < 7; i++) {
      const sx = x + 4 + ((i * 17 + 5) % (w - 8));
      const sy = 14 + ((i * 11 + 3) % 18);
      if ((i + seed) % 5 !== 0) rect(sx, sy, 1, 1, "#dfe4ff");
    }
    // skyline
    for (let i = 0; i < w; i += 8) {
      const bh = 6 + ((hash(`b${x}${i}`) >> 3) % 12);
      rect(x + i, 48 - bh, 7, bh, "#101328");
      if ((i / 8 + x) % 3 === 0) rect(x + i + 2, 48 - bh + 3, 1, 1, "#fdcb6e");
    }
    rect(x + w / 2 - 1, 12, 2, 36, C.wallTrim);
  }

  function drawDoor(key) {
    const d = DOORS[key], st = doorState[key];
    const x = d.x - 15, top = TOP - 48;
    rect(x - 3, top - 3, 36, 51, C.wallTrim);
    rect(x, top, 30, 48, "#0b0b18");
    if (st.open > 0.02) rect(x + 2, top + 2, 26, 44, alpha("#fdcb6e", 0.18 * st.open + 0.05)); // light spills in
    const leaf = Math.max(5, rnd(30 * (1 - st.open * 0.8)));
    rect(x, top, leaf, 48, key === "front" ? "#6d4c2e" : "#3f4a63");
    rect(x, top, leaf, 3, key === "front" ? "#8a6440" : "#55627f");
    rect(x + leaf - 5, top + 24, 3, 3, "#fdcb6e");
    text(d.label.toUpperCase(), d.x, top - 7, "#a5a4c4", 6);
    rect(d.x - 7, top - 3, 14, 2, C.led);
  }

  function drawSign() {
    rect(250, 14, 140, 26, "#12122a");
    rect(250, 14, 140, 2, "#8c7cf6");
    rect(250, 38, 140, 2, "#8c7cf6");
    text("AGENT FACTORY", 320, 31, "#c9c1ff", 11);
  }

  function drawClock() {
    const cx = 428, cy = 30;
    rect(cx - 13, cy - 13, 26, 26, C.wallTrim);
    rect(cx - 11, cy - 11, 22, 22, C.paper);
    const now = new Date();
    const m = now.getMinutes() + now.getSeconds() / 60;
    const h = (now.getHours() % 12) + m / 60;
    const hand = (angle, len, color) => {
      bctx.strokeStyle = color;
      bctx.lineWidth = 1;
      bctx.beginPath();
      bctx.moveTo(cx, cy);
      bctx.lineTo(cx + Math.sin(angle) * len, cy - Math.cos(angle) * len);
      bctx.stroke();
    };
    hand((h / 12) * Math.PI * 2, 5, C.ink);
    hand((m / 60) * Math.PI * 2, 8, C.ink);
    rect(cx - 1, cy - 1, 2, 2, "#ff7d70");
  }

  function drawBoard() {
    rect(468, 12, 84, 42, "#9aa0b8");
    rect(470, 14, 80, 38, C.paper);
    text("BLUEPRINT", 510, 24, "#8c7cf6", 6);
    rect(476, 30, 28, 2, "#c9c9dd");
    rect(476, 36, 44, 2, "#c9c9dd");
    rect(476, 42, 20, 2, "#c9c9dd");
    rect(520, 30, 24, 16, "#e4e2ff");
    rect(520, 30, 24, 1, "#8c7cf6");
  }

  function drawCooler(x, y) {
    rect(x - 7, y - 30, 14, 14, "#a9d6ff");
    rect(x - 7, y - 30, 14, 2, "#d7ecff");
    rect(x - 8, y - 16, 16, 22, "#d9dce8");
    rect(x - 8, y - 16, 16, 2, "#f0f1f7");
    rect(x - 3, y - 10, 6, 3, "#5b6fd6");
    rect(x - 8, y + 6, 16, 2, "#9aa0b8");
  }

  function drawLounge(y) {
    const space = H - y;
    const base = y + space / 2 + 6;
    rect(236, base - 30, 168, 72, alpha("#2ec4a0", 0.045));
    rect(275, base - 20, 90, 14, "#3d2f7a");
    rect(275, base - 6, 90, 14, "#5a46b8");
    rect(267, base - 14, 10, 24, "#3d2f7a");
    rect(363, base - 14, 10, 24, "#3d2f7a");
    rect(301, base - 4, 1, 10, "#4a3a96");
    rect(331, base - 4, 1, 10, "#4a3a96");
    rect(300, base + 18, 40, 10, "#8a6440");
    rect(300, base + 26, 40, 3, "#5a3d24");
    rect(318, base + 14, 5, 5, "#ff7d70");
    // floor lamp
    rect(404, base - 24, 2, 34, C.metal);
    rect(398, base - 32, 14, 9, "#fdcb6e");
    rect(396, base - 24, 18, 22, "rgba(253,203,110,0.07)");
  }

  function drawPlant(x, y) {
    rect(x - 7, y - 10, 14, 12, "#6d4c2e");
    rect(x - 8, y - 12, 16, 3, "#8a6440");
    rect(x - 2, y - 26, 4, 14, "#2f8f5b");
    rect(x - 10, y - 26, 8, 6, "#37a56a");
    rect(x + 2, y - 30, 8, 7, "#2f8f5b");
    rect(x - 6, y - 34, 7, 7, "#37a56a");
    rect(x + 1, y - 22, 9, 5, "#37a56a");
  }

  // ---------- tool bay ----------

  const COL_X = 690; // the tool column on the right: the Brain on top, one station under another
  const STATION_STEP = 56;
  const bayTop = () => TOP + 36;
  const brainPos = () => ({ x: COL_X, y: bayTop() });
  function bayBottom() {
    const n = presentStations().length;
    return bayTop() + (n ? 58 + (n - 1) * STATION_STEP : 0) + 52 + 8;
  }
  function presentStations() {
    const keys = new Set();
    for (const a of agents.values()) for (const t of a.tools || []) { const k = stationOf(t); if (k) keys.add(k); }
    return STATION_ORDER.filter((k) => keys.has(k));
  }
  function stationPos(key) {
    const i = presentStations().indexOf(key);
    return { x: COL_X, y: bayTop() + 58 + Math.max(0, i) * STATION_STEP };
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
    const left = DESK_W + 8, bottom = bayBottom();
    rect(left, y - 14, W - left - 8, bottom - y + 14, alpha("#4da3ff", 0.045));
    rect(left, y - 14, W - left - 8, 1, alpha("#8c7cf6", 0.35));
    text("TOOL BAY", COL_X, y - 4, "#6f6e98", 6);
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

  // ---------- people ----------

  function drawWalker(a, w) {
    const pal = look(a);
    const x = w.x - 10, feetY = w.y;
    const top = feetY - 14 * PX;
    rect(x + 2, feetY - 1, 16, 3, "rgba(0,0,0,0.25)"); // shadow
    const stepping = w.moving && !reduced.matches;
    const phase = stepping ? (Math.floor(clock * 6) % 2 ? "stepA" : "stepB") : "stand";
    const bob = reduced.matches ? 0 : stepping ? (Math.floor(clock * 6) % 2 ? 0 : -1) : (Math.floor(clock * 1.5) % 2 ? 0 : -1);
    const head = w.dir === "up" ? HEAD_UP : HEAD_DOWN;
    grid([...head, ...TORSO, ...LEGS[phase]], x, top + bob, pal);
  }

  function drawSeated(a, x, top, typing) {
    const pal = look(a);
    const torso = typing ? TORSO_TYPE : TORSO;
    grid([...HEAD_UP, ...torso.slice(0, 4)], x, top, pal);
  }

  function bubble(cx, bottomY, str) {
    const label = clip(str, 34);
    bctx.font = "bold 7px ui-monospace, Menlo, Consolas, monospace";
    const w = Math.max(18, Math.ceil(bctx.measureText(label).width) + 8);
    const x = Math.max(3, Math.min(W - w - 3, cx - w / 2));
    const y = bottomY - 13;
    rect(x - 1, y - 1, w + 2, 13, C.ink);
    rect(x, y, w, 11, C.paper);
    rect(cx - 2, y + 11, 4, 3, C.ink);
    rect(cx - 1, y + 11, 2, 2, C.paper);
    text(label, x + w / 2, y + 8, C.ink, 7);
  }

  function drawCell(a, index) {
    const { cx, y0 } = cellOf(index);
    const accent = a.color;
    const isSel = selected === a.name, isHot = highlighted === a.name || hover === a.name || (a.pulseUntil || 0) > clock;
    const working = a.status === "working", waiting = a.status === "queued";
    const off = !a.runnable;

    if (isSel || isHot || focusName === a.name) {
      const col = focusName === a.name ? C.focus : accent;
      rect(cx - 44, y0 - 6, 88, 80, alpha(accent, isSel ? 0.14 : 0.07));
      const t = isSel ? 2 : 1;
      rect(cx - 44, y0 - 6, 88, t, col);
      rect(cx - 44, y0 + 74 - t + 0, 88, t, col);
      rect(cx - 44, y0 - 6, t, 80, col);
      rect(cx + 44 - t, y0 - 6, t, 80, col);
    }

    // monitor glow
    if (working) rect(cx - 22, y0 - 4, 44, 32, alpha(accent, 0.10 + 0.04 * Math.sin(clock * 4)));

    // monitor
    rect(cx - 14, y0, 28, 19, "#3a3d52");
    rect(cx - 12, y0 + 2, 24, 14, C.screenOff);
    if (off) {
      rect(cx - 12, y0 + 2, 24, 14, "#161621");
    } else if (working) {
      rect(cx - 12, y0 + 2, 24, 14, alpha(accent, 0.28));
      const off2 = reduced.matches ? 0 : Math.floor(clock * 6) % 5;
      for (let i = 0; i < 4; i++) {
        const len = 6 + ((i * 7 + off2 * 3) % 14);
        rect(cx - 10, y0 + 4 + i * 3, len, 1, alpha(accent, 0.95));
      }
    } else if (waiting) {
      const dots = reduced.matches ? 2 : Math.floor(clock * 2) % 3;
      for (let i = 0; i <= dots; i++) rect(cx - 6 + i * 5, y0 + 8, 3, 3, C.ledWait);
    } else {
      const bx = 3 + ((reduced.matches ? 0 : Math.floor(clock * 8)) % 18);
      rect(cx - 12 + bx, y0 + 5 + ((bx * 3) % 8), 3, 3, alpha(accent, 0.7));
    }
    rect(cx - 3, y0 + 19, 6, 3, "#3a3d52");
    rect(cx - 7, y0 + 21, 14, 2, "#3a3d52");

    // desk
    rect(cx - 34, y0 + 22, 68, 14, C.woodTop);
    rect(cx - 34, y0 + 22, 68, 2, shade(C.woodTop, 1.15));
    rect(cx - 34, y0 + 36, 68, 5, C.woodDark);
    rect(cx - 32, y0 + 41, 4, 5, C.woodDark);
    rect(cx + 28, y0 + 41, 4, 5, C.woodDark);
    // things on the desk
    rect(cx - 9, y0 + 28, 18, 4, "#c8cad8");
    rect(cx - 8, y0 + 29, 16, 1, "#8e92a8");
    rect(cx + 22, y0 + 24, 5, 5, shade(accent, 1.1)); // mug
    rect(cx + 27, y0 + 25, 2, 3, shade(accent, 1.1));
    if (!reduced.matches && Math.floor(clock * 2) % 2 === 0) rect(cx + 24, y0 + 21, 1, 2, "rgba(255,255,255,0.4)");
    rect(cx - 30, y0 + 25, 9, 6, C.paper);
    rect(cx - 29, y0 + 27, 6, 1, "#9aa0b8");

    // chair and person
    rect(cx - 12, y0 + 42, 24, 12, shade(accent, 0.45));
    rect(cx - 12, y0 + 42, 24, 2, shade(accent, 0.6));
    if (a.seated) {
      const typing = working && !reduced.matches && Math.floor(clock * 7) % 2 === 0;
      drawSeated(a, cx - 10, y0 + 28, typing);
    }

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
    if (off) text("!", cx - 36, y0 + 12, C.warn, 10);

    if (a.bubbleUntil > clock && a.bubbleText) bubble(cx, y0 - 2, a.bubbleText);
  }

  // ---------- movement ----------

  function walkIn(name, door, done) {
    const a = agents.get(name);
    const index = order.indexOf(name);
    if (!a || index < 0 || !DOORS[door]) return false;
    const { cx, y0, col } = cellOf(index);
    const dx = DOORS[door].x;
    const aisle = col < COLS - 1 ? cx + 73 : cx - 73;
    a.seated = false;
    a.walker = {
      x: dx, y: TOP + 4, dir: "down", moving: true, done,
      path: reduced.matches ? [{ x: cx, y: y0 + 52 }] : [
        { x: dx, y: TOP + 18 }, { x: aisle, y: TOP + 18 },
        { x: aisle, y: y0 + 56 }, { x: cx, y: y0 + 56 }, { x: cx, y: y0 + 52 },
      ],
      door,
    };
    doorState[door].target = 1;
    if (reduced.matches) { a.walker.x = cx; a.walker.y = y0 + 52; }
    return true;
  }

  // Moves a walker along its path. True once it has arrived.
  function advance(w, dt) {
    if (w.door && (w.y > TOP + 22 || Math.abs(w.x - DOORS[w.door].x) > 40)) { doorState[w.door].target = 0; w.door = null; }
    let budget = SPEED * dt;
    while (budget > 0 && w.path.length) {
      const p = w.path[0];
      const dx = p.x - w.x, dy = p.y - w.y, d = Math.hypot(dx, dy);
      if (d < 0.5) { w.path.shift(); continue; }
      const go = Math.min(budget, d);
      w.x += (dx / d) * go;
      w.y += (dy / d) * go;
      w.dir = Math.abs(dy) >= Math.abs(dx) ? (dy < 0 ? "up" : "down") : "down";
      budget -= go;
    }
    return !w.path.length;
  }

  function stepWalker(a, dt) {
    const w = a.walker;
    if (!w || !advance(w, dt)) return;
    a.walker = null;
    if (w.leave) {
      doorState[w.leaveDoor].target = 0;
      if (w.done) w.done(a.name);
      return;
    }
    a.seated = true;
    if (w.door) doorState[w.door].target = 0;
    if (w.done) w.done(a.name);
  }

  // The agent stands up, walks to a door and leaves.
  function walkOut(name, door, done) {
    const a = agents.get(name);
    const index = order.indexOf(name);
    if (!a || index < 0 || !DOORS[door]) {
      if (done) done(name);
      return false;
    }
    const { cx, y0, col } = cellOf(index);
    const dx = DOORS[door].x;
    const aisle = col < COLS - 1 ? cx + 73 : cx - 73;
    a.seated = false;
    a.walker = {
      x: cx, y: y0 + 52, dir: "down", moving: true, done, leave: true, leaveDoor: door,
      path: reduced.matches ? [] : [
        { x: cx, y: y0 + 56 }, { x: aisle, y: y0 + 56 }, { x: aisle, y: TOP + 18 },
        { x: dx, y: TOP + 18 }, { x: dx, y: TOP + 4 },
      ],
    };
    doorState[door].target = 1;
    return true;
  }

  // A small face-and-shoulders picture for avatars elsewhere on the page.
  function portrait(canvas, info) {
    const pal = look({ name: info.name, color: info.color, hair: info.hair || null });
    const rows = [...HEAD_DOWN, ...TORSO.slice(0, 3)];
    canvas.width = 10;
    canvas.height = rows.length;
    const c = canvas.getContext("2d");
    c.clearRect(0, 0, canvas.width, canvas.height);
    rows.forEach((row, y) => {
      for (let x = 0; x < row.length; x++) {
        const ch = row[x];
        if (ch !== "." && pal[ch]) { c.fillStyle = pal[ch]; c.fillRect(x, y, 1, 1); }
      }
    });
  }

  // ---------- the front-desk guide ----------

  const GUIDE_NAME = "Nova";
  const GUIDE_SPOT = { x: 320, y: TOP + 19 };
  const GUIDE_LOOK = { name: "nova", color: "#2ec4a0", hair: "#a03a6a" };
  const guide = { on: false, x: GUIDE_SPOT.x, y: GUIDE_SPOT.y, walker: null, done: null, bubbleText: "", bubbleUntil: 0 };

  function finishGuideWalk() {
    const w = guide.walker;
    guide.x = w.x;
    guide.y = w.y;
    guide.walker = null;
    if (w.door) doorState[w.door].target = 0;
    const done = guide.done;
    guide.done = null;
    if (done) done();
  }

  function drawGuide() {
    const w = guide.walker || { x: guide.x, y: guide.y, dir: "down", moving: false };
    drawWalker(GUIDE_LOOK, w);
    text(GUIDE_NAME.toUpperCase(), w.x, w.y + 9, GUIDE_LOOK.color, 6);
    if (guide.bubbleUntil > clock && guide.bubbleText) bubble(w.x, w.y - 32, guide.bubbleText);
  }

  const guideApi = {
    look: GUIDE_LOOK,
    enter(done) {
      guide.on = true;
      guide.done = done || null;
      const w = {
        x: DOORS.front.x, y: TOP + 4, dir: "down", moving: true, door: "front",
        path: [{ x: DOORS.front.x, y: GUIDE_SPOT.y }, { x: GUIDE_SPOT.x, y: GUIDE_SPOT.y }],
      };
      if (reduced.matches) { w.x = GUIDE_SPOT.x; w.y = GUIDE_SPOT.y; w.path = []; }
      guide.walker = w;
      doorState.front.target = 1;
    },
    present() {
      guide.on = true;
      guide.walker = null;
      guide.x = GUIDE_SPOT.x;
      guide.y = GUIDE_SPOT.y;
    },
    say(str, seconds = 4) {
      guide.bubbleText = str;
      guide.bubbleUntil = clock + seconds;
    },
  };

  // ---------- frame ----------

  function draw() {
    if (!bctx) return;
    bctx.setTransform(bufScale, 0, 0, bufScale, 0, 0);
    bctx.imageSmoothingEnabled = false;
    drawFloorAndWall();
    drawWindow(88, 56);
    drawWindow(158, 56);
    drawSign();
    drawClock();
    drawBoard();
    drawDoor("front");
    drawDoor("staff");
    const loungeY = TOP + 26 + rowCount() * ROW_H;
    if (H - loungeY >= 80) drawLounge(loungeY);
    drawCooler(20, H - 22);
    drawPlant(DESK_W - 20, H - 18);
    drawBay();

    const items = [];
    order.forEach((name, i) => {
      const a = agents.get(name);
      items.push({ depth: cellOf(i).y0 + 50, fn: () => drawCell(a, i) });
      if (a.walker) items.push({ depth: a.walker.y, fn: () => drawWalker(a, a.walker) });
    });
    if (guide.on) items.push({ depth: guide.walker ? guide.walker.y : guide.y, fn: drawGuide });
    items.sort((p, q) => p.depth - q.depth);
    for (const item of items) item.fn();
    drawBeams();

    if (!order.length) text("Nobody works here yet", DESK_W / 2, TOP + 80, "#a5a4c4", 9);

    vctx.clearRect(0, 0, view.width, view.height);
    vctx.drawImage(buffer, 0, 0, view.width, view.height);
  }

  function frame(now) {
    requestAnimationFrame(frame);
    if (document.hidden || !view) return;
    const dt = Math.min(0.05, (now - (lastFrame || now)) / 1000);
    lastFrame = now;
    clock += dt;
    for (const st of Object.values(doorState)) {
      const speed = reduced.matches ? 1 : dt * 3;
      st.open += Math.sign(st.target - st.open) * Math.min(Math.abs(st.target - st.open), speed);
    }
    for (const a of agents.values()) stepWalker(a, dt);
    if (guide.walker && advance(guide.walker, dt)) finishGuideWalk();
    draw();
  }

  // ---------- pointer, keyboard, tooltip ----------

  function toLogical(event) {
    const r = view.getBoundingClientRect();
    return { x: ((event.clientX - r.left) / r.width) * W, y: ((event.clientY - r.top) / r.height) * H };
  }

  function hitTest(p) {
    for (const key of ["front", "staff"]) {
      const d = DOORS[key];
      if (p.x > d.x - 18 && p.x < d.x + 18 && p.y > TOP - 52 && p.y < TOP + 2) return { kind: "door", key };
    }
    if (p.x > 412 && p.x < 446 && p.y > 12 && p.y < 48) return { kind: "clock" };
    if (p.x > 466 && p.x < 554 && p.y > 10 && p.y < 56) return { kind: "board" };
    if (p.x > 248 && p.x < 392 && p.y > 12 && p.y < 42) return { kind: "sign" };
    if (guide.on) {
      const g = guide.walker || guide;
      if (Math.abs(p.x - g.x) < 14 && p.y > g.y - 34 && p.y < g.y + 12) return { kind: "guide" };
    }
    for (let i = 0; i < order.length; i++) {
      const { cx, y0 } = cellOf(i);
      if (p.x > cx - 44 && p.x < cx + 44 && p.y > y0 - 6 && p.y < y0 + 74) return { kind: "agent", name: order[i] };
    }
    const b = brainPos();
    if (Math.abs(p.x - b.x) < 34 && p.y > b.y - 4 && p.y < b.y + 52) return { kind: "brain" };
    for (const key of presentStations()) {
      const s = stationPos(key);
      if (Math.abs(p.x - s.x) < 28 && p.y > s.y - 4 && p.y < s.y + 52) return { kind: "station", key };
    }
    return null;
  }

  function describeHit(hit) {
    if (hit.kind === "agent") {
      const a = agents.get(hit.name);
      const state = !a.runnable ? "Out of order: some tools are not built yet" :
        a.status === "working" ? "Working right now" : a.status === "queued" ? "Waiting for the model" : "At their desk";
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
    }
    if (hit.kind === "door") {
      return hit.key === "front" ? ["Front door", "Where visitors come in", "Click to open or close it"]
        : ["Staff door", "Newly hired agents come in through here", "Click to open or close it"];
    }
    if (hit.kind === "guide") return [GUIDE_NAME, "Front desk guide", "Click to talk to her"];
    if (hit.kind === "clock") return ["Office clock", new Date().toLocaleString([], { weekday: "long", hour: "2-digit", minute: "2-digit" })];
    if (hit.kind === "board") return ["Blueprint board", "New agent plans are pinned up here"];
    return ["AgentFactory", "Everything here runs on this computer"];
  }

  function showTip(event, hit) {
    if (!tipEl) return;
    if (!hit) { tipEl.hidden = true; return; }
    const [title, ...rest] = describeHit(hit);
    tipEl.replaceChildren();
    const h = document.createElement("strong");
    h.textContent = title;
    tipEl.append(h);
    for (const line of rest) {
      const p = document.createElement("span");
      p.textContent = line;
      tipEl.append(p);
    }
    tipEl.hidden = false;
    const box = view.parentElement.getBoundingClientRect();
    const x = Math.min(event.clientX - box.left + 14, box.width - tipEl.offsetWidth - 6);
    const y = Math.min(event.clientY - box.top + 16, box.height - tipEl.offsetHeight - 6);
    tipEl.style.transform = `translate(${Math.max(4, x)}px, ${Math.max(4, y)}px)`;
  }

  function activate(hit) {
    if (!hit) return;
    if (hit.kind === "agent") onPick(hit.name);
    else if (hit.kind === "guide") onGuide();
    else if (hit.kind === "brain") { for (const a of agents.values()) if (a.status !== "idle") a.pulseUntil = clock + 2; }
    else if (hit.kind === "station") {
      for (const a of agents.values()) if ((a.tools || []).some((t) => stationOf(t) === hit.key)) a.pulseUntil = clock + 2;
    }
    else if (hit.kind === "door") doorState[hit.key].target = doorState[hit.key].target ? 0 : 1;
  }

  function announce(name) {
    if (!liveEl) return;
    const a = agents.get(name);
    liveEl.textContent = a ? `${a.label}, ${a.mode === "task" ? "task" : "chat"} agent. Press Enter to open the chat.` : "";
  }

  function onKey(event) {
    if (!order.length) return;
    const keys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"];
    if (keys.includes(event.key)) {
      event.preventDefault();
      let i = order.indexOf(focusName);
      if (i < 0) i = Math.max(0, order.indexOf(selected));
      else if (event.key === "ArrowLeft") i = Math.max(0, i - 1);
      else if (event.key === "ArrowRight") i = Math.min(order.length - 1, i + 1);
      else if (event.key === "ArrowUp") i = Math.max(0, i - COLS);
      else i = Math.min(order.length - 1, i + COLS);
      focusName = order[i];
      announce(focusName);
    } else if ((event.key === "Enter" || event.key === " ") && focusName) {
      event.preventDefault();
      onPick(focusName);
    } else if ((event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) && focusName) {
      event.preventDefault();
      const r = view.getBoundingClientRect();
      const { cx, y0 } = cellOf(order.indexOf(focusName));
      onMenu(focusName, r.left + (cx / W) * r.width, r.top + ((y0 + 30) / H) * r.height);
    }
  }

  // ---------- public interface ----------

  function init(options) {
    view = options.canvas;
    tipEl = options.tip || null;
    liveEl = options.live || null;
    onPick = options.onPick || onPick;
    onGuide = options.onGuide || onGuide;
    onMenu = options.onMenu || onMenu;
    vctx = view.getContext("2d");
    buffer = document.createElement("canvas");
    bctx = buffer.getContext("2d");

    view.addEventListener("pointermove", (event) => {
      const hit = hitTest(toLogical(event));
      hover = hit && hit.kind === "agent" ? hit.name : null;
      view.style.cursor = hit && ["agent", "door", "guide", "brain", "station"].includes(hit.kind) ? "pointer" : "default";
      showTip(event, hit);
    });
    view.addEventListener("pointerleave", () => { hover = null; if (tipEl) tipEl.hidden = true; });
    view.addEventListener("click", (event) => activate(hitTest(toLogical(event))));
    view.addEventListener("contextmenu", (event) => {
      const hit = hitTest(toLogical(event));
      if (hit && hit.kind === "agent") {
        event.preventDefault();
        onMenu(hit.name, event.clientX, event.clientY);
      }
    });
    view.addEventListener("keydown", onKey);
    view.addEventListener("focus", () => {
      if (!focusName && order.length) focusName = order.includes(selected) ? selected : order[0];
      announce(focusName);
    });
    view.addEventListener("blur", () => { focusName = null; });
    new ResizeObserver(resize).observe(view.parentElement);
    reduced.addEventListener?.("change", () => draw());
    resize();
    requestAnimationFrame(frame);
  }

  function setAgents(list) {
    const names = new Set(list.map((a) => a.name));
    for (const name of [...agents.keys()]) if (!names.has(name)) agents.delete(name);
    for (const info of list) {
      const old = agents.get(info.name);
      agents.set(info.name, {
        name: info.name, label: info.label, color: info.color, mode: info.mode, runnable: info.runnable !== false,
        hair: info.hair || null, model: info.model || "", tools: info.tools || [],
        status: info.status || "idle",
        meter: old ? old.meter : null, alert: old ? old.alert : "", lastCall: old ? old.lastCall : null,
        queuedAt: old ? old.queuedAt : 0, pulseUntil: old ? old.pulseUntil : 0,
        seated: old ? old.seated : true, walker: old ? old.walker : null,
        bubbleText: old ? old.bubbleText : "", bubbleUntil: old ? old.bubbleUntil : 0,
      });
    }
    const nextOrder = list.map((a) => a.name);
    const changed = nextOrder.join("|") !== order.join("|");
    order = nextOrder;
    if (focusName && !names.has(focusName)) focusName = null;
    if (changed) relayout();
  }

  window.Office = {
    init,
    setAgents,
    select(name) { selected = name; },
    highlight(name) { highlighted = name; },
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
    say(name, str, seconds = 4) {
      const a = agents.get(name);
      if (a) { a.bubbleText = str; a.bubbleUntil = clock + seconds; }
    },
    walkIn,
    walkOut,
    portrait,
    guide: guideApi,
    resize,
    isWalking: () => [...agents.values()].some((a) => a.walker),
  };
})();
