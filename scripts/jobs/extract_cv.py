"""Read the master CV (inputs/master_cv.pdf) into data/jobs/profile_vN.json.

Every summary sentence and every bullet gets a stable fact ID (F001, F002, ...) that later drafts must
cite. The layout is recognised by how text looks (size, weight, colour), the way the master CV is
printed: navy bold capitals are section headings, grey 9 pt text on the right is location and dates.
A scanned PDF (no extractable text) falls back to OCR with tesseract, and says so.

Arguments (JSON, all optional): {"pdf": "inputs/master_cv.pdf"}
Prints: {"ok", "file", "facts", "sections", "ocr", ...}"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path

from common import DATA, ME, INPUTS, ROOT, args, done, fail, next_version, rel, today, write_json, write_profile

META_GREY = "#555555"  # location and dates on the right of an entry heading


def _color(operands: list) -> str:
    try:
        return "#%02x%02x%02x" % tuple(round(float(a) * 255) for a in operands[:3])
    except (TypeError, ValueError):
        return "#000000"


def _is_accent(color: str) -> bool:
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return b - r > 0.15 and b > 0.3  # the navy of names, headings and links


def read_runs(pdf: Path) -> list[dict]:
    import pypdf
    page = pypdf.PdfReader(str(pdf)).pages[0]
    height, state, runs = float(page.mediabox.height), {"rg": "#000000"}, []

    def before(op, operands, cm, tm):
        if op == b"rg":
            state["rg"] = _color(operands)

    def visit(text, cm, tm, fontdict, size):
        if not text.strip() or text.strip() == "•":
            return
        font = str((fontdict or {}).get("/BaseFont", ""))
        text = unicodedata.normalize("NFKC", text)  # the PDF's "ﬁ" and "ﬂ" ligatures become plain "fi", "fl"
        runs.append({"y": round(height - (tm[4] * cm[1] + tm[5] * cm[3] + cm[5]), 1),
                     "x": round(tm[4] * cm[0] + tm[5] * cm[2] + cm[4], 1),
                     "size": round(size * abs(cm[3] or 1) * abs(tm[3] or 1), 1),
                     "bold": "bold" in font.lower(), "color": state["rg"], "text": text})
    page.extract_text(visitor_operand_before=before, visitor_text=visit)
    return runs


def lines_of(runs: list[dict]) -> list[dict]:
    rows: list[list[dict]] = []
    for r in sorted(runs, key=lambda r: (r["y"], r["x"])):
        if rows and abs(rows[-1][0]["y"] - r["y"]) <= 1.5:
            rows[-1].append(r)
        else:
            rows.append([r])
    return [{"y": row[0]["y"], "x": min(r["x"] for r in row), "runs": sorted(row, key=lambda r: r["x"]),
             "size": max(r["size"] for r in row)} for row in rows]


def marked(runs: list[dict]) -> str:
    """Join runs into text, with **bold** marks around bold runs inside regular text."""
    mixed = any(r["bold"] for r in runs) and not all(r["bold"] for r in runs)
    out = ""
    for r in runs:
        t = r["text"].replace("\n", " ")
        if mixed and r["bold"] and t.strip():
            lead, trail = t[: len(t) - len(t.lstrip())], t[len(t.rstrip()):]
            out += f"{lead}**{t.strip()}**{trail}"
        else:
            out += t
    return re.sub(r"\s+", " ", out).strip()


def join_lines(texts: list[str]) -> str:
    out = ""
    for t in texts:
        out = t if not out else (out + t if out.endswith("-") else out + " " + t)  # keep "self-correction"
    return re.sub(r"\s+", " ", out).strip()


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text) if s.strip()]


def parse(runs: list[dict]) -> dict:
    lines = lines_of(runs)
    sizes = [r["size"] for r in runs]
    body = max(set(sizes), key=sizes.count)
    left = min(r["x"] for r in runs)
    name_line = max(lines, key=lambda l: l["size"])
    header = {"name": " ".join(r["text"].strip() for r in name_line["runs"]).title(), "headline": "", "contact": []}
    sections: list[tuple[str, list[dict]]] = []
    for line in lines[lines.index(name_line) + 1:]:
        text = "".join(r["text"] for r in line["runs"]).strip()
        heading = all(r["bold"] for r in line["runs"]) and _is_accent(line["runs"][0]["color"]) \
            and line["size"] > body + 0.8 and text.upper() == text
        if heading:
            sections.append((text.upper(), []))
        elif sections:
            sections[-1][1].append(line)
        elif not header["headline"]:
            header["headline"] = marked(line["runs"])
        else:
            header["contact"] = [c.strip() for c in text.split("|") if c.strip()]

    profile = {"version": 1, "source": "inputs/master_cv.pdf", "extracted": today(), "header": header,
               "summary": [], "skills": [], "experience": [], "projects": [], "education": []}
    count = [0]

    def fact(text: str) -> dict:
        count[0] += 1
        return {"id": f"F{count[0]:03d}", "text": text}

    def bullets(rows: list[dict]) -> list[str]:
        """Indented lines: a bigger gap than a wrapped line (or the first line) starts a new bullet."""
        groups: list[list[str]] = []
        prev = None
        for row in rows:
            if prev is None or row["y"] - prev > body * 1.24:
                groups.append([])
            groups[-1].append(marked(row["runs"]))
            prev = row["y"]
        return [join_lines(g) for g in groups]

    for title, rows in sections:
        if "SUMMARY" in title or "PROFILE" in title:
            profile["summary"] = [fact(s) for s in sentences(join_lines([marked(r["runs"]) for r in rows]))]
        elif "SKILL" in title:
            items: list[dict] = []
            for row in rows:
                first = row["runs"][0]
                if first["bold"] and first["text"].strip().endswith(":"):
                    items.append({"label": first["text"].strip().rstrip(":"), "text": [marked(row["runs"][1:])]})
                elif items:
                    items[-1]["text"].append(marked(row["runs"]))
            profile["skills"] = [{"id": f"S{i + 1}", "label": s["label"], "items": join_lines(s["text"])} for i, s in enumerate(items)]
        elif any(k in title for k in ("EXPERIENCE", "PROJECT", "EDUCATION")):
            entries: list[dict] = []
            for row in rows:
                at_left = abs(row["x"] - left) < 3
                if at_left and row["runs"][0]["bold"]:
                    entries.append({"head": row, "extra": [], "rows": []})
                elif at_left and entries and not entries[-1]["rows"]:
                    entries[-1]["extra"].append(row)  # a wrapped heading line, or an education note
                elif entries:
                    entries[-1]["rows"].append(row)
            for e in entries:
                head = e["head"]["runs"]
                every = head + [r for x in e["extra"] for r in x["runs"]]
                bold = " ".join(r["text"].strip() for r in head if r["bold"])
                meta = " ".join(r["text"].strip() for r in every if not r["bold"] and r["x"] > 300 and r["color"] == META_GREY)
                rest = " ".join(r["text"].strip() for r in every if not r["bold"] and not (r["x"] > 300 and r["color"] == META_GREY))
                facts = [fact(b) for b in bullets(e["rows"])]
                if "EXPERIENCE" in title:
                    role, _, org = bold.rpartition(", ")
                    location, _, dates = meta.partition(" | ")
                    profile["experience"].append({"id": f"E{len(profile['experience']) + 1}", "title": role or bold, "org": org,
                                                  "location": location.strip(), "dates": dates.strip(), "bullets": facts})
                elif "PROJECT" in title:
                    name, _, tagline = bold.partition(": ")
                    pieces = [p.strip() for p in re.split(r"\s*·\s*", rest) if p.strip()]
                    link = next((p for p in pieces if re.match(r"(github\.com|gitlab\.com|https?://)", p)), "")
                    profile["projects"].append({"id": f"CP{len(profile['projects']) + 1}", "name": name.strip(), "tagline": tagline.strip(),
                                                "stack": [p for p in pieces if p != link], "link": link, "bullets": facts})
                else:
                    note_line = " ".join(r["text"].strip() for x in e["extra"] for r in x["runs"])
                    school, _, note = note_line.partition(" · ")
                    inline_school = rest.lstrip("· ").strip() if not note_line else ""
                    profile["education"].append({"id": f"ED{len(profile['education']) + 1}", "degree": bold,
                                                 "school": (school or inline_school).strip(), "note": note.strip(), "dates": meta.strip()})
    return profile


def ocr_lines(pdf: Path) -> list[str]:
    """A scanned CV: render the page with Quick Look and read it with tesseract."""
    if not shutil.which("tesseract"):
        fail("The CV has no extractable text and tesseract is not installed for OCR. Run: brew install tesseract")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["qlmanage", "-t", "-s", "3508", "-o", tmp, str(pdf)], capture_output=True, timeout=60)
        png = next(Path(tmp).glob("*.png"), None)
        if not png:
            fail("Could not render the scanned CV for OCR.")
        out = subprocess.run(["tesseract", str(png), "-", "--psm", "4"], capture_output=True, text=True, timeout=120)
    return [l.strip() for l in out.stdout.splitlines() if l.strip()]


def main() -> None:
    a = args()
    pdf = ROOT / a.get("pdf", "inputs/master_cv.pdf")
    if not pdf.is_file():
        fail(f"No CV at {rel(pdf)}. Put your master CV there first.", inputs=rel(INPUTS))
    runs = read_runs(pdf)
    ocr = sum(len(r["text"]) for r in runs) < 200
    if ocr:
        lines = ocr_lines(pdf)
        profile = {"version": 1, "source": rel(pdf), "extracted": today(), "ocr": True,
                   "header": {"name": lines[0] if lines else "", "headline": "", "contact": []},
                   "summary": [], "skills": [], "experience": [], "projects": [], "education": [],
                   "ocr_lines": [{"id": f"F{i + 1:03d}", "text": l} for i, l in enumerate(lines)]}
    else:
        profile = parse(runs)
    path = write_profile(profile)
    facts = len(profile["summary"]) + sum(len(e["bullets"]) for e in profile["experience"] + profile["projects"])
    done({"ok": True, "file": rel(path), "facts_file": rel(path.with_suffix(".md")), "ocr": ocr, "name": profile["header"]["name"], "facts": facts,
          "sections": {k: len(profile[k]) for k in ("summary", "skills", "experience", "projects", "education")},
          "next": "Scanned PDF read with OCR: check every line with the user." if ocr else
                  "fs_read the facts_file, show the user a short summary, and ask what to correct."})


if __name__ == "__main__":
    main()
