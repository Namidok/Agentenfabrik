"""Turn a CV or cover-letter document (JSON) into HTML in the master CV's design, print it to PDF with
headless Chrome (the engine the master CV was printed with), and check the result mechanically.

Text in documents may mark bold with **double asterisks**; everything else is escaped."""
from __future__ import annotations

import html
import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from common import TEMPLATES

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def find_chrome() -> str | None:
    return next((c for c in CHROME_CANDIDATES if Path(c).exists()), None)


def inline(text: str) -> str:
    """Escape text and turn **this** into bold."""
    out = html.escape(str(text))
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)


def _page(template: str, title: str, header: str, body: str) -> str:
    css = (TEMPLATES / "cv.css").read_text(encoding="utf-8").replace("{{FONT_DIR}}", (TEMPLATES / "fonts").as_uri())
    skeleton = (TEMPLATES / template).read_text(encoding="utf-8")
    return (skeleton.replace("{{TITLE}}", html.escape(title)).replace("{{CSS}}", css)
            .replace("{{HEADER}}", header).replace("{{BODY}}", body))


def header_html(h: dict[str, Any]) -> str:
    contact = " | ".join(inline(c) for c in h.get("contact", []))
    return (f'<h1 class="name">{inline(h["name"]).upper()}</h1>'
            f'<p class="headline">{inline(h.get("headline", ""))}</p>'
            f'<p class="contact">{contact}</p>')


def _text(item: Any) -> str:
    return item["text"] if isinstance(item, dict) else str(item)


def _bullets(items: list[Any]) -> str:
    if not items:
        return ""
    return "<ul>" + "".join(f"<li>{inline(_text(b))}</li>" for b in items) + "</ul>"


def cv_html(doc: dict[str, Any]) -> str:
    parts: list[str] = []
    summary = doc.get("summary") or []
    if summary:
        parts.append(f"<h2>Summary</h2><p>{inline(' '.join(_text(s) for s in summary))}</p>")
    skills = doc.get("skills") or []
    if skills:
        rows = "".join(f"<li><b>{inline(s['label'])}:</b> {inline(s['items'] if isinstance(s['items'], str) else ', '.join(s['items']))}</li>"
                       for s in skills)
        parts.append(f"<h2>Technical Skills</h2><ul>{rows}</ul>")
    exp = doc.get("experience") or []
    if exp:
        rows = []
        for e in exp:
            meta = " | ".join(x for x in (e.get("location"), e.get("dates")) if x)
            rows.append(f'<div class="entry"><div class="entry-head"><b>{inline(e["title"])}, {inline(e["org"])}</b>'
                        f'<span class="meta">{inline(meta)}</span></div>{_bullets(e.get("bullets", []))}</div>')
        parts.append("<h2>Professional Experience</h2>" + "".join(rows))
    projects = doc.get("projects") or []
    if projects:
        rows = []
        for p in projects:
            title = inline(p["name"]) + (f": {inline(p['tagline'])}" if p.get("tagline") else "")
            stack = "".join(f" · {inline(s)}" for s in p.get("stack", []))
            link = f' · <a class="link" href="https://{html.escape(p["link"])}">{inline(p["link"])}</a>' if p.get("link") else ""
            rows.append(f'<div class="entry project"><p class="project-head"><b>{title}</b><span class="stack">{stack}{link}</span></p>'
                        f'{_bullets(p.get("bullets", []))}</div>')
        parts.append("<h2>Projects</h2>" + "".join(rows))
    edu = doc.get("education") or []
    if edu:
        rows = []
        for e in edu:
            school_inline = f' <span class="edu-inline">· {inline(e["school"])}</span>' if e.get("school") and not e.get("note") else ""
            note = f'<div class="edu-note">{inline(e["school"])} · {inline(e["note"])}</div>' if e.get("note") else ""
            rows.append(f'<div class="entry edu"><div class="entry-head"><span><b>{inline(e["degree"])}</b>{school_inline}</span>'
                        f'<span class="meta">{inline(e.get("dates", ""))}</span></div>{note}</div>')
        parts.append("<h2>Education</h2>" + "".join(rows))
    return _page("cv_template.html", f"{doc['header']['name']} CV", header_html(doc["header"]), "".join(parts))


