"""Job sources behind one small interface, so another site can replace LinkedIn without touching the rest.

A source has two calls:
    search(query)  -> list of job stubs {id, source, title, company, location, posted, link}
    detail(stub)   -> the stub plus {"description", "criteria"}
Paging, pacing, the request budget and retries are handled by the Pacer every source shares.

LinkedIn: the public, unauthenticated "jobs-guest" pages. Automated access conflicts with LinkedIn's
User Agreement (section 8.2); this is meant for low-volume personal use only, at your own risk."""
from __future__ import annotations

import html
import random
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode

import httpx


class Blocked(Exception):
    """The site keeps refusing us; stop for this run."""


class OutOfBudget(Exception):
    """The run used its request budget."""


@dataclass
class Pacer:
    """3-5 s between requests, a hard cap per run, exponential backoff on 429 and 5xx, stop after repeated blocks."""
    max_requests: int = 30
    min_delay: float = 3.0
    max_delay: float = 5.0
    max_blocks: int = 3
    used: int = 0
    blocks: int = 0
    log: list[str] = field(default_factory=list)
    _last: float = 0.0

    def get(self, client: httpx.Client, url: str) -> httpx.Response:
        backoff = 8.0
        while True:
            if self.used >= self.max_requests:
                raise OutOfBudget()
            wait = random.uniform(self.min_delay, self.max_delay) - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self.used += 1
            self._last = time.monotonic()
            r = client.get(url)
            if r.status_code in (429, 999) or r.status_code >= 500:
                self.blocks += 1
                self.log.append(f"{r.status_code} on request {self.used}")
                if self.blocks >= self.max_blocks:
                    raise Blocked(f"stopped after {self.blocks} refusals ({r.status_code})")
                time.sleep(backoff)
                backoff *= 2
                continue
            self.blocks = 0
            return r


class _Cards(HTMLParser):
    """Job cards in LinkedIn's guest search HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.cards: list[dict[str, str]] = []
        self.field: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        cls = a.get("class") or ""
        urn = a.get("data-entity-urn") or ""
        if "jobPosting:" in urn:
            self.cards.append({"id": urn.rsplit(":", 1)[-1]})
        if not self.cards:
            return
        card = self.cards[-1]
        if "base-search-card__title" in cls:
            self.field = "title"
        elif "base-search-card__subtitle" in cls:
            self.field = "company"
        elif "job-search-card__location" in cls:
            self.field = "location"
        elif tag == "time" and a.get("datetime"):
            card["posted"] = a["datetime"] or ""
        elif tag == "a" and "base-card__full-link" in cls and a.get("href"):
            card["link"] = (a["href"] or "").split("?")[0]

    def handle_data(self, data: str) -> None:
        if self.field and self.cards and data.strip():
            card = self.cards[-1]
            card[self.field] = (card.get(self.field, "") + " " + data.strip()).strip()

    def handle_endtag(self, tag: str) -> None:
        if tag in ("h3", "h4", "span", "a"):
            self.field = None


_VOID = {"br", "img", "hr", "input", "meta", "link", "wbr", "source", "area", "col", "embed"}


class _Detail(HTMLParser):
    """The description and the criteria list (seniority, employment type, ...) of one posting."""

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.parts: list[str] = []
        self.criteria: dict[str, str] = {}
        self._key: str | None = None
        self._grab: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        cls = dict(attrs).get("class") or ""
        if "show-more-less-html__markup" in cls:
            self.depth = 1
        elif self.depth:
            if tag not in _VOID:  # <br>, <img> ... have no end tag, so they must not deepen the count
                self.depth += 1
            if tag in ("li", "p", "br", "div", "h2", "h3", "ul"):
                self.parts.append("\n")
            if tag == "li":
                self.parts.append("- ")
        if "description__job-criteria-subheader" in cls:
            self._grab = "key"
        elif "description__job-criteria-text" in cls:
            self._grab = "value"

    def handle_endtag(self, tag: str) -> None:
        if self.depth and tag not in _VOID:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.parts.append(data)
        elif self._grab == "key" and data.strip():
            self._key, self._grab = data.strip(), None
        elif self._grab == "value" and data.strip() and self._key:
            self.criteria[self._key] = data.strip()
            self._grab = self._key = None

    @property
    def text(self) -> str:
        text = html.unescape("".join(self.parts))
        return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", text)).strip()


class LinkedInGuest:
    """LinkedIn's public guest job pages. Filters: keywords, location, posting age, workplace type, job type."""

    name = "linkedin"
    SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
    AGE = {"day": "r86400", "week": "r604800", "month": "r2592000"}
    WORKPLACE = {"onsite": "1", "remote": "2", "hybrid": "3"}
    JOB_TYPE = {"internship": "I", "full_time": "F", "part_time": "P", "contract": "C", "temporary": "T"}

    def __init__(self, pacer: Pacer, client: httpx.Client | None = None) -> None:
        self.pacer = pacer
        self.client = client or httpx.Client(timeout=20, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/141.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"})

    def search_url(self, q: dict[str, Any], start: int = 0) -> str:
        params = {"keywords": q["keywords"], "location": q.get("location", "Germany"), "start": start}
        if q.get("hours"):  # a window in hours ("posted in the last 4 hours"); LinkedIn takes any number of seconds
            params["f_TPR"] = f"r{int(float(q['hours']) * 3600)}"
        elif q.get("age") in self.AGE:
            params["f_TPR"] = self.AGE[q["age"]]
        workplace = [self.WORKPLACE[w] for w in q.get("workplace", []) if w in self.WORKPLACE]
        if workplace:
            params["f_WT"] = ",".join(workplace)
        types = [self.JOB_TYPE[t] for t in q.get("job_types", []) if t in self.JOB_TYPE]
        if types:
            params["f_JT"] = ",".join(types)
        return f"{self.SEARCH}?{urlencode(params)}"

    def search(self, q: dict[str, Any], start: int = 0) -> list[dict[str, str]]:
        r = self.pacer.get(self.client, self.search_url(q, start))
        if r.status_code != 200:
            return []
        parser = _Cards()
        parser.feed(r.text)
        stubs = []
        for c in parser.cards:
            if c.get("id", "").isdigit():
                stubs.append({"id": f"li-{c['id']}", "source": self.name, "title": c.get("title", ""),
                              "company": c.get("company", ""), "location": c.get("location", ""),
                              "posted": c.get("posted", ""), "link": c.get("link") or f"https://www.linkedin.com/jobs/view/{c['id']}"})
        return stubs

    def detail(self, stub: dict[str, str]) -> dict[str, Any]:
        raw_id = stub["id"].removeprefix("li-")
        r = self.pacer.get(self.client, self.DETAIL.format(id=raw_id))
        if r.status_code != 200:
            return {**stub, "description": "", "criteria": {}}
        parser = _Detail()
        parser.feed(r.text)
        return {**stub, "description": parser.text, "criteria": parser.criteria}


SOURCES = {"linkedin": LinkedInGuest}
