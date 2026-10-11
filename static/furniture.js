"use strict";

// The things in the office, drawn from rectangles at one pixel per art pixel: desks, sofa,
// coffee corner, arcade, plants, the cat, the tools and the people. office.js decides where
// they go and when. Every function takes the drawing context first.

(() => {
  const P = window.Pixel, S = window.Scene;
  const R = (g, x, y, w, h, c) => { g.fillStyle = c; g.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h)); };

  const K = {
    wall: "#f0e0c0", wallLow: "#dcc39a", wallTrim: "#a98456", base: "#8a6a46",
    plankA: "#c9996a", plankB: "#c19061", seam: "#a87848",
    wood: "#b98550", woodHi: "#d3a06a", woodDark: "#8a5e38", woodLeg: "#5e3f26",
    metal: "#8b93a8", metalDark: "#3a3f55", ink: "#2b2230", paper: "#fbf6ea",
    teal: "#3aa6a0", tealDark: "#2a7f7a", tealLight: "#5cc4bc",
  };

  // ---------- people ----------

  const HEAD_DOWN = ["...HHHH...", "..HHHHHH..", "..HSSSSH..", "..SESSES..", "..SSSSSS..", "...SSSS..."];
  const HEAD_UP = ["...HHHH...", "..HHHHHH..", "..HHHHHH..", "..HHHHHH..", "..SHHHHS..", "...SSSS..."];
  const HEAD_ZZZ = ["...HHHH...", "..HHHHHH..", "..HSSSSH..", "..SSSSSS..", "..SSSSSS..", "...SSSS..."];
  const TORSO = ["..TTTTTT..", ".TTTTTTTT.", ".STTTTTTS.", ".STtTTtTS.", "..WWWWWW.."];
  const TORSO_TYPE = ["..TTTTTT..", ".TTTTTTTT.", ".TTTTTTTT.", ".STtTTtTS.", "..WWWWWW.."];
  const TORSO_UP = ["..TTTTTT..", "STTTTTTTTS", "S.TTTTTT.S", "..TtTTtT..", "..WWWWWW.."];
  const LEGS = {
    stand: ["..PP..PP..", "..PP..PP..", "..BB..BB.."],
    stepA: ["..PP..PP..", "..PP..BB..", "..BB......"],
    stepB: ["..PP..PP..", "..BB..PP..", "......BB.."],
  };
  const SIT_LEGS = ["..PPPPPP..", "..BB..BB.."];

  function grid(g, rows, x, y, pal) {
    for (let r = 0; r < rows.length; r++) {
      const row = rows[r];
      for (let c = 0; c < row.length; c++) {
        const ch = row[c];
        if (ch !== "." && pal[ch]) R(g, x + c, y + r, 1, 1, pal[ch]);
      }
    }
  }

  const SKIN = ["#f1c27d", "#d9a066", "#a8714a", "#6b4429", "#f6d5b8"];
  const HAIR = ["#3b2a20", "#2d1f17", "#8a4b2b", "#e0b34a", "#1c1c28", "#a03a6a", "#4b6fd6", "#d8d8e8"];
  const PANTS = ["#2f2f46", "#3a4a5a", "#4a3a2f", "#27403a"];

  function hashText(text) {
    let h = 2166136261;
    for (const ch of text) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0;
    return h;
  }

  function look(agent) {
    const h = hashText(agent.name);
    const pants = PANTS[(h >> 9) % PANTS.length];
    return {
      H: agent.hair || HAIR[h % HAIR.length], S: SKIN[(h >> 5) % SKIN.length], E: "#15151f",
      T: agent.color, t: P.shade(agent.color, 0.72), W: pants, P: pants, B: "#15151f",
    };
  }

  // feetY is where the shoes touch the floor. dir is "down" (facing us) or "up" (back to us).
  // People are drawn at 2x so they read as people, not miniatures: same sprites, every pixel doubled.
  const BODY = 2;
  function person(g, agent, pose, x, feetY, o = {}) {
    g.save();
    g.translate(Math.round(x), Math.round(feetY) + (pose === "sit" ? 5 : 0));
    g.scale(BODY, BODY);
    personRaw(g, agent, pose, 0, 0, o);
    g.restore();
  }

  function personRaw(g, agent, pose, x, feetY, o = {}) {
    const pal = look(agent), left = Math.round(x) - 5, bob = o.bob || 0;
    if (pose !== "sit") R(g, left + 1, feetY - 1, 8, 2, "rgba(40,20,30,0.22)");
    if (pose === "sit") { // front view, seated; feetY is the hips
      const head = o.asleep ? HEAD_ZZZ : HEAD_DOWN;
      grid(g, [...head, ...TORSO.slice(0, 4), ...SIT_LEGS], left, feetY - 12 + bob, pal);
      return;
    }
    if (pose === "desk") { // back view at the desk
      grid(g, [...HEAD_UP, ...(o.typing ? TORSO_TYPE : TORSO).slice(0, 4)], left, feetY - 10, pal);
      return;
    }
    const up = o.dir === "up" || pose === "coffee" || pose === "arcade";
    const stepping = o.moving, phase = stepping ? (o.step ? "stepA" : "stepB") : "stand";
    const torso = pose === "arcade" ? TORSO_UP : pose === "coffee" ? TORSO_TYPE : TORSO;
    grid(g, [...(up ? HEAD_UP : HEAD_DOWN), ...torso, ...LEGS[phase]], left, feetY - 14 + bob, pal);
    if (pose === "coffee") { R(g, left + 8, feetY - 9 + bob, 2, 2, "#ffffff"); R(g, left + 8, feetY - 10 + bob, 1, 1, "rgba(255,255,255,0.6)"); }
  }

  // A face and shoulders for avatars on the page.
  function portrait(canvas, info) {
    const pal = look({ name: info.name, color: info.color, hair: info.hair || null });
    P.icon(canvas, [...HEAD_DOWN, ...TORSO.slice(0, 3)].map((row) => row.replace(/[HSETtWPB]/g, (c) => c)), pal);
  }

  // ---------- desk ----------

  function desk(g, cx, y0, o) {
    const accent = o.accent;
    // monitor
    R(g, cx - 9, y0, 18, 11, "#2f3347");
    R(g, cx - 9, y0, 18, 1, "#4a5070");
    R(g, cx - 7, y0 + 2, 14, 7, "#12151f");
    if (o.off) {
      R(g, cx - 7, y0 + 2, 14, 7, "#2a2030");
      R(g, cx - 2, y0 + 4, 4, 3, "#ffb24a");
    } else if (o.working) {
      R(g, cx - 7, y0 + 2, 14, 7, P.alpha(accent, 0.3));
      const shift = o.reduced ? 0 : Math.floor(o.clock * 6) % 5;
      for (let i = 0; i < 3; i++) R(g, cx - 6, y0 + 3 + i * 2, 4 + ((i * 5 + shift * 3) % 9), 1, accent);
    } else if (o.waiting) {
      const n = o.reduced ? 2 : Math.floor(o.clock * 2) % 3;
      for (let i = 0; i <= n; i++) R(g, cx - 5 + i * 4, y0 + 5, 2, 2, "#ffcf5a");
    } else if (o.occupied) {
      R(g, cx - 6, y0 + 3, 8, 1, P.alpha(accent, 0.7));
      R(g, cx - 6, y0 + 5, 5, 1, P.alpha(accent, 0.5));
    } else {
      const bx = o.reduced ? 3 : Math.floor(o.clock * 6) % 12, by = (bx * 3) % 5;
      R(g, cx - 6 + bx, y0 + 3 + by, 2, 2, P.alpha(accent, 0.55));
    }
    R(g, cx - 2, y0 + 11, 4, 2, "#2f3347");
    R(g, cx - 5, y0 + 12, 10, 1, "#2f3347");
    // desk
    R(g, cx - 22, y0 + 13, 44, 7, K.wood);
    R(g, cx - 22, y0 + 13, 44, 1, K.woodHi);
    R(g, cx - 22, y0 + 20, 44, 4, K.woodDark);
    R(g, cx - 20, y0 + 24, 3, 5, K.woodLeg);
    R(g, cx + 17, y0 + 24, 3, 5, K.woodLeg);
    // things on the desk
    R(g, cx - 6, y0 + 16, 12, 2, "#d8dbe8");
    R(g, cx - 5, y0 + 16, 10, 1, "#a8adc2");
    R(g, cx + 13, y0 + 14, 4, 4, P.shade(accent, 1.15));
    R(g, cx + 17, y0 + 15, 1, 2, P.shade(accent, 1.15));
    if (!o.reduced && Math.floor(o.clock * 2) % 2 === 0 && (o.occupied || o.working)) R(g, cx + 14, y0 + 11, 1, 2, "rgba(255,255,255,0.55)");
    R(g, cx - 19, y0 + 14, 7, 5, K.paper);
    R(g, cx - 18, y0 + 16, 5, 1, "#b8b2a2");
    // lamp
    R(g, cx - 18, y0 + 6, 1, 7, K.metal);
    R(g, cx - 20, y0 + 5, 5, 2, o.lit ? "#ffe27a" : "#c9b45a");
    // chair
    const out = o.occupied ? 0 : 4, sx = o.occupied ? 0 : 3;
    R(g, cx - 9 + sx, y0 + 25 + out, 18, 5, P.shade(accent, 0.55));
    R(g, cx - 9 + sx, y0 + 25 + out, 18, 1, P.shade(accent, 0.8));
    R(g, cx - 1 + sx, y0 + 30 + out, 2, 3, K.metalDark);
    R(g, cx - 5 + sx, y0 + 33 + out, 10, 1, K.metalDark);
  }

  function selectionBrackets(g, x, y, w, h, color, t = 1) {
    const l = 5;
    for (const [px, py, sx, sy] of [[x, y, 1, 1], [x + w, y, -1, 1], [x, y + h, 1, -1], [x + w, y + h, -1, -1]]) {
      R(g, sx > 0 ? px : px - l, py, l, t, color);
      R(g, px - (sx < 0 ? t : 0), sy > 0 ? py : py - l, t, l, color);
    }
  }

  // ---------- chill zone ----------

  function sofaBack(g, x, y) { // backrest, arms and the seat top
    R(g, x + 6, y, 52, 14, K.tealDark);
    R(g, x + 6, y, 52, 2, K.teal);
    R(g, x + 8, y + 3, 14, 10, P.shade(K.teal, 0.95));
    R(g, x + 25, y + 3, 14, 10, P.shade(K.teal, 0.95));
    R(g, x + 42, y + 3, 14, 10, P.shade(K.teal, 0.95));
    R(g, x, y + 7, 9, 25, K.teal);
    R(g, x, y + 7, 9, 2, K.tealLight);
    R(g, x + 55, y + 7, 9, 25, K.teal);
    R(g, x + 55, y + 7, 9, 2, K.tealLight);
    R(g, x + 9, y + 14, 46, 9, K.tealLight);
    R(g, x + 31, y + 14, 1, 9, K.teal);
  }
  function sofaFront(g, x, y) {
    R(g, x + 9, y + 23, 46, 9, K.tealDark);
    R(g, x + 9, y + 23, 46, 1, K.teal);
    R(g, x + 3, y + 32, 3, 3, K.woodLeg);
    R(g, x + 58, y + 32, 3, 3, K.woodLeg);
    R(g, x, y + 28, 9, 4, K.tealDark);
    R(g, x + 55, y + 28, 9, 4, K.tealDark);
  }

  function beanbag(g, x, y, color) { // x, y: the middle of the top
    R(g, x - 11, y - 1, 22, 11, color);
    R(g, x - 9, y - 3, 18, 3, color);
    R(g, x - 9, y - 3, 18, 1, P.shade(color, 1.25));
    R(g, x - 11, y + 8, 22, 2, P.shade(color, 0.7));
    R(g, x - 4, y + 1, 1, 6, P.shade(color, 0.8));
    R(g, x + 4, y + 1, 1, 6, P.shade(color, 0.8));
  }

  function counter(g, x, y, o) { // coffee corner; x,y is the top left of the counter top
    R(g, x, y, 46, 5, "#e8dcc4");
    R(g, x, y, 46, 1, "#fff6e0");
    R(g, x, y + 5, 46, 20, "#6e4b34");
    R(g, x, y + 5, 46, 2, "#85604a");
    R(g, x + 3, y + 9, 18, 13, "#5a3c28");
    R(g, x + 25, y + 9, 18, 13, "#5a3c28");
    R(g, x + 19, y + 15, 2, 2, "#d8b86a");
    R(g, x + 25, y + 15, 2, 2, "#d8b86a");
    // the machine
    R(g, x + 4, y - 15, 14, 15, "#3a3d4a");
    R(g, x + 4, y - 15, 14, 2, "#575b6e");
    R(g, x + 6, y - 11, 10, 5, "#1b1d28");
    R(g, x + 7, y - 4, 8, 2, "#1b1d28");
    R(g, x + 15, y - 12, 2, 2, o.brewing ? "#ff5a4a" : "#4a8a5a");
    R(g, x + 9, y - 2, 4, 2, "#f8f4ea");
    if (o.brewing || (!o.reduced && Math.floor(o.clock * 0.6) % 4 === 0)) {
      for (let k = 0; k < 2; k++) {
        const t = (o.clock * 0.9 + k * 0.5) % 1;
        R(g, x + 10 + k * 2 + Math.round(Math.sin(o.clock * 3 + k) * 1), y - 19 - Math.round(t * 8), 1, 2, `rgba(255,255,255,${0.7 * (1 - t)})`);
      }
    }
    // mugs and a bowl
    for (let k = 0; k < 3; k++) R(g, x + 24 + k * 5, y - 3, 4, 3, ["#e8564a", "#4a9ae8", "#f2c14a"][k]);
    R(g, x + 38, y - 3, 6, 3, "#c9803a");
    R(g, x + 39, y - 5, 2, 2, "#e84a4a");
    R(g, x + 42, y - 5, 2, 2, "#8ac04a");
  }

  function arcade(g, x, y, o) { // top left of the cabinet, 28 wide, 40 tall
    R(g, x, y, 28, 40, "#2c2f6e");
    R(g, x, y, 2, 40, "#1c1e4a");
    R(g, x + 26, y, 2, 40, "#1c1e4a");
    R(g, x + 2, y + 1, 24, 9, "#e0509a");
    P.draw(g, "GAME", x + 14, y + 3, "#ffffff", "center");
    R(g, x + 5, y + 12, 18, 13, "#0a0c18");
    if (o.lit) {
      const t = Math.floor(o.clock * 6);
      R(g, x + 6, y + 13, 16, 11, "#101a40");
      for (let k = 0; k < 4; k++) R(g, x + 7 + ((t * (k + 2) + k * 5) % 14), y + 14 + k * 2, 2, 1, ["#ffd24a", "#4aff9a", "#ff5a7a", "#7ad0ff"][k]);
      R(g, x + 7 + (t % 12), y + 21, 3, 2, "#ffffff");
    } else {
      R(g, x + 6, y + 13, 16, 11, "#16193a");
      if (Math.floor(o.clock * 1.5) % 2 === 0) R(g, x + 9, y + 17, 10, 3, "#8a90d8");
    }
    R(g, x + 2, y + 27, 24, 6, "#1c1e4a");
    R(g, x + 7, y + 26, 2, 4, "#ff4a4a");
    R(g, x + 6, y + 25, 4, 2, "#ff4a4a");
    R(g, x + 15, y + 28, 2, 2, "#4ac8ff");
    R(g, x + 19, y + 28, 2, 2, "#ffd24a");
    R(g, x + 4, y + 34, 20, 6, "#1c1e4a");
    R(g, x + 6, y + 36, 16, 1, "#4a50a8");
  }

  function lamp(g, x, y, on) { // y is the floor
    R(g, x - 1, y - 30, 2, 30, K.metal);
    R(g, x - 4, y - 2, 8, 2, K.metalDark);
    R(g, x - 6, y - 38, 12, 9, on ? "#ffe27a" : "#d8c26a");
    R(g, x - 6, y - 38, 12, 1, on ? "#fff4b0" : "#e8d686");
    R(g, x - 4, y - 29, 8, 1, "#a8923a");
  }

  function plant(g, x, y, s = 1) { // y is the floor
    R(g, x - 6 * s, y - 10 * s, 12 * s, 10 * s, "#b86a4a");
    R(g, x - 7 * s, y - 12 * s, 14 * s, 3 * s, "#d68a68");
    const L = ["#2f8f5b", "#37a56a", "#47b87a"];
    R(g, x - 1, y - 28 * s, 2, 16 * s, L[0]);
    R(g, x - 10 * s, y - 24 * s, 9 * s, 5 * s, L[1]);
    R(g, x + 1, y - 30 * s, 9 * s, 6 * s, L[0]);
    R(g, x - 7 * s, y - 32 * s, 7 * s, 6 * s, L[2]);
    R(g, x + 1, y - 22 * s, 10 * s, 5 * s, L[1]);
  }

  function cat(g, x, y, o) { // x, y: the middle of the cat on the floor
    const c = "#e0903f", d = "#b86a28";
    if (o.stretch) {
      R(g, x - 10, y - 5, 18, 5, c);
      R(g, x - 10, y - 5, 18, 1, "#f0aa5a");
      R(g, x + 8, y - 8, 6, 6, c);
      R(g, x + 9, y - 10, 2, 2, d);
      R(g, x + 12, y - 10, 2, 2, d);
      R(g, x + 12, y - 6, 1, 1, "#15151f");
      R(g, x - 14, y - 4, 5, 2, d);
      R(g, x - 6, y - 3, 1, 3, d);
      R(g, x + 2, y - 3, 1, 3, d);
    } else {
      const breathe = o.reduced ? 0 : Math.floor(o.clock * 0.8) % 2;
      R(g, x - 8, y - 6 - breathe, 16, 6 + breathe, c);
      R(g, x - 8, y - 6 - breathe, 16, 1, "#f0aa5a");
      R(g, x - 3, y - 6 - breathe, 1, 3, d);
      R(g, x + 1, y - 6 - breathe, 1, 3, d);
      R(g, x - 11, y - 4, 4, 3, d);
      R(g, x + 5, y - 9, 6, 5, c);
      R(g, x + 5, y - 11, 2, 2, d);
      R(g, x + 9, y - 11, 2, 2, d);
      R(g, x + 6, y - 7, 2, 1, "#15151f");
      R(g, x + 9, y - 7, 2, 1, "#15151f");
      if (!o.reduced) {
        const t = (o.clock * 0.5) % 1;
        P.draw(g, "Z", x + 12 + Math.round(t * 4), y - 14 - Math.round(t * 8), `rgba(80,70,110,${1 - t})`);
      }
    }
  }

  function rug(g, x, y, w, h) {
    R(g, x, y, w, h, "#c4543f");
    R(g, x + 2, y + 2, w - 4, h - 4, "#e8d2a0");
    R(g, x + 4, y + 4, w - 8, h - 8, "#3aa6a0");
    R(g, x + 6, y + 6, w - 12, h - 12, "#2a7f7a");
    const cx = x + w / 2, cy = y + h / 2;
    for (let k = 0; k < 4; k++) {
      R(g, cx - 14 + k * 3, cy - k * 2 - 1, 28 - k * 6, 2, k % 2 ? "#e8d2a0" : "#f2a65a");
      R(g, cx - 14 + k * 3, cy + k * 2 - 1, 28 - k * 6, 2, k % 2 ? "#e8d2a0" : "#f2a65a");
    }
    for (let k = 0; k < w; k += 4) { R(g, x + k, y - 1, 2, 1, "#e8d2a0"); R(g, x + k, y + h, 2, 1, "#e8d2a0"); }
  }

  // ---------- wall things ----------

  function door(g, x, key, openAmount, label) { // x is the left edge, 32 wide, 48 tall, standing on y=88
    const top = 40;
    R(g, x - 3, top - 3, 38, 51, "#a98456");
    R(g, x - 3, top - 3, 38, 2, "#c9a56e");
    R(g, x, top, 32, 48, "#1d1a2a");
    if (openAmount > 0.02) R(g, x + 2, top + 2, 28, 46, `rgba(255,240,190,${0.25 + 0.3 * openAmount})`);
    const leaf = Math.max(6, Math.round(32 * (1 - openAmount * 0.8)));
    const base = key === "front" ? "#8a5a34" : "#4a6a8a";
    R(g, x, top, leaf, 48, base);
    R(g, x, top, leaf, 2, P.shade(base, 1.25));
    R(g, x + 3, top + 5, Math.max(2, leaf - 7), 16, P.shade(base, 0.85));
    R(g, x + 3, top + 25, Math.max(2, leaf - 7), 18, P.shade(base, 0.85));
    R(g, x + leaf - 5, top + 26, 2, 3, "#ffd24a");
    P.draw(g, label, x + 16, top - 9, "#6a4a2a", "center");
    R(g, x + 11, top - 13, 10, 1, "#2ec4a0");
  }

  function sign(g, x, y, w) {
    R(g, x, y, w, 17, "#3a2f5a");
    R(g, x, y, w, 2, "#8c7cf6");
    R(g, x, y + 15, w, 2, "#8c7cf6");
    P.draw(g, "Kodi & Co", x + w / 2, y + 6, "#f4eaff", "center");
  }

  function clockFace(g, cx, cy, date) {
    S.disc(g, cx, cy, 11, "#7a5232");
    S.disc(g, cx, cy, 9, "#fbf6ea");
    for (let k = 0; k < 12; k++) {
      const a = (k / 12) * Math.PI * 2;
      R(g, cx + Math.round(Math.sin(a) * 7.5), cy - Math.round(Math.cos(a) * 7.5), 1, 1, "#7a6a58");
    }
    const m = date.getMinutes() + date.getSeconds() / 60, h = (date.getHours() % 12) + m / 60;
    const hand = (angle, len, color) => {
      for (let t = 0; t <= len; t++) R(g, cx + Math.round(Math.sin(angle) * t), cy - Math.round(Math.cos(angle) * t), 1, 1, color);
    };
    hand((h / 12) * Math.PI * 2, 4, "#2b2230");
    hand((m / 60) * Math.PI * 2, 7, "#2b2230");
    R(g, cx, cy, 1, 1, "#e8554e");
  }

  function board(g, x, y, notes) { // cork board with a sticky note per agent
    R(g, x, y, 80, 40, "#8a5e38");
    R(g, x + 2, y + 2, 76, 36, "#c99a5e");
    R(g, x + 2, y + 2, 76, 1, "#d8ae74");
    P.draw(g, "CREW", x + 40, y + 5, "#6a4a2a", "center");
    notes.slice(0, 12).forEach((color, i) => {
      const nx = x + 6 + (i % 6) * 12, ny = y + 15 + Math.floor(i / 6) * 11, tilt = (i * 7) % 3 - 1;
      R(g, nx, ny + tilt, 9, 8, color);
      R(g, nx, ny + tilt, 9, 1, P.shade(color, 1.2));
      R(g, nx + 1, ny + 3 + tilt, 6, 1, P.shade(color, 0.7));
      R(g, nx + 1, ny + 5 + tilt, 4, 1, P.shade(color, 0.7));
      R(g, nx + 4, ny - 1 + tilt, 1, 2, "#e8554e");
    });
  }

  function reception(g, x, y) { // counter, 40 wide; y is the top
    R(g, x, y, 40, 5, "#e8dcc4");
    R(g, x, y, 40, 1, "#fff6e0");
    R(g, x, y + 5, 40, 14, K.tealDark);
    R(g, x, y + 5, 40, 2, K.teal);
    P.draw(g, "HELLO", x + 20, y + 10, "#f4ffff", "center");
    R(g, x + 30, y - 3, 6, 3, "#ffd24a");
    R(g, x + 32, y - 5, 2, 2, "#ffd24a");
    R(g, x + 3, y - 2, 6, 2, "#ffffff");
  }

  // ---------- tools ----------

  const STATION_LOOK = {
    fs(g, x, y, lit) {
      R(g, x - 10, y + 2, 20, 18, "#8e94ad");
      R(g, x - 10, y + 2, 20, 1, "#b3b8cf");
      for (let i = 0; i < 3; i++) {
        const dy = lit && i === 0 ? 2 : 0;
        if (lit && i === 0) R(g, x - 7, y + 1, 14, 2, K.paper);
        R(g, x - 9, y + 4 + i * 5 + dy, 18, 4, "#c3c8da");
        R(g, x - 2, y + 5 + i * 5 + dy, 4, 1, "#5b6078");
      }
    },
    http(g, x, y, lit, o) {
      R(g, x - 11, y + 2, 22, 14, "#3a3d52");
      R(g, x - 9, y + 4, 18, 10, "#0f1a33");
      S.disc(g, x, y + 9, 4, "#4da3ff");
      R(g, x - 4, y + 9, 8, 1, "#0f1a33");
      R(g, x, y + 5, 1, 8, "#0f1a33");
      R(g, x - 2, y + 16, 4, 2, "#3a3d52");
      R(g, x - 6, y + 18, 12, 2, "#3a3d52");
      R(g, x + 9, y - 2, 1, 5, "#9aa0b8");
      R(g, x + 8, y - 4, 3, 2, lit && !o.reduced && Math.floor(o.clock * 6) % 2 ? "#ff7d70" : "#6b6f86");
    },
    notes(g, x, y, lit) {
      R(g, x - 11, y + 1, 22, 19, "#6e4b34");
      R(g, x - 9, y + 3, 18, 7, "#2a1c10");
      R(g, x - 9, y + 12, 18, 7, "#2a1c10");
      ["#ff7d70", "#fdcb6e", "#4da3ff", "#2ec4a0", "#f78fb3", "#8c7cf6"].forEach((c, i) => R(g, x - 8 + i * 3, y + 4 + (i % 2), 2, 6 - (i % 2), c));
      ["#8c7cf6", "#7bd88f", "#ff9f5a", "#4da3ff"].forEach((c, i) => R(g, x - 8 + i * 3, y + 13 + (i % 2), 2, 6 - (i % 2), c));
      if (lit) { R(g, x - 5, y + 9, 10, 7, K.paper); R(g, x, y + 9, 1, 7, "#9aa0b8"); }
    },
    code(g, x, y, lit, o) {
      R(g, x - 11, y + 4, 22, 16, "#3b4246");
      R(g, x - 11, y + 4, 22, 1, "#5a6468");
      R(g, x - 9, y + 6, 18, 8, "#101820");
      P.draw(g, "C++", x, y + 8, lit ? "#ff9f5a" : "#a0663a", "center");
      R(g, x - 9, y + 16, 18, 2, "#1a2022");
      const s = lit && !o.reduced ? Math.floor(o.clock * 8) % 6 : 0;
      for (let i = 0; i < 4; i++) R(g, x - 8 + i * 4 + (s % 3), y + 16, 2, 1, lit ? "#ff9f5a" : "#566266");
      if (lit && !o.reduced) R(g, x + 6 + (Math.floor(o.clock * 4) % 3), y + 1 - (Math.floor(o.clock * 4) % 3) * 2, 3, 3, "rgba(220,220,235,0.5)");
    },
    srs(g, x, y, lit) {
      R(g, x - 10, y + 10, 20, 10, "#3e6f4a");
      R(g, x - 10, y + 10, 20, 2, "#57956a");
      R(g, x - 8, y + (lit ? 1 : 4), 7, 9, K.paper);
      R(g, x - 4, y + (lit ? 0 : 2), 7, 9, "#e4e2ff");
      R(g, x, y + (lit ? 2 : 4), 7, 9, K.paper);
      R(g, x - 6, y + (lit ? 4 : 7), 4, 1, "#8e92a8");
    },
  };

  function rack(g, x, y, working, down, o) {
    R(g, x - 11, y, 22, 24, "#2d3036");
    R(g, x - 11, y, 22, 1, "#4a4f5a");
    for (let i = 0; i < 4; i++) {
      const sy = y + 2 + i * 5;
      R(g, x - 9, sy, 18, 4, "#15161c");
      const busy = typeof working === "number" ? Math.min(4, working) : working ? 4 : 0; // agents thinking right now
      const on = !down && (busy ? i < busy && (o.reduced || (Math.floor(o.clock * 5) + i) % 3 !== 0) : i === 0);
      R(g, x - 8, sy + 1, 2, 2, down ? "#ff7d70" : on ? "#2ec4a0" : "#3a3d48");
      R(g, x - 4, sy + 1, 9, 1, "#262830");
    }
  }

  window.Art = {
    K, R, grid, look, person, BODY, portrait, desk, selectionBrackets, sofaBack, sofaFront, beanbag, counter, arcade,
    lamp, plant, cat, rug, door, sign, clockFace, board, reception, STATION_LOOK, rack, hashText,
  };
})();
