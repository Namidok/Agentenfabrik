"use strict";

// The world outside the office and the light inside it. Given an hour of the day it works out the
// sky, the sun or moon, how warm or dark the room is, and draws the view from the big windows.
// The office calls it every frame. Everything is drawn from plain rectangles.

(() => {
  const P = window.Pixel;

  // Keyframes: hour, sky at the top, sky at the horizon, and the colour the room is multiplied by.
  const KEYS = [
    [0, "#0b1030", "#1b2450", "#5a64a4"],
    [5, "#131a44", "#3b3a72", "#6a6fa8"],
    [6.5, "#5b7fc0", "#f4b58a", "#f3d6cc"],
    [8.5, "#5aa7ee", "#b9e0ff", "#fff4e8"],
    [12, "#3d8ee8", "#a8dcff", "#ffffff"],
    [16, "#4d96e6", "#b4defc", "#fffaf0"],
    [18, "#6a86d0", "#ffc58a", "#ffdcb8"],
    [19.5, "#5a4a98", "#ff8f6a", "#dba8b8"],
    [21, "#1d1f52", "#4a3a7a", "#7a74ae"],
    [22.5, "#0b1030", "#1b2450", "#5a64a4"],
    [24, "#0b1030", "#1b2450", "#5a64a4"],
  ];

  // Two big windows. The sky is one picture behind both.
  const WINDOWS = [{ x: 56, y: 12, w: 120, h: 60 }, { x: 188, y: 12, w: 120, h: 60 }];
  const SKY = { x0: 56, x1: 308, y0: 12, y1: 72 };

  const PRESETS = [
    { name: "LIVE", hour: null },
    { name: "MORNING", hour: 9.5 },
    { name: "AFTERNOON", hour: 13.5 },
    { name: "SUNSET", hour: 18.6 },
    { name: "DUSK", hour: 20.3 },
    { name: "NIGHT", hour: 23 },
  ];

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  function phaseOf(h) {
    if (h < 5 || h >= 21.5) return { phase: "night", theme: "night", label: "NIGHT" };
    if (h < 8) return { phase: "dawn", theme: "golden", label: "EARLY MORNING" };
    if (h < 12) return { phase: "day", theme: "day", label: "MORNING" };
    if (h < 17) return { phase: "day", theme: "day", label: "AFTERNOON" };
    if (h < 19.3) return { phase: "golden", theme: "golden", label: "EVENING" };
    return { phase: "dusk", theme: "dusk", label: "DUSK" };
  }

  function env(hour) {
    const h = ((hour % 24) + 24) % 24;
    let i = 0;
    while (i < KEYS.length - 2 && h >= KEYS[i + 1][0]) i++;
    const [h0, t0, b0, m0] = KEYS[i], [h1, t1, b1, m1] = KEYS[i + 1];
    const f = clamp((h - h0) / (h1 - h0), 0, 1);
    const mul = P.mix(m0, m1, f), [mr, mg, mb] = P.parse(mul);
    const lum = (0.3 * mr + 0.59 * mg + 0.11 * mb) / 255;
    const dark = clamp((1 - lum) / 0.55, 0, 1);
    const skyTop = P.mix(t0, t1, f), skyBot = P.mix(b0, b1, f);
    const e = {
      hour: h, ...phaseOf(h), skyTop, skyBot, mul, mulRGB: [mr / 255, mg / 255, mb / 255], dark,
      sunP: h >= 5.5 && h <= 19.5 ? (h - 5.5) / 14 : -1,
      moonP: h >= 18.5 ? (h - 18.5) / 11.5 : h <= 6.5 ? (h + 5.5) / 11.5 : -1,
      cloud: P.mix(P.mix("#ffffff", skyBot, 0.3), "#3a4272", dark * 0.8),
    };
    e.tint = (hex) => P.toHex(P.parse(hex).map((v, k) => v * e.mulRGB[k]));
    return e;
  }

  // ---------- small shapes ----------

  function disc(g, cx, cy, r, color) {
    g.fillStyle = color;
    for (let y = -r; y <= r; y++) {
      const half = Math.floor(Math.sqrt(r * r + r * 0.8 - y * y));
      if (half >= 0) g.fillRect(Math.round(cx - half), Math.round(cy + y), half * 2 + 1, 1);
    }
  }

  // A soft light made of a few flat rings. Used for lamps and screens after dark.
  function glow(g, cx, cy, r, color, a) {
    for (let k = 3; k >= 1; k--) disc(g, cx, cy, Math.round((r * k) / 3), P.alpha(color, a * (4 - k) * 0.4));
  }

  const hash = (n) => {
    let x = Math.imul(n + 0x9e3779b9, 0x85ebca6b);
    x ^= x >>> 13;
    x = Math.imul(x, 0xc2b2ae35);
    return ((x ^ (x >>> 16)) >>> 0) / 4294967295;
  };

  // ---------- the window frames (drawn with the room, so the room's light colours them) ----------

  function drawFrames(g) {
    for (const w of WINDOWS) {
      g.fillStyle = "#7a5232";
      g.fillRect(w.x - 3, w.y - 3, w.w + 6, w.h + 6);
      g.fillStyle = "#9a6c42";
      g.fillRect(w.x - 3, w.y - 3, w.w + 6, 1);
      g.fillStyle = "#4a2f1b";
      g.fillRect(w.x - 3, w.y + w.h + 2, w.w + 6, 1);
      g.fillStyle = "#c8a070";
      g.fillRect(w.x - 6, w.y + w.h + 3, w.w + 12, 3); // sill
      g.fillStyle = "#8a6a46";
      g.fillRect(w.x - 6, w.y + w.h + 6, w.w + 12, 1);
      g.fillStyle = "#cf6f4f"; // curtains
      g.fillRect(w.x - 3, w.y - 3, 7, w.h + 6);
      g.fillRect(w.x + w.w - 4, w.y - 3, 7, w.h + 6);
      g.fillStyle = "#e58a68";
      for (let y = w.y; y < w.y + w.h; y += 6) { g.fillRect(w.x - 1, y, 1, 4); g.fillRect(w.x + w.w + 1, y, 1, 4); }
      g.fillStyle = "#a9553b";
      g.fillRect(w.x - 3, w.y - 3, w.w + 6, 2); // rail
    }
  }

  // ---------- the sky (drawn after the room's tint, so it keeps its own colours) ----------

  // The sun and moon cross the sky without ever hiding behind the wall between the windows.
  function skyX(p) {
    const x = 66 + p * 206;
    return x > 166 ? x + 28 : x;
  }

  function drawSky(g, e, clock) {
    g.save();
    g.beginPath();
    for (const w of WINDOWS) g.rect(w.x + 4, w.y, w.w - 8, w.h);
    g.clip();

    const bands = 7, bandH = (SKY.y1 - SKY.y0) / bands;
    for (let b = 0; b < bands; b++) {
      g.fillStyle = P.mix(e.skyTop, e.skyBot, b / (bands - 1));
      g.fillRect(SKY.x0, Math.floor(SKY.y0 + b * bandH), SKY.x1 - SKY.x0, Math.ceil(bandH) + 1);
    }

    // stars
    const starA = clamp((e.dark - 0.55) * 2.2, 0, 1);
    if (starA > 0.02) {
      for (let k = 0; k < 34; k++) {
        const sx = SKY.x0 + 4 + Math.floor(hash(k * 3 + 1) * (SKY.x1 - SKY.x0 - 8)), sy = SKY.y0 + 2 + Math.floor(hash(k * 3 + 2) * 36);
        const tw = 0.55 + 0.45 * Math.sin(clock * (1 + hash(k)) + k);
        g.fillStyle = P.alpha("#ffffff", starA * tw);
        g.fillRect(sx, sy, 1, 1);
        if (k % 7 === 0) g.fillRect(sx - 1, sy, 3, 1), g.fillRect(sx, sy - 1, 1, 3);
      }
    }

    // sun
    if (e.sunP >= 0 && e.sunP <= 1) {
      const sx = skyX(e.sunP), sy = 60 - Math.sin(Math.PI * e.sunP) * 42;
      const warm = clamp(Math.abs(e.sunP - 0.5) * 2.2, 0, 1);
      const core = P.mix("#fff6b0", "#ff9a4a", warm), ring = P.mix("#ffe070", "#ff6a3a", warm);
      disc(g, sx, sy, 17, P.alpha(ring, 0.1));
      disc(g, sx, sy, 12, P.alpha(ring, 0.18));
      disc(g, sx, sy, 8, ring);
      disc(g, sx, sy, 6, core);
    }

    // moon
    if (e.moonP >= 0 && e.moonP <= 1 && e.dark > 0.3) {
      const mx = skyX(e.moonP), my = 56 - Math.sin(Math.PI * e.moonP) * 38;
      disc(g, mx, my, 11, P.alpha("#cfd8ff", 0.1));
      disc(g, mx, my, 7, "#eef0ff");
      disc(g, mx + 3, my - 1, 6, P.mix(e.skyTop, e.skyBot, clamp((my - SKY.y0) / 60, 0, 1)));
      g.fillStyle = "#cfd4ee";
      g.fillRect(mx - 4, my + 1, 1, 1);
      g.fillRect(mx - 3, my - 2, 1, 1);
    }

    // clouds
    const span = SKY.x1 - SKY.x0 + 90;
    [[0, 20, 1], [70, 36, 0.8], [140, 14, 1.2], [210, 30, 0.9]].forEach(([base, y, s], k) => {
      const x = SKY.x0 - 45 + ((base + clock * (2.2 + k * 0.5)) % span);
      g.fillStyle = e.cloud;
      g.fillRect(Math.round(x), y + Math.round(4 * s), Math.round(30 * s), Math.round(5 * s));
      g.fillRect(Math.round(x + 5 * s), y + Math.round(1 * s), Math.round(14 * s), Math.round(5 * s));
      g.fillRect(Math.round(x + 14 * s), y - Math.round(2 * s), Math.round(10 * s), Math.round(6 * s));
      g.fillStyle = P.mix(e.cloud, e.skyBot, 0.45);
      g.fillRect(Math.round(x + 2 * s), y + Math.round(8 * s), Math.round(26 * s), 1);
    });

    // birds in the daytime
    if (e.dark < 0.35) {
      g.fillStyle = "#2a3350";
      for (let k = 0; k < 3; k++) {
        const bx = SKY.x0 - 20 + ((clock * (9 + k) + k * 90) % (SKY.x1 - SKY.x0 + 40)), by = 22 + k * 7 + Math.round(Math.sin(clock * 1.3 + k) * 2);
        const up = Math.floor(clock * 5 + k) % 2;
        g.fillRect(Math.round(bx), by + (up ? 0 : 1), 2, 1);
        g.fillRect(Math.round(bx) + 2, by + (up ? 1 : 0), 1, 1);
        g.fillRect(Math.round(bx) + 3, by + (up ? 0 : 1), 2, 1);
      }
    }

    // the city, far then near. At night some windows are lit.
    const far = P.mix(e.skyBot, e.dark > 0.5 ? "#2a3470" : "#7f9acb", 0.55);
    const near = P.mix(e.skyBot, e.dark > 0.5 ? "#141a3a" : "#4f6490", 0.75);
    g.fillStyle = far;
    for (let x = SKY.x0, k = 0; x < SKY.x1; k++) {
      const w = 9 + Math.floor(hash(k + 40) * 9), h = 10 + Math.floor(hash(k + 90) * 18);
      g.fillRect(x, SKY.y1 - h - 4, w, h + 4);
      x += w + 1;
    }
    g.fillStyle = near;
    const lit = [];
    for (let x = SKY.x0 - 3, k = 0; x < SKY.x1; k++) {
      const w = 12 + Math.floor(hash(k + 7) * 14), h = 8 + Math.floor(hash(k + 21) * 16);
      g.fillRect(x, SKY.y1 - h, w, h);
      for (let wy = SKY.y1 - h + 3; wy < SKY.y1 - 3; wy += 4) {
        for (let wx = x + 2; wx < x + w - 2; wx += 4) if (hash(wx * 31 + wy * 17) > 0.45) lit.push([wx, wy]);
      }
      x += w + 2;
    }
    if (e.dark > 0.4) {
      g.fillStyle = P.alpha("#ffd27a", clamp((e.dark - 0.35) * 1.6, 0, 1));
      for (const [wx, wy] of lit) g.fillRect(wx, wy, 2, 2);
    }
    // a factory chimney with a little smoke
    const cx = 262, top = SKY.y1 - 30;
    g.fillStyle = near;
    g.fillRect(cx - 14, SKY.y1 - 14, 30, 14);
    g.fillRect(cx, top, 5, 20);
    g.fillStyle = P.mix(near, "#cf5a4a", e.dark > 0.5 ? 0.15 : 0.45);
    g.fillRect(cx, top + 3, 5, 2);
    g.fillRect(cx, top + 9, 5, 2);
    for (let k = 0; k < 3; k++) {
      const t = ((clock * 0.35 + k / 3) % 1);
      g.fillStyle = P.alpha(P.mix("#ffffff", e.skyBot, 0.3 + e.dark * 0.5), 0.55 * (1 - t));
      g.fillRect(cx - 1 + Math.round(t * 9), top - 2 - Math.round(t * 16), 5 + Math.round(t * 3), 3 + Math.round(t * 2));
    }

    // glass shine
    g.fillStyle = P.alpha("#ffffff", 0.12);
    for (const w of WINDOWS) {
      g.fillRect(w.x + 14, w.y + 4, 3, 40);
      g.fillRect(w.x + 20, w.y + 4, 1, 40);
    }
    g.restore();

    // the bar down the middle of each window and the rails
    for (const w of WINDOWS) {
      g.fillStyle = e.tint("#7a5232");
      g.fillRect(w.x + Math.floor(w.w / 2) - 1, w.y, 3, w.h);
      g.fillRect(w.x + 4, w.y + 34, w.w - 8, 2);
    }
  }

  // Patches of sunlight on the floor, sliding across the room as the sun moves.
  function drawBeams(g, e, y0, y1) {
    if (e.sunP < 0 || e.sunP > 1 || e.dark > 0.45) return;
    const dir = (e.sunP - 0.5) * 2, a = 0.16 * (1 - e.dark / 0.45) * (0.5 + 0.5 * Math.sin(Math.PI * e.sunP));
    const warm = e.sunP < 0.2 || e.sunP > 0.8 ? "#ffc27a" : "#fff0b0";
    for (const w of WINDOWS) {
      for (let y = y0; y < y1; y += 2) {
        const u = (y - y0) / (y1 - y0), shift = -dir * 90 * u + dir * 0;
        g.fillStyle = P.alpha(warm, a * (1 - 0.7 * u));
        g.fillRect(Math.round(w.x + 4 + shift), y, 52, 2);
        g.fillRect(Math.round(w.x + 64 + shift), y, 52, 2);
      }
    }
  }

  window.Scene = { env, drawFrames, drawSky, drawBeams, disc, glow, hash, WINDOWS, PRESETS, phaseOf, clamp };
})();