def letter_html(doc: dict[str, Any]) -> str:
    to = "<br>".join(inline(line) for line in doc.get("recipient", []))
    body = "".join(f"<p>{inline(p)}</p>" for p in doc.get("paragraphs", []))
    letter = (f'<div class="letter"><div class="date">{inline(doc.get("place_date", ""))}</div>'
              f'<div class="to">{to}</div><div class="subject">{inline(doc.get("subject", ""))}</div>'
              f'<div class="body"><p>{inline(doc.get("salutation", "Dear Hiring Team,"))}</p>{body}</div>'
              f'<div class="closing">{inline(doc.get("closing", "Kind regards,"))}<br><b>{inline(doc["header"]["name"])}</b></div></div>')
    return _page("cover_letter_template.html", f"{doc['header']['name']} cover letter", header_html(doc["header"]), letter)


def print_pdf(html_text: str, html_path: Path, pdf_path: Path, timeout: int = 90) -> None:
    """Save the HTML (the editable source) and print it to PDF with headless Chrome."""
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("No Chrome, Chromium or Edge found; install Google Chrome to print PDFs.")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html_text, encoding="utf-8")
    pdf_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="af-chrome-") as profile:
        # On macOS headless Chrome often writes the PDF and then never exits, so wait for a complete,
        # stable file and then end Chrome ourselves.
        proc = subprocess.Popen([chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                                 "--no-pdf-header-footer", f"--user-data-dir={profile}", f"--print-to-pdf={pdf_path}",
                                 html_path.resolve().as_uri()], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        deadline, last = time.monotonic() + timeout, -1
        try:
            while time.monotonic() < deadline:
                if pdf_path.exists():
                    size = pdf_path.stat().st_size
                    if size == last and size > 0 and pdf_path.read_bytes()[-1024:].rstrip().endswith(b"%%EOF"):
                        break
                    last = size
                if proc.poll() is not None and not pdf_path.exists():
                    break
                time.sleep(0.25)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
    if not pdf_path.exists() or not pdf_path.read_bytes()[-1024:].rstrip().endswith(b"%%EOF"):
        raise RuntimeError("Chrome did not write a complete PDF.")


def pdf_facts(path: Path) -> dict[str, Any]:
    """Page count, fonts and whether they are embedded, extractable text, and where the last text sits."""
    import pypdf
    reader = pypdf.PdfReader(str(path))
    fonts: dict[str, bool] = {}
    for page in reader.pages:
        for font in (page.get("/Resources", {}).get("/Font", {}) or {}).values():
            font = font.get_object()
            desc = font.get("/FontDescriptor")
            if desc is None and font.get("/DescendantFonts"):
                desc = font["/DescendantFonts"][0].get_object().get("/FontDescriptor")
            desc = desc.get_object() if desc is not None else {}
            name = str(font.get("/BaseFont", "?")).split("+")[-1]
            fonts[name] = any(k in desc for k in ("/FontFile", "/FontFile2", "/FontFile3"))
    lowest = 0.0
    page = reader.pages[-1]
    height = float(page.mediabox.height)

    def visit(text, cm, tm, fontdict, size):
        nonlocal lowest
        if text.strip():
            lowest = max(lowest, height - (tm[4] * cm[1] + tm[5] * cm[3] + cm[5]))
    text = "".join(p.extract_text() or "" for p in reader.pages)
    page.extract_text(visitor_text=visit)
    return {"pages": len(reader.pages), "fonts": fonts, "text_chars": len(text.strip()), "text": text,
            "last_text_y": round(lowest, 1), "page_height": round(height, 1)}


def mechanical_checks(pdf: Path, expect_pages: int, must_contain: list[str], bottom_margin_pt: float = 18) -> list[str]:
    """Problems with a rendered PDF: page count, extractable text, embedded fonts, text running off the page."""
    facts = pdf_facts(pdf)
    problems = []
    if facts["pages"] != expect_pages:
        problems.append(f"{pdf.name}: {facts['pages']} pages, the master CV has {expect_pages}")
    if facts["text_chars"] < 200:
        problems.append(f"{pdf.name}: the text cannot be extracted (an ATS could not read it)")
    flat = re.sub(r"\s+", " ", facts["text"]).lower()
    for want in must_contain:
        if re.sub(r"\s+", " ", want).lower() not in flat:
            problems.append(f"{pdf.name}: '{want}' is missing from the extracted text")
    missing = [f for f, embedded in facts["fonts"].items() if not embedded]
    if missing:
        problems.append(f"{pdf.name}: fonts not embedded: {', '.join(missing)}")
    if facts["last_text_y"] > facts["page_height"] - bottom_margin_pt:
        problems.append(f"{pdf.name}: text runs into the bottom margin (overflow)")
    return problems
