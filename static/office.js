"use strict";

// The pixel-art office, full screen. Agents rest in the chill zone and only walk to their desks
// when you give them something to do. The sky outside and the light inside follow the clock.
// app.js tells this file who works here and what they are doing; this file draws everything
// on a small 480 x 270 canvas (one art pixel per canvas pixel) that is scaled up in whole
// steps so the pixels stay sharp.

(() => {
  const P = window.Pixel, S = window.Scene, A = window.Art;
  const R = A.R, K = A.K;

  const W = 480, H = 270, WALL = 88;
  const COLS = 4, CELL_W = 64, X0 = 52, ROW0 = 106, ROW_P = 54, MAX_DESKS = 12;
  const CORR_X = 312; // the walkway between the desks and the chill zone
  const SPEED = 62; // art pixels per second
  const DOORS = { front: { x: 26, left: 10, label: "FRONT" }, staff: { x: 456, left: 440, label: "STAFF" } };
  const GUIDE_SPOT = { x: 26, y: 108 };
  const COL_X = 456, BRAIN_Y = 91, STATION_Y = 123, STATION_STEP = 29;

  const SOFA = { x: 330, y: 166 };
  const SPOTS = [
    { id: "sofa0", kind: "sit", x: 350, y: 189, exit: { x: 350, y: 207 }, grp: "south" },
    { id: "sofa1", kind: "sit", x: 362, y: 189, exit: { x: 362, y: 207 }, grp: "south" },
    { id: "sofa2", kind: "sit", x: 374, y: 189, exit: { x: 374, y: 207 }, grp: "south" },
    { id: "cof0", kind: "coffee", x: 327, y: 136, exit: { x: 327, y: 148 }, grp: "north" },
    { id: "cof1", kind: "coffee", x: 345, y: 136, exit: { x: 345, y: 148 }, grp: "north" },
    { id: "arc0", kind: "arcade", x: 402, y: 143, exit: { x: 402, y: 153 }, grp: "north" },
    { id: "arc1", kind: "arcade", x: 414, y: 143, exit: { x: 414, y: 153 }, grp: "north" },
    { id: "bean0", kind: "nap", x: 340, y: 236, exit: { x: 340, y: 252 }, grp: "south" },
    { id: "bean1", kind: "nap", x: 404, y: 244, exit: { x: 404, y: 258 }, grp: "south" },
    { id: "rug0", kind: "stand", x: 356, y: 226, exit: { x: 356, y: 226 }, grp: "south" },
    { id: "rug1", kind: "stand", x: 376, y: 234, exit: { x: 376, y: 234 }, grp: "south" },
    { id: "rug2", kind: "stand", x: 392, y: 222, exit: { x: 392, y: 222 }, grp: "south" },
    { id: "rug3", kind: "stand", x: 330, y: 220, exit: { x: 330, y: 220 }, grp: "south" },
    { id: "ext0", kind: "stand", x: 330, y: 258, exit: { x: 330, y: 258 }, grp: "south" },
    { id: "ext1", kind: "stand", x: 368, y: 258, exit: { x: 368, y: 258 }, grp: "south" },
    { id: "ext2", kind: "stand", x: 424, y: 222, exit: { x: 424, y: 222 }, grp: "south" },
    { id: "ext3", kind: "stand", x: 420, y: 258, exit: { x: 420, y: 258 }, grp: "south" },
  ];
  const SAYINGS = {
    sit: ["NICE BREAK", "AHH...", "LONG DAY?"], nap: ["ZZZ"], coffee: ["MMM, COFFEE", "NEED CAFFEINE"],
    arcade: ["GG!", "ONE MORE ROUND", "NEW HIGH SCORE!"], stand: ["HMM...", "ANY NEWS?", "STRETCH TIME"],
  };

  const STATIONS = {
    fs: { label: "FILES", color: "#8c7cf6", name: "File cabinet", what: "Reads and writes files, only in the folders each agent may use" },
    http: { label: "WEB", color: "#4da3ff", name: "Web terminal", what: "Reads pages, only on the websites each agent may visit" },
    notes: { label: "NOTES", color: "#fdcb6e", name: "Notes shelf", what: "Keeps notes between chats" },
    code: { label: "BUILD", color: "#ff9f5a", name: "Build machine", what: "Compiles and runs C++ on this computer" },
    srs: { label: "CARDS", color: "#7bd88f", name: "Flashcard box", what: "Flashcards that come back at the right time" },
  };
  const STATION_ORDER = ["fs", "http", "notes", "code", "srs"];
  const stationOf = (tool) => { const key = String(tool || "").split(/[._]/)[0]; return STATIONS[key] ? key : null; };

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const agents = new Map();
  let order = [];
  let view, vctx, buffer, g, back, tipEl, liveEl;
  let scale = 1;
  let onPick = () => {}, onGuide = () => {}, onMenu = () => {}, onBoard = () => {};
  let selected = null, highlighted = null, hover = null, hoverObj = null, focusName = null;
  let lastFrame = 0, clock = 0, lastSecond = -1, lastTimeKey = "";
  let presetIndex = 0, lampManual = null, brewUntil = 0, arcadeUntil = 0, catUntil = 0, catBubble = 0;
  const brain = { online: null, slots: 1 };
  const effects = []; // short-lived sparks: work starts, work done, dust under feet, clicks
  let fadeFrom = null, fadeUntil = 0; // the last frame before a time-of-day change, faded out on top
  let lastDraw = 0;
  const FRAME_MS = 1000 / 30; // pixel art does not need 60 frames a second
  const stationLog = new Map();
  const doorState = { front: { open: 0, target: 0 }, staff: { open: 0, target: 0 } };
  let env = S.env(12);

  const rnd = Math.round;
  const rand = (a, b) => a + Math.random() * (b - a);
  const clip = (s, n) => (s.length > n ? s.slice(0, n - 1) + "." : s);

  // ---------- time ----------

  function currentHour() {
    const preset = S.PRESETS[presetIndex];
    if (preset.hour != null) return preset.hour;
    const d = new Date();
    return d.getHours() + d.getMinutes() / 60 + d.getSeconds() / 3600;
  }

  function announceTime(force) {
    const d = new Date(), preset = S.PRESETS[presetIndex];
    const key = `${env.theme}|${env.label}|${preset.name}|${d.getMinutes()}`;
    if (!force && key === lastTimeKey) return;
    lastTimeKey = key;
    const hh = String(d.getHours()).padStart(2, "0"), mm = String(d.getMinutes()).padStart(2, "0");
    document.dispatchEvent(new CustomEvent("agentfactory:time", { detail: {
      theme: env.theme, label: env.label, clock: `${hh}:${mm}`, preview: preset.hour != null ? preset.name : null,
      wall: env.tint(K.wall), floor: env.tint(K.plankA), dark: env.dark,
    } }));
  }

  function cycleTime() {
    if (buffer && !reduced.matches) {
      fadeFrom = fadeFrom || document.createElement("canvas");
      fadeFrom.width = W; fadeFrom.height = H;
      fadeFrom.getContext("2d").drawImage(buffer, 0, 0);
      fadeUntil = clock + 0.8;
    }
    presetIndex = (presetIndex + 1) % S.PRESETS.length;
    env = S.env(currentHour());
    announceTime(true);
    return S.PRESETS[presetIndex].name;
  }

  // ---------- layout ----------

  function cellOf(index) {
    if (index < 0 || index >= MAX_DESKS) return null;
    const row = Math.floor(index / COLS), y0 = ROW0 + row * ROW_P;
    return { cx: X0 + CELL_W / 2 + (index % COLS) * CELL_W, y0, row, aisleY: y0 + 48 };
  }
  const deskOf = (a) => cellOf(order.indexOf(a.name));

  function presentStations() {
    const keys = new Set();
    for (const a of agents.values()) for (const t of a.tools || []) { const k = stationOf(t); if (k) keys.add(k); }
    return STATION_ORDER.filter((k) => keys.has(k));
  }
  const brainPos = () => ({ x: COL_X, y: BRAIN_Y });
  function stationPos(key) {
    return { x: COL_X, y: STATION_Y + Math.max(0, presentStations().indexOf(key)) * STATION_STEP };
  }
  const queueList = () => [...agents.values()].filter((a) => a.status === "queued").sort((p, q) => (p.queuedAt || 0) - (q.queuedAt || 0));
  function brainModel() {
    const list = [...agents.values()];
    const a = list.find((x) => x.status === "working") || list.find((x) => x.name === selected) || list[0];
    return a && a.model ? a.model : "model";
  }

  function resize() {
    if (!view) return;
    const box = view.parentElement, cw = box.clientWidth, ch = box.clientHeight;
    if (!cw || !ch) return;
    const dpr = window.devicePixelRatio || 1;
    // On a tall, narrow screen (a phone) the whole room would be a thin strip, so make it as tall as
    // the space between the top bar and the dock allows and let it be swiped sideways instead.
    const portrait = ch > cw * 1.15 && cw < 700;
    const raw = portrait ? (Math.max(H, ch - 150) * dpr) / H : Math.min((cw * dpr) / W, (ch * dpr) / H);
    let s = Math.floor(raw);
    // whole-number scaling keeps every pixel square, but when it would waste a lot of the window
    // (the chat is open, say) take the nearest quarter step instead
    if (!portrait && s < raw * 0.82) s = Math.floor(raw * 4) / 4;
    if (s < 1) s = Math.max(0.5, Math.min((cw * dpr) / W, (ch * dpr) / H));
    scale = s;
    const cssW = (W * s) / dpr, cssH = (H * s) / dpr;
    view.style.width = `${cssW}px`;
    view.style.height = `${cssH}px`;
    view.width = Math.max(1, rnd(W * s));
    view.height = Math.max(1, rnd(H * s));
    vctx.imageSmoothingEnabled = false;
    const pan = portrait && cssW > cw + 1;
    const top = pan ? Math.max(0, Math.round((ch - cssH) / 2)) : (ch - cssH) / 2;
    if (pan && !box.classList.contains("pan")) box.scrollLeft = 0; // start at the desks
    box.classList.toggle("pan", pan);
    box.style.setProperty("--pan-top", `${top}px`);
    // the page around the picture paints wall above this line and floor below it
    document.documentElement.style.setProperty("--wall-edge", `${top + (WALL / H) * cssH}px`);
    draw();
  }

  // ---------- the part of the room that never changes ----------

  function buildBack() {
    back = document.createElement("canvas");
    back.width = W;
    back.height = H;
    const b = back.getContext("2d");
    R(b, 0, 0, W, H, K.wall);
    R(b, 0, 60, W, 28, K.wallLow); // lower wall
    R(b, 0, 60, W, 1, K.wallTrim);
    for (let x = 0; x < W; x += 16) R(b, x, 62, 1, 26, "#d2b88c");
    R(b, 0, WALL - 4, W, 4, K.base);
    R(b, 0, WALL, W, 2, "#6a4c2e");
    for (let y = WALL + 2, row = 0; y < H; y += 12, row++) {
      R(b, 0, y, W, 12, row % 2 ? K.plankB : K.plankA);
      R(b, 0, y, W, 1, K.seam);
      for (let x = (row * 37) % 64; x < W; x += 64 + (row % 3) * 8) R(b, x, y, 1, 12, K.seam);
    }
    S.drawFrames(b);
    A.sign(b, 318, 8, 112);
    A.rug(b, 322, 204, 100, 58);
    R(b, 6, 120, 40, 4, "#e8dcc4"); // welcome mat edge by the door
    R(b, 8, 124, 36, 6, "#c4543f");
    R(b, 10, 126, 32, 2, "#e8d2a0");
  }

  // ---------- people ----------

  function reserve(a, id) { a.spotId = id; }
  const spotById = (id) => SPOTS.find((s) => s.id === id);
  function takenSpots(except) {
    const set = new Set();
    for (const o of agents.values()) if (o !== except) { if (o.spotId) set.add(o.spotId); if (o.walker && o.walker.spotId) set.add(o.walker.spotId); }
    return set;
  }
  function freeSpot(a, prefer) {
    const taken = takenSpots(a);
    const free = SPOTS.filter((s) => !taken.has(s.id) && s.id !== a.spotId);
    const pool = prefer ? free.filter((s) => s.kind === prefer) : free;
    const list = pool.length ? pool : free;
    return list.length ? list[Math.floor(Math.random() * list.length)] : SPOTS[0];
  }

  function placeInLounge(a, spot) {
    reserve(a, spot.id);
    a.x = spot.x; a.y = spot.y;
    a.place = "lounge"; a.seated = false; a.walker = null;
    a.nextRoam = clock + rand(12, 30);
    a.nextSay = clock + rand(10, 30);
  }

  function startWalk(a, path, extra) {
    const from = { x: a.x, y: a.y };
    if (reduced.matches) {
      const last = path[path.length - 1];
      a.x = last.x; a.y = last.y;
      path = [];
    }
    a.walker = { x: a.x, y: a.y, dir: "down", moving: true, path: path.slice(), trail: [from], ...extra };
    a.place = "walking";
    a.seated = false;
    if (extra.door) doorState[extra.door].target = 1;
  }

  function routeFromSpot(a, spot) { // from where it stands in the chill zone
    return [spot.exit];
  }

  function toDesk(a) {
    const cell = deskOf(a);
    if (!cell) return false;
    let path;
    if (a.place === "desk") return true;
    const spot = spotById(a.spotId);
    const startsAtDesk = false;
    path = [];
    if (spot) path.push(spot.exit, { x: CORR_X, y: spot.exit.y });
    else path.push({ x: CORR_X, y: Math.max(a.y, 150) });
    path.push({ x: CORR_X, y: cell.aisleY }, { x: cell.cx, y: cell.aisleY });
    a.spotId = null;
    startWalk(a, path, { dest: "desk", cell, fromSpot: spot ? spot.id : null, startsAtDesk });
    return true;
  }

  function toLounge(a, spot) {
    const cell = deskOf(a);
    spot = spot || freeSpot(a);
    const path = [];
    if (cell && a.place === "desk") {
      a.x = cell.cx; a.y = cell.aisleY;
      path.push({ x: CORR_X, y: cell.aisleY });
    }
    path.push({ x: CORR_X, y: spot.exit.y }, spot.exit, { x: spot.x, y: spot.y });
    startWalk(a, path, { dest: "lounge", spotId: spot.id });
  }

  function roam(a) {
    const spot = freeSpot(a);
    const from = spotById(a.spotId);
    const path = [];
    if (from) {
      path.push(from.exit);
      if (from.grp !== spot.grp) path.push({ x: CORR_X, y: from.exit.y }, { x: CORR_X, y: spot.exit.y });
    }
    path.push(spot.exit, { x: spot.x, y: spot.y });
    a.spotId = null;
    startWalk(a, path, { dest: "lounge", spotId: spot.id });
  }

  // Walks from where it is back along the way it came, to the other end.
  function turnAround(a) {
    const w = a.walker;
    if (!w || w.turned) return;
    const wantDesk = w.dest === "lounge";
    w.turned = true;
    w.path = [...w.trail].reverse();
    if (wantDesk) {
      w.dest = "desk";
      w.cell = deskOf(a);
      w.spotId = null;
    } else {
      w.dest = "lounge";
      w.spotId = w.fromSpot;
    }
  }

  function wantsDesk(a) {
    return a.runnable && !!deskOf(a) && (a.status === "working" || a.status === "queued" || clock < a.deskUntil);
  }

  function arrive(a) {
    const w = a.walker;
    a.walker = null;
    if (w.leave) {
      doorState[w.leaveDoor].target = 0;
      if (w.done) w.done(a.name);
      return;
    }
    if (w.dest === "desk" && w.cell) {
      a.place = "desk"; a.seated = true;
      a.x = w.cell.cx; a.y = w.cell.aisleY;
    } else {
      const spot = spotById(w.spotId) || SPOTS[0];
      placeInLounge(a, spot);
    }
    if (w.door) doorState[w.door].target = 0;
    if (w.done) w.done(a.name);
  }

  function advance(w, dt) {
    if (w.door && (w.y > 94 || Math.abs(w.x - DOORS[w.door].x) > 30)) { doorState[w.door].target = 0; w.door = null; }
    let budget = SPEED * dt;
    while (budget > 0 && w.path.length) {
      const p = w.path[0], dx = p.x - w.x, dy = p.y - w.y, d = Math.hypot(dx, dy);
      if (d < 0.5) { w.trail.push(w.path.shift()); continue; }
      const go = Math.min(budget, d);
      w.x += (dx / d) * go;
      w.y += (dy / d) * go;
      w.dir = Math.abs(dy) >= Math.abs(dx) ? (dy < 0 ? "up" : "down") : "down";
      budget -= go;
    }
    return !w.path.length;
  }

  function stepAgent(a, dt) {
    if (a.walker) {
      const w = a.walker;
      if (!w.leave && !w.turned) {
        const wantDesk = wantsDesk(a);
        if ((w.dest === "lounge" && wantDesk) || (w.dest === "desk" && !wantDesk && clock >= a.deskUntil && a.status === "idle")) turnAround(a);
      }
      a.x = w.x; a.y = w.y;
      if (!reduced.matches && clock >= (a.nextDust || 0)) { a.nextDust = clock + 0.22; spark("dust", a.x + rand(-3, 3), a.y + 1); }
      if (advance(w, dt)) arrive(a);
      else { a.x = w.x; a.y = w.y; }
      return;
    }
    const want = wantsDesk(a);
    if (want && a.place !== "desk") { toDesk(a); return; }
    if (!want && a.place === "desk") { toLounge(a); return; }
    if (a.place === "lounge") {
      if (clock >= a.nextRoam) roam(a);
      else if (clock >= a.nextSay && !(a.bubbleUntil > clock)) {
        const spot = spotById(a.spotId), lines = SAYINGS[spot ? spot.kind : "stand"];
        a.bubbleText = lines[Math.floor(Math.random() * lines.length)];
        a.bubbleUntil = clock + 3;
        a.nextSay = clock + rand(22, 50);
      }
    }
  }

  function walkIn(name, door, done) {
    const a = agents.get(name);
    if (!a || !DOORS[door]) return false;
    const d = DOORS[door], spot = freeSpot(a);
    a.x = d.x; a.y = 90; a.spotId = null; a.place = "walking";
    const path = [{ x: d.x, y: 97 }];
    if (door === "staff") path.push({ x: CORR_X, y: 97 });
    else path.push({ x: CORR_X, y: 97 });
    path.push({ x: CORR_X, y: spot.exit.y }, spot.exit, { x: spot.x, y: spot.y });
    startWalk(a, path, { dest: "lounge", spotId: spot.id, door, done });
    return true;
  }

  function walkOut(name, door, done) {
    const a = agents.get(name);
    if (!a || !DOORS[door]) { if (done) done(name); return false; }
    const d = DOORS[door], cell = deskOf(a), spot = spotById(a.spotId);
    const path = [];
    if (a.place === "desk" && cell) { a.x = cell.cx; a.y = cell.aisleY; path.push({ x: CORR_X, y: cell.aisleY }); }
    else if (spot) { path.push(spot.exit, { x: CORR_X, y: spot.exit.y }); }
    path.push({ x: CORR_X, y: 97 }, { x: d.x, y: 97 }, { x: d.x, y: 90 });
    a.spotId = null;
    startWalk(a, path, { dest: "out", leave: true, leaveDoor: door, done });
    doorState[door].target = 1;
    return true;
  }

  // ---------- drawing ----------

  function drawPerson(a, w) {
    const moving = !!w && w.moving && !reduced.matches, step = Math.floor(clock * 6) % 2 === 0;
    const bob = reduced.matches ? 0 : moving ? (step ? 0 : -1) : (Math.floor(clock * 1.5) % 2 ? 0 : -1);
    if (a.place === "lounge") {
      const spot = spotById(a.spotId), kind = spot ? spot.kind : "stand";
      if (kind === "sit" || kind === "nap") A.person(g, a, "sit", a.x, a.y, { asleep: kind === "nap", bob: kind === "nap" ? 2 : 0 });
      else if (kind === "coffee") A.person(g, a, "coffee", a.x, a.y, { bob });
      else if (kind === "arcade") A.person(g, a, "arcade", a.x, a.y, { bob: !reduced.matches && Math.floor(clock * 4) % 2 && arcadeUntil > clock ? -1 : 0 });
      else A.person(g, a, "stand", a.x, a.y, { dir: "down", bob });
      return;
    }
    A.person(g, a, "walk", a.x, a.y, { dir: w ? w.dir : "down", moving, step, bob });
  }

  function deskState(a) {
    return { accent: a.color, working: a.status === "working", waiting: a.status === "queued", off: !a.runnable,
      occupied: a.place === "desk", reduced: reduced.matches, clock, lit: a.place === "desk" && env.dark > 0.3 };
  }

  function drawDeskCell(a, i) {
    const cell = cellOf(i);
    A.desk(g, cell.cx, cell.y0, deskState(a));
    if (a.status === "working" && !reduced.matches && Math.random() < 0.08) {
      R(g, cell.cx - 7, cell.y0 + 2 + Math.floor(Math.random() * 7), 14, 1, "rgba(255,255,255,0.35)"); // the screen flickers
    }
    if (a.place === "desk") {
      const typing = a.status === "working" && !reduced.matches && Math.floor(clock * 7) % 2 === 0;
      A.person(g, a, "desk", cell.cx, cell.y0 + 25, { typing });
    }
  }

  function drawPlate(a, i) {
    const cell = cellOf(i), { cx, y0 } = cell;
    const accent = a.color, sel = selected === a.name, hot = highlighted === a.name || hover === a.name || (a.pulseUntil || 0) > clock || focusName === a.name;
    const working = a.status === "working", waiting = a.status === "queued";
    const ledColor = !a.runnable ? "#ffcf5a" : a.alert ? "#ff6a5a" : working ? accent : waiting ? "#ffcf5a" : "#9aa0b4";
    const label = clip(a.label.toUpperCase(), 12);
    const pw = Math.max(36, P.measure(label) + 12);
    R(g, cx - pw / 2, y0 + 37, pw, 8, sel ? P.alpha(accent, 0.95) : "rgba(30,24,40,0.92)");
    R(g, cx - pw / 2, y0 + 37, pw, 1, accent);
    P.draw(g, label, cx + 3, y0 + 39, sel ? "#ffffff" : accent, "center");
    const on = !(working && !reduced.matches && Math.floor(clock * 3) % 2);
    R(g, cx - pw / 2 + 2, y0 + 39, 3, 3, on ? ledColor : P.shade(ledColor, 0.55));
    if (a.meter && a.meter.max > 0 && a.meter.used > 0) {
      const frac = Math.min(1, a.meter.used / a.meter.max);
      R(g, cx - pw / 2, y0 + 46, pw, 2, "rgba(30,24,40,0.5)");
      R(g, cx - pw / 2, y0 + 46, Math.max(1, rnd(pw * frac)), 2, frac < 0.6 ? "#2ec4a0" : frac < 0.85 ? "#ffcf5a" : "#ff6a5a");
    }
    if (waiting) {
      R(g, cx + 16, y0 - 7, 12, 7, "#ffcf5a");
      P.draw(g, `#${queueList().indexOf(a) + 1}`, cx + 22, y0 - 6, "#2b2230", "center");
    }
    if (!a.runnable) P.draw(g, "!", cx - 26, y0 + 4, "#ffcf5a", "center", "#2b2230");
    if (sel || hot) A.selectionBrackets(g, cx - 31, y0 - 4, 62, 52, focusName === a.name ? "#ffd166" : accent, sel ? 2 : 1);
  }

  function drawLounger(a) {
    if (a.place !== "lounge" && a.place !== "walking") return;
    const sel = selected === a.name, hot = hover === a.name || highlighted === a.name || focusName === a.name || (a.pulseUntil || 0) > clock;
    if (sel || hot) {
      const bx = rnd(a.x) - 12, by = rnd(a.y) - 31;
      A.selectionBrackets(g, bx, by, 24, 34, focusName === a.name ? "#ffd166" : a.color, sel ? 2 : 1);
    }
    if (sel || hot) P.draw(g, clip(a.label.toUpperCase(), 12), a.x, a.y + 3, "#ffffff", "center", "#2b2230");
    if (a.alert) P.draw(g, "!", a.x, a.y - 38, "#ff6a5a", "center", "#2b2230");
  }

  function bubble(cx, bottomY, str) {
    const label = clip(str.toUpperCase(), 30), w = P.measure(label) + 6;
    const x = Math.max(2, Math.min(W - w - 2, Math.round(cx - w / 2))), y = Math.round(bottomY - 11);
    R(g, x - 1, y - 1, w + 2, 9, "#2b2230");
    R(g, x, y, w, 7, "#fffaf0");
    R(g, cx - 2, y + 7, 5, 3, "#2b2230");
    R(g, cx - 1, y + 7, 3, 2, "#fffaf0");
    P.draw(g, label, x + 3, y + 1, "#2b2230");
  }

  function spark(kind, x, y) {
    if (reduced.matches && kind !== "start" && kind !== "done") return;
    effects.push({ kind, x, y, born: clock, life: { dust: 0.5, click: 0.35, start: 1.1, done: 1.3 }[kind] || 1 });
    if (effects.length > 80) effects.shift();
  }

  // Where an agent's head is right now, for effects above it.
  function headOf(a) {
    const cell = deskOf(a);
    return a.place === "desk" && cell ? { x: cell.cx, y: cell.y0 - 2 } : { x: a.x, y: a.y - 34 };
  }

  function drawEffects() {
    for (let i = effects.length - 1; i >= 0; i--) {
      const e = effects[i], t = (clock - e.born) / e.life;
      if (t >= 1) { effects.splice(i, 1); continue; }
      const x = rnd(e.x), y = rnd(e.y);
      if (e.kind === "dust") {
        const r = 1 + Math.floor(t * 2);
        R(g, x - r, y - Math.floor(t * 3), r * 2, 1, `rgba(214,190,150,${0.55 * (1 - t)})`);
      } else if (e.kind === "click") {
        const r = 3 + Math.floor(t * 8), a = 0.8 * (1 - t);
        for (const [dx, dy, w, h] of [[-r, -r, r * 2, 1], [-r, r, r * 2 + 1, 1], [-r, -r, 1, r * 2], [r, -r, 1, r * 2]]) R(g, x + dx, y + dy, w, h, `rgba(255,250,240,${a})`);
      } else if (e.kind === "start") {
        // a "!" pops up and floats away: work begins
        const lift = reduced.matches ? 0 : Math.floor(Math.min(1, t * 3) * 5), y0 = y - 6 - lift;
        if (t < 0.85 || Math.floor(clock * 10) % 2) { R(g, x - 3, y0 - 1, 7, 9, "#2b2230"); R(g, x - 2, y0, 5, 7, "#ffd166"); P.draw(g, "!", x, y0 + 1, "#2b2230", "center"); }
      } else if (e.kind === "done") {
        // a little check mark with four sparks around it: work finished
        const y0 = y - 8 - (reduced.matches ? 0 : Math.floor(t * 4));
        R(g, x - 4, y0 - 1, 9, 8, "#2b2230");
        R(g, x - 3, y0, 7, 6, "#2ec4a0");
        for (const [dx, dy] of [[-2, 2], [-1, 3], [0, 4], [1, 3], [2, 2], [3, 1]]) R(g, x + dx - 1, y0 + dy - 1, 1, 1, "#ffffff");
        if (!reduced.matches) {
          const r = 6 + Math.floor(t * 6), c = `rgba(255,209,102,${1 - t})`;
          R(g, x - r, y0 + 2, 2, 1, c); R(g, x + r - 1, y0 + 2, 2, 1, c); R(g, x, y0 - r + 2, 1, 2, c); R(g, x, y0 + r + 2, 1, 2, c);
        }
      }
    }
  }

  function drawBubbles() {
    for (const a of agents.values()) {
      if (!(a.bubbleUntil > clock) || !a.bubbleText) continue;
      const i = order.indexOf(a.name), cell = cellOf(i);
      if (a.place === "desk" && cell) bubble(cell.cx, cell.y0 + 8, a.bubbleText);
      else bubble(a.x, a.y - 30, a.bubbleText);
    }
    if (guide.bubbleUntil > clock && guide.bubbleText) bubble(guide.walker ? guide.walker.x : GUIDE_SPOT.x + 4, (guide.walker ? guide.walker.y : GUIDE_SPOT.y) - 30, guide.bubbleText);
    if (catBubble > clock) bubble(372, 232, "MEOW");
  }

  function drawStation(key) {
    const meta = STATIONS[key], { x, y } = stationPos(key), log = stationLog.get(key);
    const lit = !!log && log.until > clock;
    A.STATION_LOOK[key](g, x, y, lit, { reduced: reduced.matches, clock });
    return { x, y, lit, meta };
  }

  function plateAt(x, y, w, label, color, lit) {
    R(g, x - w / 2, y, w, 7, lit ? P.alpha(color, 0.9) : "rgba(30,24,40,0.9)");
    R(g, x - w / 2, y, w, 1, color);
    P.draw(g, label, x, y + 1, lit ? "#2b2230" : color, "center");
  }

  function drawToolsPlates() {
    const b = brainPos(), working = [...agents.values()].some((a) => a.status === "working");
    const down = brain.online === false;
    plateAt(b.x, b.y + 21, 30, down ? "OFFLINE" : "BRAIN", down ? "#ffcf5a" : "#2ec4a0", working);
    const q = queueList();
    q.slice(0, 5).forEach((a, i) => { R(g, b.x + 13, b.y + 2 + i * 4, 6, 3, a.color); });
    if (q.length) P.draw(g, `X${q.length}`, b.x + 17, b.y + 22, "#ffcf5a", "center", "#2b2230");
    for (const key of presentStations()) {
      const s = stationPos(key), log = stationLog.get(key), lit = !!log && log.until > clock;
      plateAt(s.x, s.y + 21, 30, STATIONS[key].label, STATIONS[key].color, lit);
    }
  }

  function drawBeams() {
    for (const [i, name] of order.entries()) {
      const a = agents.get(name), cell = cellOf(i);
      if (!a || !cell || a.place !== "desk") continue;
      const call = a.lastCall && a.lastCall.until > clock ? a.lastCall : null;
      let target = null, color = a.color, dim = false;
      if (call && presentStations().includes(call.key)) { const p = stationPos(call.key); target = { x: p.x, y: p.y + 10 }; }
      else if (a.status === "working") { const p = brainPos(); target = { x: p.x, y: p.y + 10 }; }
      else if (a.status === "queued") { const p = brainPos(); target = { x: p.x, y: p.y + 10 }; color = "#ffcf5a"; dim = true; }
      if (!target) continue;
      const sx = cell.cx, sy = cell.y0 + 4, dist = Math.hypot(target.x - sx, target.y - sy), n = Math.max(2, Math.floor(dist / 6));
      const drift = reduced.matches || dim ? 0 : (clock * 1.2) % 1;
      for (let k = 0; k < n; k++) {
        const t = ((k + drift) % n) / n;
        R(g, sx + (target.x - sx) * t, sy + (target.y - sy) * t, 2, 2, P.alpha(color, dim ? 0.4 : 0.95));
      }
    }
  }

  function lampOn() { return lampManual != null ? lampManual : env.dark > 0.35; }

  function draw() {
    if (!g) return;
    env = S.env(currentHour());
    g.globalCompositeOperation = "source-over";
    if (!back) buildBack();
    g.drawImage(back, 0, 0);
    S.drawBeams(g, env, 96, 200);

    // things on the wall
    const date = new Date();
    for (const key of ["front", "staff"]) A.door(g, DOORS[key].left, key, doorState[key].open, DOORS[key].label);
    A.clockFace(g, 333, 46, date);
    A.board(g, 352, 34, order.map((n) => agents.get(n).color));

    // furniture and people, back to front
    const items = [];
    const add = (depth, fn) => items.push({ depth, fn });
    order.forEach((name, i) => {
      const a = agents.get(name);
      if (cellOf(i)) add(cellOf(i).y0 + 24, () => drawDeskCell(a, i));
      if (a.place === "lounge" || a.place === "walking") add(a.y, () => drawPerson(a, a.walker));
    });
    if (guide.on) add(guide.walker ? guide.walker.y : GUIDE_SPOT.y, drawGuide);
    add(SOFA.y, () => A.sofaBack(g, SOFA.x, SOFA.y));
    add(SOFA.y + 23.5, () => A.sofaFront(g, SOFA.x, SOFA.y));
    add(236.5, () => A.beanbag(g, 340, 236, "#e0709a"));
    add(244.5, () => A.beanbag(g, 404, 244, "#f2a65a"));
    add(129, () => A.counter(g, 314, 104, { clock, reduced: reduced.matches, brewing: brewUntil > clock }));
    add(132, () => A.arcade(g, 394, 92, { clock, lit: arcadeUntil > clock || [...agents.values()].some((x) => x.place === "lounge" && spotById(x.spotId) && spotById(x.spotId).kind === "arcade") }));
    add(206, () => A.lamp(g, 404, 206, lampOn()));
    add(262, () => A.plant(g, 428, 266, 1));
    add(262, () => A.plant(g, 302, 266, 1));
    add(246, () => A.cat(g, 372, 248, { clock, reduced: reduced.matches, stretch: catUntil > clock }));
    add(124, () => A.reception(g, 6, 108));
    add(BRAIN_Y + 20, () => A.rack(g, COL_X, BRAIN_Y, [...agents.values()].filter((x) => x.status === "working").length, brain.online === false, { clock, reduced: reduced.matches }));
    for (const key of presentStations()) add(stationPos(key).y + 20, () => drawStation(key));
    items.sort((p, q) => p.depth - q.depth);
    for (const item of items) item.fn();
    drawBeams();

    // the room's light, then the view outside, then lamps and screens glowing
    if (env.mul !== "#ffffff") {
      g.globalCompositeOperation = "multiply";
      R(g, 0, 0, W, H, env.mul);
      g.globalCompositeOperation = "source-over";
    }
    S.drawSky(g, env, clock);
    if (env.dark > 0.2) drawLights();

    drawEffects();

    // labels and markers, never tinted
    order.forEach((name, i) => { if (cellOf(i)) drawPlate(agents.get(name), i); });
    for (const a of agents.values()) drawLounger(a);
    drawToolsPlates();
    if (guide.on) {
      const w = guide.walker || { x: GUIDE_SPOT.x, y: GUIDE_SPOT.y };
      P.draw(g, "NOVA", w.x, w.y - 38, "#2ec4a0", "center", "#2b2230");
    }
    drawBubbles();

    if (fadeFrom && fadeUntil > clock) {
      g.globalAlpha = Math.min(1, (fadeUntil - clock) / 0.8);
      g.drawImage(fadeFrom, 0, 0);
      g.globalAlpha = 1;
    }

    vctx.imageSmoothingEnabled = false;
    vctx.clearRect(0, 0, view.width, view.height);
    vctx.drawImage(buffer, 0, 0, view.width, view.height);
  }

  function drawLights() {
    const d = Math.min(1, (env.dark - 0.2) / 0.5);
    for (const [i, name] of order.entries()) {
      const a = agents.get(name), cell = cellOf(i);
      if (!cell) continue;
      if (a.place === "desk") {
        S.glow(g, cell.cx - 18, cell.y0 + 6, 9, "#ffd98a", 0.35 * d);
        if (a.status === "working") S.glow(g, cell.cx, cell.y0 + 8, 20, a.color, 0.28 * d);
        else S.glow(g, cell.cx, cell.y0 + 6, 13, "#9ac0ff", 0.2 * d);
      }
    }
    if (lampOn()) { S.glow(g, 404, 172, 34, "#ffe27a", 0.24 * Math.max(0.5, d)); S.glow(g, 404, 190, 16, "#ffe27a", 0.18); }
    const arcadeOn = arcadeUntil > clock || [...agents.values()].some((x) => x.place === "lounge" && spotById(x.spotId) && spotById(x.spotId).kind === "arcade");
    S.glow(g, 408, 108, arcadeOn ? 26 : 16, arcadeOn ? "#7aa0ff" : "#4a50a8", 0.35 * d);
    S.glow(g, 326, 98, 14, "#ffb06a", 0.22 * d);
    S.glow(g, COL_X, BRAIN_Y + 10, 20, "#2ec4a0", 0.22 * d);
    for (const key of presentStations()) { const p = stationPos(key); S.glow(g, p.x, p.y + 10, 16, STATIONS[key].color, 0.16 * d); }
  }

  // ---------- the front-desk guide ----------

  const GUIDE_LOOK = { name: "nova", color: "#2ec4a0", hair: "#a03a6a" };
  const guide = { on: false, walker: null, done: null, bubbleText: "", bubbleUntil: 0 };

  function drawGuide() {
    const w = guide.walker || { x: GUIDE_SPOT.x, y: GUIDE_SPOT.y, dir: "down", moving: false };
    const moving = !!guide.walker && !reduced.matches, step = Math.floor(clock * 6) % 2 === 0;
    A.person(g, GUIDE_LOOK, "walk", w.x, w.y, { dir: w.dir, moving, step, bob: reduced.matches || moving ? 0 : (Math.floor(clock * 1.5) % 2 ? 0 : -1) });
  }

  function finishGuideWalk() {
    const w = guide.walker;
    guide.walker = null;
    if (w.door) doorState[w.door].target = 0;
    const done = guide.done;
    guide.done = null;
    if (done) done();
  }

  const guideApi = {
    look: GUIDE_LOOK,
    enter(done) {
      guide.on = true;
      guide.done = done || null;
      const w = { x: DOORS.front.x, y: 90, dir: "down", moving: true, door: "front", trail: [], path: [{ x: DOORS.front.x, y: 97 }, { x: GUIDE_SPOT.x, y: GUIDE_SPOT.y }] };
      if (reduced.matches) { w.x = GUIDE_SPOT.x; w.y = GUIDE_SPOT.y; w.path = []; }
      guide.walker = w;
      doorState.front.target = 1;
    },
    present() { guide.on = true; guide.walker = null; },
    say(str, seconds = 4) { guide.bubbleText = str; guide.bubbleUntil = clock + seconds; },
  };

  // ---------- frame ----------

  function frame(now) {
    requestAnimationFrame(frame);
    if (document.hidden || !view) { lastFrame = 0; return; }
    if (now - lastDraw < FRAME_MS - 2) return;
    lastDraw = now;
    const dt = Math.min(0.1, (now - (lastFrame || now)) / 1000);
    lastFrame = now;
    clock += dt;
    for (const st of Object.values(doorState)) {
      const speed = reduced.matches ? 1 : dt * 3;
      st.open += Math.sign(st.target - st.open) * Math.min(Math.abs(st.target - st.open), speed);
    }
    for (const a of agents.values()) stepAgent(a, dt);
    if (guide.walker && advance(guide.walker, dt)) finishGuideWalk();
    if (Math.floor(clock) !== lastSecond) { lastSecond = Math.floor(clock); env = S.env(currentHour()); announceTime(false); }
    draw();
  }

  // ---------- pointer, keyboard, tooltip ----------

  function toLogical(event) {
    const r = view.getBoundingClientRect();
    return { x: ((event.clientX - r.left) / r.width) * W, y: ((event.clientY - r.top) / r.height) * H };
  }
  const inside = (p, x, y, w, h) => p.x >= x && p.x < x + w && p.y >= y && p.y < y + h;

  function hitTest(p) {
    for (const a of agents.values()) {
      if ((a.place === "lounge" || a.place === "walking") && inside(p, a.x - 12, a.y - 32, 24, 36)) return { kind: "agent", name: a.name };
    }
    if (guide.on) {
      const g2 = guide.walker || GUIDE_SPOT;
      if (inside(p, g2.x - 12, g2.y - 32, 24, 36)) return { kind: "guide" };
    }
    for (let i = 0; i < order.length; i++) {
      const cell = cellOf(i);
      if (cell && inside(p, cell.cx - 31, cell.y0 - 4, 62, 52)) return { kind: "agent", name: order[i] };
    }
    for (const key of ["front", "staff"]) if (inside(p, DOORS[key].left - 3, 37, 38, 51)) return { kind: "door", key };
    if (inside(p, 6, 100, 40, 24)) return { kind: "guide" };
    for (const w of S.WINDOWS) if (inside(p, w.x - 6, w.y - 3, w.w + 12, w.h + 10)) return { kind: "window" };
    if (Math.hypot(p.x - 333, p.y - 46) < 13) return { kind: "clock" };
    if (inside(p, 352, 34, 80, 40)) return { kind: "board" };
    if (inside(p, 318, 8, 112, 17)) return { kind: "sign" };
    if (inside(p, 358, 236, 30, 16)) return { kind: "cat" };
    if (inside(p, 394, 92, 28, 40)) return { kind: "arcade" };
    if (inside(p, 316, 88, 20, 20)) return { kind: "coffee" };
    if (inside(p, 314, 104, 46, 26)) return { kind: "counter" };
    if (inside(p, 396, 164, 16, 44)) return { kind: "lamp" };
    if (inside(p, SOFA.x, SOFA.y, 64, 36)) return { kind: "sofa" };
    if (inside(p, 328, 230, 24, 16) || inside(p, 392, 238, 24, 16)) return { kind: "beanbag" };
    const b = brainPos();
    if (inside(p, b.x - 14, b.y - 2, 28, 32)) return { kind: "brain" };
    for (const key of presentStations()) {
      const s = stationPos(key);
      if (inside(p, s.x - 14, s.y, 28, 30)) return { kind: "station", key };
    }
    return null;
  }

  function placeWord(a) {
    if (a.place === "desk") return "At their desk";
    if (a.place === "walking") return a.walker && a.walker.dest === "desk" ? "Heading to their desk" : "Walking";
    const s = spotById(a.spotId);
    return !s ? "Taking a break" : { sit: "Relaxing on the sofa", nap: "Napping on a beanbag", coffee: "Getting a coffee", arcade: "Playing the arcade", stand: "Chatting on the rug" }[s.kind];
  }

  function ago(ms) {
    const s = Math.round((Date.now() - ms) / 1000);
    return s < 10 ? "just now" : s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
  }

  function describeHit(hit) {
    if (hit.kind === "agent") {
      const a = agents.get(hit.name);
      const state = !a.runnable ? "Out of order: some tools are not built yet" :
        a.status === "working" ? "Working right now" : a.status === "queued" ? "Waiting for the model" : placeWord(a);
      const lines = [a.label, `${a.mode === "task" ? "Task agent" : "Chat agent"}: ${state}`];
      if (a.status === "queued") lines.push(`Number ${queueList().indexOf(a) + 1} in line for the model`);
      if (a.meter && a.meter.max > 0) lines.push(`${a.status === "working" ? "This run" : "Last run"}: ${a.meter.used.toLocaleString()} of ${a.meter.max.toLocaleString()} tokens`);
      if (a.alert) lines.push(a.alert);
      if (a.lastWhat) lines.push(`Last: ${a.lastWhat.text}, ${ago(a.lastWhat.at)}`);
      else if (a.doneAt) lines.push(`Finished a run ${ago(a.doneAt)}`);
      lines.push("Click to chat. Right-click for more.");
      return lines;
    }
    if (hit.kind === "brain") {
      const q = queueList(), now = [...agents.values()].filter((x) => x.status === "working");
      const state = brain.online === false ? "Ollama is not reachable. Open the Ollama app."
        : now.length ? `Thinking for ${now.map((x) => x.label).join(" and ")}${brain.slots > 1 ? ` (${now.length} of ${brain.slots} slots)` : ""}` : "Idle";
      const lines = ["Brain", `${brainModel()}, running on this computer`, state];
      if (q.length) lines.push(`Waiting: ${q.map((x) => x.label).join(", ")}`);
      lines.push(`${brain.slots > 1 ? `Up to ${brain.slots} agents think` : "One agent thinks"} at a time. Click to see who is using it.`);
      return lines;
    }
    if (hit.kind === "station") {
      const meta = STATIONS[hit.key], users = [...agents.values()].filter((a) => (a.tools || []).some((t) => stationOf(t) === hit.key)), log = stationLog.get(hit.key);
      const lines = [meta.name, meta.what, `Used by: ${users.map((a) => a.label).join(", ") || "nobody"}`];
      if (log) lines.push(`Last call: ${log.by} ${log.text}`);
      lines.push("Click to see who may use it");
      return lines;
    }
    if (hit.kind === "door") return hit.key === "front" ? ["Front door", "Where visitors come in", "Click to open or close it"] : ["Staff door", "New agents walk in through here", "Click to open or close it"];
    if (hit.kind === "guide") return ["Nova", "Front desk guide", "Click to talk to her"];
    if (hit.kind === "clock") return ["Office clock", new Date().toLocaleString([], { weekday: "long", hour: "2-digit", minute: "2-digit" }), "Click to peek at another time of day"];
    if (hit.kind === "window") return ["Window", `Outside it is ${env.label.toLowerCase()}`, "Click to peek at another time of day"];
    if (hit.kind === "board") return ["Crew board", "One note for every agent", "Click to open the staff list"];
    if (hit.kind === "sign") return ["AgentFactory", "Everything here runs on this computer"];
    if (hit.kind === "coffee") return ["Coffee machine", "Click and someone will want a coffee"];
    if (hit.kind === "counter") return ["Coffee corner", "Agents come here when they need a break"];
    if (hit.kind === "arcade") return ["Arcade", "Click and someone will go and play"];
    if (hit.kind === "cat") return ["Office cat", "Please do not wake her. Click anyway."];
    if (hit.kind === "lamp") return ["Floor lamp", lampManual == null ? "Switches on by itself after dark" : "Set by hand", "Click to switch it"];
    if (hit.kind === "sofa") return ["Sofa", "Where agents rest when nothing is going on"];
    if (hit.kind === "beanbag") return ["Beanbag", "The best spot for a nap"];
    return ["AgentFactory"];
  }

  function showTip(event, hit) {
    if (!tipEl) return;
    if (!hit) { tipEl.hidden = true; return; }
    const [title, ...rest] = describeHit(hit);
    tipEl.replaceChildren();
    const h = document.createElement("strong");
    h.textContent = title;
    tipEl.append(h);
    for (const line of rest) { const p = document.createElement("span"); p.textContent = line; tipEl.append(p); }
    tipEl.hidden = false;
    const box = view.parentElement.getBoundingClientRect();
    const x = Math.min(event.clientX - box.left + 16, box.width - tipEl.offsetWidth - 6);
    const y = Math.min(event.clientY - box.top + 18, box.height - tipEl.offsetHeight - 6);
    tipEl.style.transform = `translate(${Math.max(4, x)}px, ${Math.max(4, y)}px)`;
  }

  function sendToSpot(kind, text) {
    const pool = [...agents.values()].filter((a) => a.place === "lounge" && !a.walker && !(spotById(a.spotId) && spotById(a.spotId).kind === kind));
    if (!pool.length) return;
    const a = pool[Math.floor(Math.random() * pool.length)], taken = takenSpots(a);
    const spot = SPOTS.find((s) => s.kind === kind && !taken.has(s.id));
    if (!spot) return;
    const from = spotById(a.spotId), path = [];
    if (from) { path.push(from.exit); if (from.grp !== spot.grp) path.push({ x: CORR_X, y: from.exit.y }, { x: CORR_X, y: spot.exit.y }); }
    path.push(spot.exit, { x: spot.x, y: spot.y });
    a.spotId = null;
    startWalk(a, path, { dest: "lounge", spotId: spot.id });
    a.bubbleText = text; a.bubbleUntil = clock + 3;
  }

  function activate(hit) {
    if (!hit) return;
    if (hit.kind === "agent") onPick(hit.name);
    else if (hit.kind === "guide") onGuide();
    else if (hit.kind === "board") onBoard();
    else if (hit.kind === "brain") { for (const a of agents.values()) if (a.status !== "idle") a.pulseUntil = clock + 2; }
    else if (hit.kind === "station") { for (const a of agents.values()) if ((a.tools || []).some((t) => stationOf(t) === hit.key)) a.pulseUntil = clock + 2; }
    else if (hit.kind === "door") doorState[hit.key].target = doorState[hit.key].target ? 0 : 1;
    else if (hit.kind === "clock" || hit.kind === "window") cycleTime();
    else if (hit.kind === "coffee" || hit.kind === "counter") { brewUntil = clock + 4; sendToSpot("coffee", "COFFEE TIME!"); }
    else if (hit.kind === "arcade") { arcadeUntil = clock + 10; sendToSpot("arcade", "MY TURN!"); }
    else if (hit.kind === "cat") { catUntil = clock + 2.5; catBubble = clock + 2; }
    else if (hit.kind === "lamp") lampManual = lampManual == null ? !lampOn() : lampManual ? false : null;
  }

  function announce(name) {
    if (!liveEl) return;
    const a = agents.get(name);
    liveEl.textContent = a ? `${a.label}, ${a.mode === "task" ? "task" : "chat"} agent. Press Enter to open the chat.` : "";
  }

  function onKey(event) {
    if (!order.length) return;
    if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
      event.preventDefault();
      let i = order.indexOf(focusName);
      if (i < 0) i = Math.max(0, order.indexOf(selected));
      else if (event.key === "ArrowLeft") i = Math.max(0, i - 1);
      else if (event.key === "ArrowRight") i = Math.min(order.length - 1, i + 1);
      else if (event.key === "ArrowUp") i = Math.max(0, i - COLS);
      else i = Math.min(order.length - 1, i + COLS);
      focusName = order[i];
      announce(focusName);
      const box = view.parentElement, cell = cellOf(i);
      if (box.classList.contains("pan") && cell) {
        const x = (cell.cx / W) * view.clientWidth;
        if (x < box.scrollLeft + 40 || x > box.scrollLeft + box.clientWidth - 40) box.scrollLeft = x - box.clientWidth / 2;
      }
    } else if ((event.key === "Enter" || event.key === " ") && focusName) {
      event.preventDefault();
      onPick(focusName);
    } else if ((event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) && focusName) {
      event.preventDefault();
      const r = view.getBoundingClientRect(), a = agents.get(focusName), cell = deskOf(a);
      const px = a.place === "desk" && cell ? cell.cx : a.x, py = a.place === "desk" && cell ? cell.y0 + 20 : a.y - 16;
      onMenu(focusName, r.left + (px / W) * r.width, r.top + (py / H) * r.height);
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
    onBoard = options.onBoard || onBoard;
    vctx = view.getContext("2d");
    buffer = document.createElement("canvas");
    buffer.width = W;
    buffer.height = H;
    g = buffer.getContext("2d");
    buildBack();

    view.addEventListener("pointermove", (event) => {
      const hit = hitTest(toLogical(event));
      hover = hit && hit.kind === "agent" ? hit.name : null;
      hoverObj = hit;
      view.style.cursor = hit && !["sign", "sofa", "beanbag", "counter"].includes(hit.kind) ? "pointer" : "default";
      showTip(event, hit);
    });
    view.addEventListener("pointerleave", () => { hover = null; hoverObj = null; if (tipEl) tipEl.hidden = true; });
    view.addEventListener("click", (event) => {
      const p = toLogical(event), hit = hitTest(p);
      if (hit) spark("click", p.x, p.y);
      activate(hit);
    });
    view.addEventListener("contextmenu", (event) => {
      const hit = hitTest(toLogical(event));
      if (hit && hit.kind === "agent") { event.preventDefault(); onMenu(hit.name, event.clientX, event.clientY); }
    });
    view.addEventListener("keydown", onKey);
    view.addEventListener("focus", () => {
      if (!focusName && order.length) focusName = order.includes(selected) ? selected : order[0];
      announce(focusName);
    });
    view.addEventListener("blur", () => { focusName = null; });
    new ResizeObserver(resize).observe(view.parentElement);
    reduced.addEventListener?.("change", () => draw());
    env = S.env(currentHour());
    announceTime(true);
    resize();
    requestAnimationFrame(frame);
  }

  function setAgents(list) {
    const names = new Set(list.map((a) => a.name));
    for (const name of [...agents.keys()]) if (!names.has(name)) agents.delete(name);
    const nextOrder = list.map((a) => a.name);
    order = nextOrder;
    for (const info of list) {
      const old = agents.get(info.name);
      const a = {
        name: info.name, label: info.label, color: info.color, mode: info.mode, runnable: info.runnable !== false,
        hair: info.hair || null, model: info.model || "", tools: info.tools || [], status: info.status || "idle",
        meter: old ? old.meter : null, alert: old ? old.alert : "", lastCall: old ? old.lastCall : null,
        queuedAt: old ? old.queuedAt : 0, pulseUntil: old ? old.pulseUntil : 0,
        bubbleText: old ? old.bubbleText : "", bubbleUntil: old ? old.bubbleUntil : 0,
        x: old ? old.x : 0, y: old ? old.y : 0, place: old ? old.place : "new", seated: old ? old.seated : false,
        walker: old ? old.walker : null, spotId: old ? old.spotId : null, nextRoam: old ? old.nextRoam : 0, nextSay: old ? old.nextSay : 0,
        deskUntil: old ? old.deskUntil : 0, lastWhat: old ? old.lastWhat : null, doneAt: old ? old.doneAt : 0, nextDust: 0,
      };
      agents.set(info.name, a);
    }
    for (const a of agents.values()) {
      if (a.place !== "new") continue;
      if (a.status !== "idle" && deskOf(a)) { const c = deskOf(a); a.place = "desk"; a.seated = true; a.x = c.cx; a.y = c.aisleY; continue; }
      placeInLounge(a, freeSpot(a));
    }
    if (focusName && !names.has(focusName)) focusName = null;
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
      if (status === "idle" && a.status !== "idle") a.deskUntil = clock + 3.5;
      if (status === "working" && a.status !== "working") { const h = headOf(a); spark("start", h.x, h.y); }
      if (status === "idle" && a.status === "working") { const h = headOf(a); spark("done", h.x, h.y); a.doneAt = Date.now(); }
      a.status = status;
    },
    setMeter(name, used, max) { const a = agents.get(name); if (a) a.meter = { used, max }; },
    setAlert(name, message) { const a = agents.get(name); if (a) a.alert = message || ""; },
    setBrain(info) { if ("online" in info) brain.online = info.online; if (info.slots >= 1) brain.slots = info.slots; },
    toolCall(name, tool, detail) {
      const a = agents.get(name), key = stationOf(tool);
      if (a) a.lastWhat = { text: `${tool}${detail ? ` ${String(detail).slice(0, 40)}` : ""}`, at: Date.now() };
      if (!a || !key) return;
      a.lastCall = { key, until: clock + 1.8 };
      stationLog.set(key, { until: clock + 1.8, by: a.label, text: detail || tool });
    },
    say(name, str, seconds = 4) { const a = agents.get(name); if (a) { a.bubbleText = str; a.bubbleUntil = clock + seconds; } },
    walkIn,
    walkOut,
    portrait: A.portrait,
    guide: guideApi,
    resize,
    cycleTime,
    getTime() { return { theme: env.theme, label: env.label, preview: S.PRESETS[presetIndex].hour != null ? S.PRESETS[presetIndex].name : null }; },
    isWalking: () => [...agents.values()].some((a) => a.walker),
    where(name) { const a = agents.get(name); return a ? { place: a.place, spot: a.spotId, x: Math.round(a.x), y: Math.round(a.y) } : null; },
  };
})();
