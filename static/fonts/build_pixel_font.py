"""Builds af-pixel.ttf, the 3x5 pixel font of the office signs, for the page around the office.

The glyphs are read from static/pixel.js, so the canvas and the page share one alphabet.
Run once after changing the glyphs (needs fontTools: pip install fonttools):
    python static/fonts/build_pixel_font.py
"""
import re
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

HERE = Path(__file__).resolve().parent
PX, CAP, ADVANCE = 100, 500, 400  # one pixel is 100 units; at font-size 14px one pixel is 2px

# A few marks the canvas does not need but labels on the page do.
EXTRA = {
    "=": "000,111,000,111,000", "<": "001,010,100,010,001", ">": "100,010,001,010,100",
    "[": "110,100,100,100,110", "]": "011,001,001,001,011", "&": "010,101,010,101,011",
    "@": "111,101,111,100,011", '"': "101,101,000,000,000", ";": "000,010,000,010,100",
    "|": "010,010,010,010,010", "·": "000,000,010,000,000", "^": "010,101,000,000,000",
    "\\": "100,100,010,001,001", "×": "000,101,010,101,000",
}


def read_glyphs() -> dict[str, list[str]]:
    src = (HERE.parent / "pixel.js").read_text(encoding="utf-8")
    body = src[src.index("const RAW = {"):src.index("};", src.index("const RAW = {"))]
    glyphs = {}
    for key, rows in re.findall(r'(\\u[0-9a-fA-F]{4}|"[^"]+"|[A-Za-z0-9_]+):\s*"([01,]+)"', body):
        key = key.strip('"')
        if key.startswith("\\u"):
            key = chr(int(key[2:], 16))
        if len(key) == 1:
            glyphs[key] = rows.split(",")
    glyphs.update({k: v.split(",") for k, v in EXTRA.items()})
    return glyphs


def draw(rows: list[str]):
    pen = TTGlyphPen(None)
    for r, row in enumerate(rows):
        x = 0
        while x < len(row):  # one rectangle per run of lit pixels in a row
            if row[x] != "1":
                x += 1
                continue
            start = x
            while x < len(row) and row[x] == "1":
                x += 1
            x0, x1, y1 = start * PX, x * PX, CAP - r * PX
            pen.moveTo((x0, y1 - PX)); pen.lineTo((x0, y1)); pen.lineTo((x1, y1)); pen.lineTo((x1, y1 - PX)); pen.closePath()
    return pen.glyph()


def main() -> None:
    glyphs = read_glyphs()
    names, cmap, outlines = [".notdef"], {}, {".notdef": draw(["111", "101", "101", "101", "111"])}
    for ch, rows in sorted(glyphs.items()):
        name = f"uni{ord(ch):04X}"
        names.append(name)
        outlines[name] = draw(rows)
        cmap[ord(ch)] = name
        low = ch.lower()  # small letters use the capitals, like the signs
        if low != ch and ord(low) not in cmap and low.upper() == ch:
            cmap[ord(low)] = name
    fb = FontBuilder(700, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(outlines)
    fb.setupHorizontalMetrics({n: (ADVANCE, 0) for n in names})
    fb.setupHorizontalHeader(ascent=600, descent=-200)
    fb.setupNameTable({"familyName": "AF Pixel", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=600, sTypoDescender=-200, sTypoLineGap=0, usWinAscent=600, usWinDescent=200,
                sCapHeight=CAP, sxHeight=CAP)
    fb.setupPost()
    out = HERE / "af-pixel.ttf"
    fb.save(str(out))
    print(f"wrote {out} with {len(names) - 1} glyphs")


if __name__ == "__main__":
    main()
