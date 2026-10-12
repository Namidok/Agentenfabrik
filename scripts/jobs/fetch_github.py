"""Catalogue a GitHub user's public, non-fork repositories into data/jobs/projects_vN.json, one repo at a time.

One GitHub API call lists the repos (description, language, topics); the README and dependency files come
from raw.githubusercontent.com, which does not count against the 60-requests-per-hour API limit.
"outcomes" are only sentences quoted word for word from the README that state a result; nothing is invented.

Arguments (JSON): {"user": "Namidok", "max_repos": 40, "delay_s": 1.0}
Prints: {"ok", "file", "repos", "with_readme", "ids", ...}"""
from __future__ import annotations

import json
import re
import time

import httpx

from common import DATA, ME, args, clip, done, fail, next_version, rel, slug, today, write_json

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
HEADERS = {"User-Agent": "AgentFactory-job-search (personal use)", "Accept": "application/vnd.github+json"}
README_NAMES = ["README.md", "readme.md", "Readme.md", "README.rst", "README.txt", "README"]
DEP_FILES = ["requirements.txt", "pyproject.toml", "package.json", "Package.swift"]
# Dependency or keyword -> how it reads on a CV
KNOWN = {
    "fastapi": "FastAPI", "flask": "Flask", "django": "Django", "pandas": "Pandas", "numpy": "NumPy", "torch": "PyTorch",
    "pytorch": "PyTorch", "tensorflow": "TensorFlow", "scikit-learn": "scikit-learn", "sklearn": "scikit-learn",
    "langgraph": "LangGraph", "langchain": "LangChain", "ollama": "Ollama", "openai": "OpenAI API", "anthropic": "Claude API",
    "pytest": "pytest", "streamlit": "Streamlit", "apache spark": "Spark", "pyspark": "Spark", "kafka": "Kafka", "airflow": "Airflow",
    "docker": "Docker", "sqlalchemy": "SQLAlchemy", "postgres": "PostgreSQL", "sqlite": "SQLite", "react.js": "React", "reactjs": "React",
    "next.js": "Next.js", "nextjs": "Next.js", "typescript": "TypeScript", "playwright": "Playwright", "selenium": "Selenium", "beautifulsoup4": "BeautifulSoup",
    "httpx": "httpx", "faiss": "FAISS", "chromadb": "ChromaDB", "llama.cpp": "llama.cpp",
    "tree-sitter": "tree-sitter", "spacy": "spaCy", "transformers": "Hugging Face Transformers", "opencv": "OpenCV",
    "matplotlib": "Matplotlib", "plotly": "Plotly", "dbt": "dbt", "aws": "AWS", "github actions": "GitHub Actions",
}
# Ordinary English words: only counted when they are a real dependency, never from README prose.
DEPS_ONLY = {"requests": "requests", "next": "Next.js", "react": "React", "spark": "Spark", "flask": "Flask"}
OUTCOME = re.compile(r"\d[\d,.]*\s*(?:[a-z-]+\s+){0,2}(%|x\b|ms\b|s\b|seconds|minutes|hours|tests?\b|users|runs|repos|files|languages|"
                     r"requests|models|agents|documents|rows|records|accuracy|f1|faster|smaller|fewer|less)", re.I)


def get(client: httpx.Client, url: str, delay: float, tries: int = 4) -> httpx.Response | None:
    """GET with polite pacing; slows down on rate limits (403/429) and server errors."""
    wait = delay
    for _ in range(tries):
        time.sleep(wait)
        r = client.get(url)
        if r.status_code in (403, 429) and r.headers.get("x-ratelimit-remaining") == "0":
            reset = int(r.headers.get("x-ratelimit-reset", "0")) - int(time.time())
            if reset > 120:
                fail(f"GitHub's hourly API limit is used up; try again in {reset // 60} minutes.")
            wait = max(reset, 5)
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            wait = min(wait * 2 + 1, 30)
            continue
        return r
    return None


