"use strict";

// Pixel helpers shared by the office and the page around it: a small 3x5 bitmap font (capital letters,
// digits and a few marks), colour maths, and a tiny icon painter. Everything is drawn pixel by
// pixel, so text in the office stays as sharp as the art around it.

(() => {
  const RAW = {
    A: "010,101,111,101,101", B: "110,101,110,101,110", C: "011,100,100,100,011", D: "110,101,101,101,110",
    E: "111,100,110,100,111", F: "111,100,110,100,100", G: "011,100,101,101,011", H: "101,101,111,101,101",
    I: "111,010,010,010,111", J: "001,001,001,101,010", K: "101,101,110,101,101", L: "100,100,100,100,111",
    M: "101,111,111,101,101", N: "111,101,101,101,101", O: "010,101,101,101,010", P: "110,101,110,100,100",
    Q: "010,101,101,110,011", R: "110,101,110,101,101", S: "011,100,010,001,110", T: "111,010,010,010,010",
    U: "101,101,101,101,111", V: "101,101,101,101,010", W: "101,101,111,111,101", X: "101,101,010,101,101",
    Y: "101,101,010,010,010", Z: "111,001,010,100,111",
    0: "111,101,101,101,111", 1: "010,110,010,010,111", 2: "110,001,010,100,111", 3: "110,001,010,001,110",
    4: "101,101,111,001,001", 5: "111,100,110,001,110", 6: "011,100,111,101,111", 7: "111,001,010,010,010",
    8: "111,101,111,101,111", 9: "111,101,111,001,110",
    ".": "000,000,000,000,010", ",": "000,000,000,010,100", "!": "010,010,010,000,010", "?": "110,001,010,000,010",
    ":": "000,010,000,010,000", "-": "000,000,111,000,000", "+": "000,010,111,010,000", "'": "010,010,000,000,000",
    "/": "001,001,010,100,100", "(": "001,010,010,010,001", ")": "100,010,010,010,100", "#": "101,111,101,111,101",
    "%": "101,001,010,100,101", _: "000,000,000,000,111", "*": "000,101,010,101,000", "~": "000,011,110,000,000",
    "\u00c4": "010,101,111,101,101", "\u00d6": "010,101,101,101,010", "\u00dc": "101,101,101,101,111",
    " ": "000,000,000,000,000", "?_": "111,101,101,101,111",
  };
  const GLYPHS = {};
  for (const [ch, rows] of Object.entries(RAW)) GLYPHS[ch] = rows.split(",");

  const ADVANCE = 4, HEIGHT = 5;
  const cache = new Map();

  function glyphFor(ch) {
    return GLYPHS[ch] || GLYPHS[ch.toUpperCase()] || GLYPHS["?_"];
  }

  const clean = (str) => String(str).toUpperCase().normalize("NFC");

  function measure(str) {
    const n = [...clean(str)].length;
    return n ? n * ADVANCE - 1 : 0;
  }

  // The text as a small canvas, drawn once and reused.
  function sprite(str, color) {
    const key = `${color}|${str}`;
    let c = cache.get(key);
    if (c) return c;
    const chars = [...clean(str)];
    c = document.createElement("canvas");
    c.width = Math.max(1, measure(str));
    c.height = HEIGHT;
    const g = c.getContext("2d");
    g.fillStyle = color;
    chars.forEach((ch, i) => {
      glyphFor(ch).forEach((row, y) => {
        for (let x = 0; x < 3; x++) if (row[x] === "1") g.fillRect(i * ADVANCE + x, y, 1, 1);
      });
    });
    if (cache.size > 400) cache.clear();
    cache.set(key, c);
    return c;
  }

  // y is the top of the letters. A 1 pixel dark outline keeps text readable on any background.
  function draw(ctx, str, x, y, color, align = "left", outline = null) {
    if (!str) return;
    const w = measure(str);
    const left = Math.round(align === "center" ? x - w / 2 : align === "right" ? x - w : x), top = Math.round(y);
    if (outline) {
      const o = sprite(str, outline);
      for (const [dx, dy] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) ctx.drawImage(o, left + dx, top + dy);
    }
    ctx.drawImage(sprite(str, color), left, top);
  }

  // ---------- colours ----------

  const parse = (hex) => {
    const n = parseInt(hex.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  };
  const toHex = (rgb) => `#${rgb.map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("")}`;
  const mix = (a, b, t) => {
    const p = parse(a), q = parse(b);
    return toHex(p.map((v, i) => v + (q[i] - v) * t));
  };
  const shade = (hex, f) => toHex(parse(hex).map((v) => v * f));
  const alpha = (hex, a) => {
    const [r, g, b] = parse(hex);
    return `rgba(${r},${g},${b},${a})`;
  };

  // A small picture from rows of characters: icon(canvas, ["..##..", ...], {"#": "#fff"}).
  function icon(canvas, rows, pal) {
    canvas.width = rows[0].length;
    canvas.height = rows.length;
    const g = canvas.getContext("2d");
    g.clearRect(0, 0, canvas.width, canvas.height);
    rows.forEach((row, y) => {
      for (let x = 0; x < row.length; x++) {
        const color = pal[row[x]];
        if (color) { g.fillStyle = color; g.fillRect(x, y, 1, 1); }
      }
    });
  }

  window.Pixel = { measure, sprite, draw, mix, shade, alpha, parse, toHex, icon, HEIGHT, ADVANCE };
})();
