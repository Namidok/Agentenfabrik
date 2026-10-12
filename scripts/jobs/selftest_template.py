"""Fidelity self-test: render the master CV's own content through the template and compare it with the
original PDF, pixel by pixel and structurally. Writes templates/fidelity_report_vN.json and a diff image.

The template only counts as a match below the thresholds; the user approves the result.

Arguments (JSON, optional): {"profile": "data/jobs/profile_v1.json"}
Prints: {"ok", "score", "verdict", "pixel_mismatch_pct", "mean_line_offset_pt", "report", ...}"""
from __future__ import annotations

import struct
import subprocess
import zlib
from pathlib import Path

from common import DATA, ME, INPUTS, ROOT, TEMPLATES, args, done, fail, latest, next_version, read_json, rel, today, write_json
from render_lib import cv_html, pdf_facts, print_pdf

DPI_WIDTH = 1240  # A4 at 150 dpi
PIXEL_OK = 1.5    # % of pixels allowed to differ by more than 1 px of shift, for a "match"
OFFSET_OK = 1.0   # mean vertical offset of matched text lines allowed, in pt


def rasterize(pdf: Path, out_dir: Path) -> Path:
    """PDF page -> PNG at 150 dpi with macOS Quick Look, -> BMP with sips (easy to read without libraries)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["qlmanage", "-t", "-s", str(round(DPI_WIDTH * 297 / 210)), "-o", str(out_dir), str(pdf)],
                   capture_output=True, timeout=60, check=True)
    png = out_dir / f"{pdf.name}.png"
    bmp = out_dir / f"{pdf.stem}.bmp"
    subprocess.run(["sips", "-s", "format", "bmp", str(png), "--out", str(bmp)], capture_output=True, timeout=60, check=True)
    return bmp


def read_bmp(path: Path) -> tuple[int, int, list[int]]:
    """Grey values (0-255), top row first."""
    data = path.read_bytes()
    offset = struct.unpack_from("<I", data, 10)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    bpp = struct.unpack_from("<H", data, 28)[0] // 8
    stride = (width * bpp + 3) & ~3
    rows = range(abs(height) - 1, -1, -1) if height > 0 else range(abs(height))
    grey: list[int] = []
    for y in rows:
        start = offset + y * stride
        row = data[start:start + width * bpp]
        grey += [(row[i] * 114 + row[i + 1] * 587 + row[i + 2] * 299) // 1000 for i in range(0, len(row), bpp)]
    return width, abs(height), grey


def write_png(path: Path, width: int, height: int, rgb: bytes) -> None:
    raw = b"".join(b"\x00" + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    chunk = lambda kind, body: struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)  # noqa: E731
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def pixel_diff(a: Path, b: Path, out: Path) -> float:
    """% of pixels that differ clearly (grey difference > 64); writes a diff image (red = only in the render,
    blue = only in the original)."""
    w1, h1, g1 = read_bmp(a)
    w2, h2, g2 = read_bmp(b)
    w, h = min(w1, w2), min(h1, h2)
    rgb = bytearray()
    differ = 0
    for y in range(h):
        for x in range(w):
            p, q = g1[y * w1 + x], g2[y * w2 + x]
            if abs(p - q) > 64:
                differ += 1
                rgb += b"\xdd\x22\x22" if q < p else b"\x22\x44\xdd"
            else:
                v = 255 - (255 - min(p, q)) // 4
                rgb += bytes((v, v, v))
    write_png(out, w, h, bytes(rgb))
    return 100 * differ / (w * h)


def tolerant_diff(a: Path, b: Path, radius: int = 1) -> float:
    """% of dark pixels in either image with no similar pixel within `radius` px in the other one.
    A 1 px shift of anti-aliased text is rounding, not a layout difference, so it does not count."""
    w1, h1, g1 = read_bmp(a)
    w2, h2, g2 = read_bmp(b)
    w, h = min(w1, w2), min(h1, h2)

    def unmatched(src, sw, dst, dw) -> int:
        bad = 0
        for y in range(radius, h - radius):
            row = y * sw
            for x in range(radius, w - radius):
                v = src[row + x]
                if v > 160:
                    continue  # only ink counts
                if not any(abs(dst[(y + dy) * dw + x + dx] - v) <= 64 for dy in (-1, 0, 1) for dx in (-1, 0, 1)):
                    bad += 1
        return bad
    return 100 * (unmatched(g1, w1, g2, w2) + unmatched(g2, w2, g1, w1)) / (w * h)


def text_lines(pdf: Path) -> list[tuple[float, float, str]]:
    """(y, x, first characters) of each text line, for matching lines between the two PDFs."""
    import pypdf
    import unicodedata
    page = pypdf.PdfReader(str(pdf)).pages[0]
    height = float(page.mediabox.height)
    runs: list[tuple[float, float, str]] = []

    def visit(text, cm, tm, fontdict, size):
        if text.strip() and text.strip() != "•":
            runs.append((height - (tm[4] * cm[1] + tm[5] * cm[3] + cm[5]), tm[4] * cm[0] + tm[5] * cm[2] + cm[4],
                         unicodedata.normalize("NFKC", text.strip())))
    page.extract_text(visitor_text=visit)
    lines: list[list] = []
    for y, x, t in sorted(runs):
        if lines and abs(lines[-1][0] - y) <= 1.5:
            if x < lines[-1][1]:
                lines[-1][1], lines[-1][2] = x, t
        else:
            lines.append([y, x, t])
    return [(round(y, 1), round(x, 1), t[:24]) for y, x, t in lines]


def compare_lines(original: Path, render: Path) -> dict:
    a, b = text_lines(original), text_lines(render)
    pool = {t: (y, x) for y, x, t in b}
    offsets, xoffs, missing = [], [], []
    for y, x, t in a:
        if t in pool:
            offsets.append(abs(pool[t][0] - y))
            xoffs.append(abs(pool[t][1] - x))
        else:
            missing.append(t)
    worst = sorted(((abs(pool[t][0] - y), t) for y, x, t in a if t in pool), reverse=True)[:5]
    return {"lines_original": len(a), "lines_render": len(b), "matched": len(offsets),
            "mean_line_offset_pt": round(sum(offsets) / max(1, len(offsets)), 2),
            "mean_x_offset_pt": round(sum(xoffs) / max(1, len(xoffs)), 2),
            "unmatched_lines": missing[:8], "worst_lines": [{"offset_pt": round(o, 1), "line": t} for o, t in worst]}


def main() -> None:
    a = args()
    profile_path = ROOT / a["profile"] if a.get("profile") else latest(ME, "profile")
    master = INPUTS / "master_cv.pdf"
    if not profile_path or not profile_path.exists():
        fail("No profile yet: run extract_cv first.")
    if not master.exists():
        fail("No master CV at inputs/master_cv.pdf.")
    profile = read_json(profile_path)
    work = TEMPLATES / "selftest"
    render = work / "render.pdf"
    print_pdf(cv_html(profile), work / "render.html", render)
    orig_bmp, render_bmp = rasterize(master, work), rasterize(render, work)
    pixel = pixel_diff(render_bmp, orig_bmp, work / "diff.png")
    tolerant = tolerant_diff(render_bmp, orig_bmp)
    lines = compare_lines(master, render)
    o, r = pdf_facts(master), pdf_facts(render)
    fonts_missing = sorted(set(o["fonts"]) - set(r["fonts"]))
    match = (tolerant <= PIXEL_OK and lines["mean_line_offset_pt"] <= OFFSET_OK and o["pages"] == r["pages"]
             and not fonts_missing and lines["matched"] >= 0.95 * lines["lines_original"])
    score = round(max(0.0, 100 - tolerant * 10 - lines["mean_line_offset_pt"] * 10
                      - 100 * (1 - lines["matched"] / max(1, lines["lines_original"]))), 1)
    report = {"date": today(), "profile": rel(profile_path), "score": score,
              "verdict": "match (below thresholds; the user must still approve)" if match else "no match yet",
              "thresholds": {"pixel_mismatch_tolerant_pct": PIXEL_OK, "mean_line_offset_pt": OFFSET_OK},
              "pixel_mismatch_pct": round(pixel, 2), "pixel_mismatch_tolerant_pct": round(tolerant, 2), **lines,
              "pages": {"original": o["pages"], "render": r["pages"]},
              "fonts": {"original": sorted(o["fonts"]), "render": sorted(r["fonts"]), "missing": fonts_missing,
                        "all_embedded": all(r["fonts"].values())},
              "files": {"render": rel(render), "diff_image": rel(work / "diff.png")}}
    path = write_json(next_version(TEMPLATES, "fidelity_report"), report)
    done({"ok": True, "score": score, "verdict": report["verdict"], "pixel_mismatch_pct": report["pixel_mismatch_pct"],
          "pixel_mismatch_tolerant_pct": report["pixel_mismatch_tolerant_pct"],
          "mean_line_offset_pt": lines["mean_line_offset_pt"], "pages": report["pages"], "report": rel(path)})


if __name__ == "__main__":
    main()