def clean_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)       # images and badges
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)    # links keep their words
    text = re.sub(r"^\s{0,3}#+\s*", "", text, flags=re.M)    # headings
    text = re.sub(r"[*_`>|]", " ", text)
    return re.sub(r"[ \t]+", " ", text)


def paragraphs(text: str) -> list[str]:
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    return [p for p in paras if len(p) > 40 and not p.lower().startswith(("license", "installation", "install", "usage"))]


def outcomes(text: str) -> list[str]:
    found = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n", re.sub(r"[ \t]+", " ", text)):
        s = sentence.strip(" -•")
        words = s.split()
        prose = sum(w.isalpha() for w in words) >= max(5, len(words) * 0.6)  # a sentence, not a table row or command
        if 20 < len(s) < 220 and OUTCOME.search(s) and prose:
            found.append(s)
    return found[:6]


def stack_of(repo: dict, readme: str, deps: str) -> list[str]:
    seen: list[str] = []
    for item in [repo.get("language")] + list(repo.get("topics") or []):
        if item and item not in seen:
            seen.append(item)
    hay = f"{readme}\n{deps}".lower()
    for key, name in KNOWN.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", hay) and name not in seen:
            seen.append(name)
    dep_names = {re.split(r"[<>=~!\[; ]", line.strip().strip('",'))[0].lower() for line in deps.splitlines()}
    for key, name in DEPS_ONLY.items():
        if key in dep_names and name not in seen:
            seen.append(name)
    return seen[:14]


def main() -> None:
    a = args()
    user = str(a.get("user", "")).strip().removeprefix("https://github.com/").strip("/")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", user):
        fail("Give a GitHub username, for example {\"user\": \"Namidok\"}.")
    delay = float(a.get("delay_s", 1.0))
    with httpx.Client(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        r = get(client, f"{API}/users/{user}/repos?per_page=100&type=owner&sort=pushed", 0)
        if r is None or r.status_code != 200:
            fail(f"Could not list the repositories of {user} (GitHub answered {getattr(r, 'status_code', 'nothing')}).")
        repos = [x for x in r.json() if not x.get("fork")][: int(a.get("max_repos", 40))]
        projects, with_readme = [], 0
        for repo in repos:
            name, branch = repo["name"], repo.get("default_branch") or "main"
            readme = ""
            for fname in README_NAMES:
                res = get(client, f"{RAW}/{user}/{name}/{branch}/{fname}", delay)
                if res is not None and res.status_code == 200 and res.text.strip():
                    readme = clip(res.text)  # at most about 3000 characters per README
                    break
            deps = ""
            for fname in DEP_FILES:
                res = get(client, f"{RAW}/{user}/{name}/{branch}/{fname}", delay / 2)
                if res is not None and res.status_code == 200:
                    deps += res.text[:3000] + "\n"
            with_readme += bool(readme)
            text = clean_markdown(readme)
            paras = paragraphs(text)
            projects.append({
                "id": f"PRJ-{slug(name, 30)}", "name": name,
                "summary": clip(repo.get("description") or (paras[0] if paras else ""), 300),
                "stack": stack_of(repo, readme, deps),
                "what_was_built": clip(" ".join(paras[:2]), 700),
                "outcomes": outcomes(text),  # quoted from the README; empty when it states none
                "link": f"github.com/{user}/{name}",
                "tags": [t for t in [repo.get("language")] + list(repo.get("topics") or []) if t],
                "updated": (repo.get("pushed_at") or "")[:10], "stars": repo.get("stargazers_count", 0),
                "has_readme": bool(readme),
            })
    path = write_json(next_version(ME, "projects"), {"version": 1, "user": user, "fetched": today(), "projects": projects})
    done({"ok": True, "file": rel(path), "repos": len(projects), "with_readme": with_readme,
          "without_readme": [p["name"] for p in projects if not p["has_readme"]][:15],
          "ids": [p["id"] for p in projects][:40]})


if __name__ == "__main__":
    main()
