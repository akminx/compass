# Compass Phase 0.A — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the three ATS scrapers (Greenhouse, Lever, Ashby), the vault reader and writer, and two smoke-test scripts — so that scraping and vault I/O work independently of any LLM call. No pipeline nodes, no scoring, no Modal in this phase.

**Architecture:** Each scraper is a thin async function wrapping a single public ATS endpoint, returning `list[RawJob]`. The vault reader/writer use `python-frontmatter` for YAML+markdown round-tripping and validate every write against the Pydantic schemas already defined in `compass/vault/schemas.py`. Smoke tests are plain Python scripts (not pytest) — they hit real APIs and the real vault to prove the foundation is alive.

**Tech Stack:** Python 3.12 · uv · httpx (async) · python-frontmatter · pydantic v2 · pytest + pytest-asyncio + pytest-httpx (TDD). No LLM dependencies in this phase.

**Authoritative spec:** `docs/superpowers/specs/2026-05-17-compass-mvp-to-portfolio-ship-design.md`

---

## File Structure

### New
- `tests/__init__.py`
- `tests/conftest.py` (shared fixtures: temp vault dir)
- `tests/scrapers/__init__.py`
- `tests/scrapers/test_greenhouse.py`
- `tests/scrapers/test_lever.py`
- `tests/scrapers/test_ashby.py`
- `tests/vault/__init__.py`
- `tests/vault/test_reader.py`
- `tests/vault/test_writer.py`
- `scripts/test_scrape.py` (live-API smoke)
- `scripts/test_vault_roundtrip.py` (vault I/O smoke)

### Modify (replace `NotImplementedError`)
- `compass/scrapers/greenhouse.py`
- `compass/scrapers/lever.py`
- `compass/scrapers/ashby.py`
- `compass/vault/reader.py`
- `compass/vault/writer.py`
- `compass/config.py` (add model env vars)
- `.env.example` (add new keys)

### Untouched (existing — do not modify in this phase)
- `compass/vault/{taxonomy,learning_bridge,schemas}.py`
- `compass/analysis/{gap_aggregator,skill_assessor}.py`
- `compass/mcp_server/server.py`
- `compass/pipeline/*` (nodes + graph — Phase 0.B)

### Decomposition rationale
Each scraper file is one responsibility (one ATS, one endpoint). `vault/reader.py` and `vault/writer.py` stay split — reads and writes have different validation needs and different test surfaces. The smoke scripts live under `scripts/` (separate from `tests/`) because they hit live external services and aren't safe to run in CI.

---

## Task 0: Pre-flight

**Files:** none

- [ ] **Step 1: Verify uv environment**

Run: `cd ~/Documents/compass && uv sync`
Expected: completes without errors, all dev deps installed.

- [ ] **Step 2: Verify git is clean before starting**

Run: `git status`
Expected: working tree clean (or only the recently-added vault/code files we already wrote — commit them as a baseline if not yet).

If uncommitted work exists from earlier sessions, commit it first:
```bash
git add -A && git commit -m "chore: baseline before Phase 0.A foundation work"
```

- [ ] **Step 3: Verify pytest runs (will collect zero tests since we haven't written any)**

Run: `uv run pytest -q`
Expected: `no tests ran` (or similar) with exit code 5. Confirms the toolchain works.

- [ ] **Step 4: Create the tests/ scaffold**

```bash
mkdir -p tests/scrapers tests/vault
touch tests/__init__.py tests/scrapers/__init__.py tests/vault/__init__.py
```

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "chore: add tests/ scaffold for Phase 0.A"
```

---

## Task 1: Extend config + .env.example

**Files:**
- Modify: `compass/config.py`
- Modify: `.env.example`

These are foundational — every later module reads from `compass.config`. Doing this first means scrapers and tests can import model names if needed (though Phase 0.A doesn't use LLMs).

- [ ] **Step 1: Add per-node model env vars to `compass/config.py`**

Append these lines after the existing `ASSESSOR_MODEL` line in `compass/config.py`:

```python
# ── Per-node model routing (OpenRouter model IDs) ────────────────────────────
EXTRACT_MODEL: str = os.getenv("EXTRACT_MODEL", "google/gemini-2.5-flash")
SCORE_MODEL: str = os.getenv("SCORE_MODEL", "google/gemini-2.5-flash")
REFLECT_MODEL: str = os.getenv("REFLECT_MODEL", "anthropic/claude-sonnet-4.6")
TAILOR_MODEL: str = os.getenv("TAILOR_MODEL", "anthropic/claude-sonnet-4.6")
# ASSESSOR_MODEL already defined above; defaults to anthropic/claude-sonnet-4.6.
```

Also change the existing `ASSESSOR_MODEL` default from `COMPASS_MODEL` to `"anthropic/claude-sonnet-4.6"` so it doesn't accidentally inherit a Gemini default.

- [ ] **Step 2: Update `.env.example`**

Replace the file with:

```env
# ── LLM ──────────────────────────────────────────────────────────────────────
OPENROUTER_API_KEY=sk-or-v1-...
# Per-node model routing — leave defaults unless you have a specific reason
EXTRACT_MODEL=google/gemini-2.5-flash
SCORE_MODEL=google/gemini-2.5-flash
REFLECT_MODEL=anthropic/claude-sonnet-4.6
TAILOR_MODEL=anthropic/claude-sonnet-4.6
ASSESSOR_MODEL=anthropic/claude-sonnet-4.6
COMPASS_MODEL=anthropic/claude-sonnet-4.6  # legacy fallback

# ── Langfuse (self-hosted) ───────────────────────────────────────────────────
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...

# ── Vaults ───────────────────────────────────────────────────────────────────
VAULT_PATH=/Users/<user>/Documents/compass-vault
LEARNING_VAULT_PATH=/Users/<user>/Documents/learning-vault

# ── RAG ──────────────────────────────────────────────────────────────────────
CHROMA_PATH=~/.compass/chroma
EMBEDDING_MODEL=all-MiniLM-L6-v2

# ── HiTL ─────────────────────────────────────────────────────────────────────
HITL_STATE_DB=~/.compass/hitl.db
HITL_TIMEOUT_HOURS=4

# ── Pipeline ─────────────────────────────────────────────────────────────────
MAX_JOBS_PER_RUN=50
SCORE_THRESHOLD=3.5
MAX_CONCURRENT_JOBS=5

# ── ATS targets (tier `apply-now` from compass-vault/_profile/target-companies.md) ──
# Comma-separated. Slugs verified May 2026.
GREENHOUSE_BOARDS=anthropic,hebbia,gleanwork,cresta,andurilindustries,vannevarlabs,cadencehealth,vercel
LEVER_COMPANIES=shieldai
ASHBY_BOARDS=sierra,decagon,cognition,ramp,traversal,vapi,retell-ai,wispr-flow,browserbase,openai,cursor,harvey,perplexity
```

- [ ] **Step 3: Verify config imports cleanly**

Run: `cd ~/Documents/compass && VAULT_PATH=~/Documents/compass-vault OPENROUTER_API_KEY=stub uv run python -c "from compass.config import EXTRACT_MODEL, SCORE_MODEL, GREENHOUSE_BOARDS; print(EXTRACT_MODEL); print(len(GREENHOUSE_BOARDS), 'GH boards')"`
Expected: `google/gemini-2.5-flash` and `8 GH boards`.

- [ ] **Step 4: Commit**

```bash
git add compass/config.py .env.example
git commit -m "feat(config): add per-node model env vars + tier-apply-now ATS slugs"
```

---

## Task 2: Greenhouse scraper

**Files:**
- Modify: `compass/scrapers/greenhouse.py`
- Create: `tests/scrapers/test_greenhouse.py`

API contract: `GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs` returns `{"jobs": [{"id": int, "title": str, "absolute_url": str, "location": {"name": str}, "updated_at": str ISO, "content": str HTML, ...}], "meta": {...}}`.

- [ ] **Step 1: Write the failing test**

Write `tests/scrapers/test_greenhouse.py`:

```python
"""Tests for compass.scrapers.greenhouse."""
import pytest
from compass.scrapers.greenhouse import scrape_greenhouse, GREENHOUSE_BASE

SAMPLE_RESPONSE = {
    "jobs": [
        {
            "id": 1234567,
            "title": "Senior Agent Engineer",
            "absolute_url": "https://job-boards.greenhouse.io/sample/jobs/1234567",
            "location": {"name": "San Francisco, CA"},
            "updated_at": "2026-05-15T10:00:00-07:00",
            "content": "<p>Build AI agents</p><p>Required: Python, LangGraph</p>",
        },
        {
            "id": 7654321,
            "title": "Agent Engineer",
            "absolute_url": "https://job-boards.greenhouse.io/sample/jobs/7654321",
            "location": {"name": "Remote"},
            "updated_at": "2026-05-10T09:00:00-07:00",
            "content": "<p>Junior role</p>",
        },
    ],
    "meta": {"total": 2},
}


async def test_scrape_greenhouse_returns_rawjob_list(httpx_mock):
    httpx_mock.add_response(
        url=f"{GREENHOUSE_BASE}/sample/jobs",
        json=SAMPLE_RESPONSE,
    )
    jobs = await scrape_greenhouse("sample")
    assert len(jobs) == 2
    first = jobs[0]
    assert first.company == "sample"
    assert first.title == "Senior Agent Engineer"
    assert first.url == "https://job-boards.greenhouse.io/sample/jobs/1234567"
    assert first.source == "greenhouse"
    assert first.location == "San Francisco, CA"
    assert "LangGraph" in first.description  # HTML stripped to plain text
    assert first.date_posted is not None


async def test_scrape_greenhouse_handles_missing_location(httpx_mock):
    httpx_mock.add_response(
        url=f"{GREENHOUSE_BASE}/sample/jobs",
        json={"jobs": [{
            "id": 1,
            "title": "X",
            "absolute_url": "https://example.com/x",
            "location": None,
            "updated_at": "2026-05-15T10:00:00-07:00",
            "content": "<p>y</p>",
        }]},
    )
    jobs = await scrape_greenhouse("sample")
    assert jobs[0].location is None


async def test_scrape_greenhouse_empty_board(httpx_mock):
    httpx_mock.add_response(
        url=f"{GREENHOUSE_BASE}/sample/jobs",
        json={"jobs": []},
    )
    jobs = await scrape_greenhouse("sample")
    assert jobs == []


async def test_scrape_greenhouse_http_error_returns_empty(httpx_mock):
    """A 404 board should log and return [], not raise — pipeline must keep running."""
    httpx_mock.add_response(
        url=f"{GREENHOUSE_BASE}/nonexistent/jobs",
        status_code=404,
    )
    jobs = await scrape_greenhouse("nonexistent")
    assert jobs == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scrapers/test_greenhouse.py -v`
Expected: 4 FAILs with `NotImplementedError: scrape_greenhouse not yet implemented`.

- [ ] **Step 3: Implement `scrape_greenhouse`**

Replace `compass/scrapers/greenhouse.py` with:

```python
"""
Greenhouse public API scraper.

Endpoint: GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs
No authentication required.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import date, datetime

import httpx

from compass.pipeline.state import RawJob

logger = logging.getLogger(__name__)

GREENHOUSE_BASE = "https://boards-api.greenhouse.io/v1/boards"
_REQUEST_TIMEOUT = 20.0
# Update the URL if/when the repo moves; current placeholder is the planned public URL.
_USER_AGENT = "compass-job-scraper/0.1"


def _strip_html(raw: str) -> str:
    """Cheap HTML-to-text. Good enough for JD bodies; we don't need perfect fidelity."""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _to_rawjob(board_token: str, raw: dict) -> RawJob | None:
    try:
        return RawJob(
            company=board_token,
            title=raw["title"],
            url=raw["absolute_url"],
            source="greenhouse",
            location=(raw.get("location") or {}).get("name") if raw.get("location") else None,
            remote=None,
            salary_min=None,
            salary_max=None,
            description=_strip_html(raw.get("content", "")),
            date_posted=_parse_date(raw.get("updated_at")),
        )
    except (KeyError, TypeError) as e:
        logger.warning("greenhouse: malformed job entry skipped: %s", e)
        return None


async def scrape_greenhouse(board_token: str) -> list[RawJob]:
    """Scrape all open jobs from a Greenhouse board.

    Returns [] on any HTTP error — never raises. Pipeline must keep running
    when one ATS source is unavailable.
    """
    url = f"{GREENHOUSE_BASE}/{board_token}/jobs"
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("greenhouse %s: %s", board_token, e)
        return []
    jobs = [j for j in (_to_rawjob(board_token, raw) for raw in data.get("jobs", [])) if j is not None]
    return jobs


async def scrape_greenhouse_many(board_tokens: list[str]) -> list[RawJob]:
    """Scrape multiple Greenhouse boards concurrently."""
    if not board_tokens:
        return []
    results = await asyncio.gather(*[scrape_greenhouse(t) for t in board_tokens], return_exceptions=True)
    out: list[RawJob] = []
    for r in results:
        if isinstance(r, list):
            out.extend(r)
        else:
            logger.warning("greenhouse_many: unexpected exception: %s", r)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/scrapers/test_greenhouse.py -v`
Expected: 4 PASSES.

- [ ] **Step 5: Commit**

```bash
git add compass/scrapers/greenhouse.py tests/scrapers/test_greenhouse.py
git commit -m "feat(scrapers): implement Greenhouse scraper with HTTP error tolerance"
```

---

## Task 3: Lever scraper

**Files:**
- Modify: `compass/scrapers/lever.py`
- Create: `tests/scrapers/test_lever.py`

API contract: `GET https://api.lever.co/v0/postings/{company}?mode=json` returns a JSON array of postings, each `{"id": str, "text": str title, "hostedUrl": str, "categories": {"location": str, "commitment": str, "team": str}, "createdAt": int ms, "descriptionPlain": str, ...}`.

- [ ] **Step 1: Write the failing test**

Write `tests/scrapers/test_lever.py`:

```python
"""Tests for compass.scrapers.lever."""
import pytest
from compass.scrapers.lever import scrape_lever, LEVER_BASE

SAMPLE_RESPONSE = [
    {
        "id": "abc-123",
        "text": "Software Engineer, AI",
        "hostedUrl": "https://jobs.lever.co/sample/abc-123",
        "categories": {"location": "Remote", "commitment": "Full-time", "team": "Engineering"},
        "createdAt": 1715600000000,
        "descriptionPlain": "Build agentic systems with Python and LangGraph.",
    },
    {
        "id": "def-456",
        "text": "ML Engineer",
        "hostedUrl": "https://jobs.lever.co/sample/def-456",
        "categories": {"location": "SF, CA", "commitment": "Full-time", "team": "Research"},
        "createdAt": 1715500000000,
        "descriptionPlain": "Train models.",
    },
]


async def test_scrape_lever_returns_rawjob_list(httpx_mock):
    httpx_mock.add_response(
        url=f"{LEVER_BASE}/sample?mode=json",
        json=SAMPLE_RESPONSE,
    )
    jobs = await scrape_lever("sample")
    assert len(jobs) == 2
    first = jobs[0]
    assert first.company == "sample"
    assert first.title == "Software Engineer, AI"
    assert first.url == "https://jobs.lever.co/sample/abc-123"
    assert first.source == "lever"
    assert first.location == "Remote"
    assert "LangGraph" in first.description
    assert first.date_posted is not None


async def test_scrape_lever_handles_missing_categories(httpx_mock):
    httpx_mock.add_response(
        url=f"{LEVER_BASE}/sample?mode=json",
        json=[{
            "id": "x",
            "text": "Y",
            "hostedUrl": "https://example.com/x",
            "categories": {},
            "createdAt": 1715600000000,
            "descriptionPlain": "z",
        }],
    )
    jobs = await scrape_lever("sample")
    assert jobs[0].location is None


async def test_scrape_lever_http_error_returns_empty(httpx_mock):
    httpx_mock.add_response(
        url=f"{LEVER_BASE}/nonexistent?mode=json",
        status_code=404,
    )
    jobs = await scrape_lever("nonexistent")
    assert jobs == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scrapers/test_lever.py -v`
Expected: 3 FAILs.

- [ ] **Step 3: Implement `scrape_lever`**

Replace `compass/scrapers/lever.py` with:

```python
"""
Lever public API scraper.

Endpoint: GET https://api.lever.co/v0/postings/{company}?mode=json
No authentication required.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime

import httpx

from compass.pipeline.state import RawJob

logger = logging.getLogger(__name__)

LEVER_BASE = "https://api.lever.co/v0/postings"
_REQUEST_TIMEOUT = 20.0
_USER_AGENT = "compass-job-scraper/0.1"


def _ms_to_date(ms: int | None) -> date | None:
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000).date()
    except (TypeError, ValueError, OSError):
        return None


def _to_rawjob(company: str, raw: dict) -> RawJob | None:
    try:
        categories = raw.get("categories") or {}
        return RawJob(
            company=company,
            title=raw["text"],
            url=raw["hostedUrl"],
            source="lever",
            location=categories.get("location") or None,
            remote=None,
            salary_min=None,
            salary_max=None,
            description=raw.get("descriptionPlain", ""),
            date_posted=_ms_to_date(raw.get("createdAt")),
        )
    except (KeyError, TypeError) as e:
        logger.warning("lever: malformed posting skipped: %s", e)
        return None


async def scrape_lever(company: str) -> list[RawJob]:
    """Scrape all open postings from a Lever company."""
    url = f"{LEVER_BASE}/{company}?mode=json"
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("lever %s: %s", company, e)
        return []
    if not isinstance(data, list):
        logger.warning("lever %s: unexpected payload type %s", company, type(data).__name__)
        return []
    return [j for j in (_to_rawjob(company, raw) for raw in data) if j is not None]


async def scrape_lever_many(companies: list[str]) -> list[RawJob]:
    if not companies:
        return []
    results = await asyncio.gather(*[scrape_lever(c) for c in companies], return_exceptions=True)
    out: list[RawJob] = []
    for r in results:
        if isinstance(r, list):
            out.extend(r)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/scrapers/test_lever.py -v`
Expected: 3 PASSES.

- [ ] **Step 5: Commit**

```bash
git add compass/scrapers/lever.py tests/scrapers/test_lever.py
git commit -m "feat(scrapers): implement Lever scraper"
```

---

## Task 4: Ashby scraper

**Files:**
- Modify: `compass/scrapers/ashby.py`
- Create: `tests/scrapers/test_ashby.py`

API contract: `GET https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true` returns `{"jobs": [{"id": str, "title": str, "jobUrl": str, "locationName": str, "publishedAt": str ISO, "descriptionPlain": str, "compensation": {"compensationTierSummary": str optional}, "employmentType": str, "shouldDisplayCompensationOnJobBoard": bool, ...}], ...}`.

- [ ] **Step 1: Write the failing test**

Write `tests/scrapers/test_ashby.py`:

```python
"""Tests for compass.scrapers.ashby."""
import pytest
from compass.scrapers.ashby import scrape_ashby, ASHBY_BASE

SAMPLE_RESPONSE = {
    "jobs": [
        {
            "id": "uuid-aaa",
            "title": "Agent Engineer",
            "jobUrl": "https://jobs.ashbyhq.com/sample/uuid-aaa",
            "locationName": "New York, NY",
            "publishedAt": "2026-05-12T15:00:00.000Z",
            "descriptionPlain": "Build customer agents with LangGraph, Python, and MCP.",
            "compensation": {"compensationTierSummary": "$180K – $230K"},
            "employmentType": "FullTime",
            "shouldDisplayCompensationOnJobBoard": True,
        },
        {
            "id": "uuid-bbb",
            "title": "Senior Agent Engineer",
            "jobUrl": "https://jobs.ashbyhq.com/sample/uuid-bbb",
            "locationName": "Remote",
            "publishedAt": "2026-05-10T15:00:00.000Z",
            "descriptionPlain": "Senior role.",
            "compensation": None,
            "employmentType": "FullTime",
            "shouldDisplayCompensationOnJobBoard": False,
        },
    ],
}


async def test_scrape_ashby_returns_rawjob_list(httpx_mock):
    httpx_mock.add_response(
        url=f"{ASHBY_BASE}/sample?includeCompensation=true",
        json=SAMPLE_RESPONSE,
    )
    jobs = await scrape_ashby("sample")
    assert len(jobs) == 2
    first = jobs[0]
    assert first.company == "sample"
    assert first.title == "Agent Engineer"
    assert first.url == "https://jobs.ashbyhq.com/sample/uuid-aaa"
    assert first.source == "ashby"
    assert first.location == "New York, NY"
    assert "LangGraph" in first.description
    assert first.date_posted is not None


async def test_scrape_ashby_parses_compensation_range(httpx_mock):
    httpx_mock.add_response(
        url=f"{ASHBY_BASE}/sample?includeCompensation=true",
        json=SAMPLE_RESPONSE,
    )
    jobs = await scrape_ashby("sample")
    assert jobs[0].salary_min == 180000
    assert jobs[0].salary_max == 230000
    # Second job has compensation=None → salary fields should be None.
    assert jobs[1].salary_min is None
    assert jobs[1].salary_max is None


async def test_scrape_ashby_http_error_returns_empty(httpx_mock):
    httpx_mock.add_response(
        url=f"{ASHBY_BASE}/nonexistent?includeCompensation=true",
        status_code=404,
    )
    jobs = await scrape_ashby("nonexistent")
    assert jobs == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scrapers/test_ashby.py -v`
Expected: 3 FAILs.

- [ ] **Step 3: Implement `scrape_ashby`**

Replace `compass/scrapers/ashby.py` with:

```python
"""
Ashby public API scraper.

Endpoint: GET https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true
No authentication required. Covers Sierra, Decagon, Cognition, Ramp, OpenAI, Cursor, and many more.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime

import httpx

from compass.pipeline.state import RawJob

logger = logging.getLogger(__name__)

ASHBY_BASE = "https://api.ashbyhq.com/posting-api/job-board"
_REQUEST_TIMEOUT = 20.0
_USER_AGENT = "compass-job-scraper/0.1"

# Parses compensation summaries like "$180K – $230K", "$120,000 - $160,000", "$200K+"
_COMP_RANGE_RE = re.compile(
    r"\$([\d,]+)(?:[Kk])?\s*[–\-—to]+\s*\$?([\d,]+)(?:[Kk])?",
)
_COMP_SINGLE_RE = re.compile(r"\$([\d,]+)(?:[Kk])?")


def _parse_money(token: str, is_k: bool) -> int | None:
    try:
        n = int(token.replace(",", ""))
    except ValueError:
        return None
    return n * 1000 if is_k else n


def _parse_compensation(summary: str | None) -> tuple[int | None, int | None]:
    if not summary:
        return None, None
    m = _COMP_RANGE_RE.search(summary)
    if m:
        low_k = "k" in summary[m.start(1):m.end(1) + 1].lower() or "K" in summary
        high_k = "K" in summary[m.start(2):]
        # Simpler approach: assume both share K-ness based on whether 'K' appears in the summary.
        is_k = "K" in summary or "k" in summary
        return _parse_money(m.group(1), is_k), _parse_money(m.group(2), is_k)
    return None, None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        # Strip trailing 'Z' for fromisoformat compatibility on older Python
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _to_rawjob(slug: str, raw: dict) -> RawJob | None:
    try:
        comp = (raw.get("compensation") or {}).get("compensationTierSummary") if raw.get("shouldDisplayCompensationOnJobBoard") else None
        salary_min, salary_max = _parse_compensation(comp)
        return RawJob(
            company=slug,
            title=raw["title"],
            url=raw["jobUrl"],
            source="ashby",
            location=raw.get("locationName") or None,
            remote=None,
            salary_min=salary_min,
            salary_max=salary_max,
            description=raw.get("descriptionPlain", ""),
            date_posted=_parse_date(raw.get("publishedAt")),
        )
    except (KeyError, TypeError) as e:
        logger.warning("ashby: malformed job skipped: %s", e)
        return None


async def scrape_ashby(slug: str) -> list[RawJob]:
    url = f"{ASHBY_BASE}/{slug}?includeCompensation=true"
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("ashby %s: %s", slug, e)
        return []
    return [j for j in (_to_rawjob(slug, raw) for raw in data.get("jobs", [])) if j is not None]


async def scrape_ashby_many(slugs: list[str]) -> list[RawJob]:
    if not slugs:
        return []
    results = await asyncio.gather(*[scrape_ashby(s) for s in slugs], return_exceptions=True)
    out: list[RawJob] = []
    for r in results:
        if isinstance(r, list):
            out.extend(r)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/scrapers/test_ashby.py -v`
Expected: 3 PASSES.

- [ ] **Step 5: Commit**

```bash
git add compass/scrapers/ashby.py tests/scrapers/test_ashby.py
git commit -m "feat(scrapers): implement Ashby scraper with compensation parsing"
```

---

## Task 5: Vault reader

**Files:**
- Modify: `compass/vault/reader.py`
- Create: `tests/conftest.py` (shared fixture: `temp_vault`)
- Create: `tests/vault/test_reader.py`

The reader has five functions: `read_profile_section`, `read_skill_inventory`, `read_resume`, `job_url_exists`, `list_job_notes`. All operate against `VAULT_PATH` from config — tests use a monkey-patched temp dir.

- [ ] **Step 1: Write `tests/conftest.py` with the `temp_vault` fixture**

```python
"""Shared pytest fixtures.

NOTE on env vars: `compass.config` reads `OPENROUTER_API_KEY` and `VAULT_PATH`
via `os.environ[...]` at import time — that raises KeyError on missing values.
We set sane defaults BEFORE any `compass.*` import so `uv run pytest` works
without requiring the executor to export envs on every invocation.
"""
import os

# MUST happen before any compass import below.
os.environ.setdefault("OPENROUTER_API_KEY", "test-stub")
os.environ.setdefault("VAULT_PATH", "/tmp/compass-vault-pytest-placeholder")
os.environ.setdefault("LEARNING_VAULT_PATH", "/tmp/learning-vault-pytest-placeholder")

from pathlib import Path

import pytest


@pytest.fixture
def temp_vault(tmp_path: Path, monkeypatch):
    """Create a minimal compass-vault structure in a tmp dir and point config at it."""
    vault = tmp_path / "compass-vault"
    for sub in ["_profile", "_meta", "jobs", "skills", "companies", "applications", "study-plans"]:
        (vault / sub).mkdir(parents=True, exist_ok=True)
    # Seed minimal _profile files so reader tests can find them.
    (vault / "_profile" / "resume.md").write_text("---\ntype: profile\n---\n# Resume\n\nFake resume body.\n")
    (vault / "_profile" / "skill-inventory.md").write_text("---\ntype: profile\n---\n# Skills\n\nPython: 3\n")
    (vault / "_profile" / "preferences.md").write_text("---\ntype: profile\n---\nPreferences body.\n")
    (vault / "_meta" / "agent-log.md").write_text("# Agent Log\n")

    # Patch the config module's attributes.
    import compass.config as cfg
    monkeypatch.setattr(cfg, "VAULT_PATH", vault)
    monkeypatch.setattr(cfg, "AGENT_LOG_PATH", vault / "_meta" / "agent-log.md")
    monkeypatch.setattr(cfg, "SKILL_INVENTORY_PATH", vault / "_profile" / "skill-inventory.md")
    monkeypatch.setattr(cfg, "MASTER_GAP_PLAN_PATH", vault / "study-plans" / "master-gap-plan.md")

    # Also patch the modules that captured these via `from compass.config import VAULT_PATH`.
    # Guarded with hasattr because Task 5 runs BEFORE Task 6 implements the writer's
    # AGENT_LOG_PATH import — reader tests in Task 5 don't touch the writer module's
    # AGENT_LOG_PATH so the guard keeps that test wave green.
    import compass.vault.reader as reader_mod
    if hasattr(reader_mod, "VAULT_PATH"):
        monkeypatch.setattr(reader_mod, "VAULT_PATH", vault)

    import compass.vault.writer as writer_mod
    if hasattr(writer_mod, "VAULT_PATH"):
        monkeypatch.setattr(writer_mod, "VAULT_PATH", vault)
    if hasattr(writer_mod, "AGENT_LOG_PATH"):
        monkeypatch.setattr(writer_mod, "AGENT_LOG_PATH", vault / "_meta" / "agent-log.md")

    return vault
```

> **Note on the `hasattr` guards:** by the time Task 6 (writer) is implemented and its tests run, both attributes WILL exist and the patches WILL apply. The guards only matter during Task 5 (reader) tests where the writer module is still a stub without `AGENT_LOG_PATH`. If you're tempted to remove the guards: don't — they let reader tests pass cleanly regardless of writer-implementation state.

- [ ] **Step 2: Write the failing reader tests**

Write `tests/vault/test_reader.py`:

```python
"""Tests for compass.vault.reader."""
from datetime import date


def test_read_profile_section_returns_content(temp_vault):
    from compass.vault.reader import read_profile_section
    content = read_profile_section("resume")
    assert "Fake resume body" in content


def test_read_profile_section_missing_returns_empty_string(temp_vault):
    from compass.vault.reader import read_profile_section
    assert read_profile_section("nonexistent") == ""


def test_read_skill_inventory(temp_vault):
    from compass.vault.reader import read_skill_inventory
    content = read_skill_inventory()
    assert "Python: 3" in content


def test_read_resume(temp_vault):
    from compass.vault.reader import read_resume
    assert "Fake resume body" in read_resume()


def test_job_url_exists_false_when_no_jobs(temp_vault):
    from compass.vault.reader import job_url_exists
    assert job_url_exists("https://example.com/jobs/123") is False


def test_job_url_exists_true_when_present(temp_vault):
    from compass.vault.reader import job_url_exists
    # Manually create a job note with a known URL
    (temp_vault / "jobs" / "2026-05-15-Sample-Title.md").write_text(
        "---\ntype: job\nurl: https://example.com/jobs/123\ncompany: Sample\ntitle: Title\nmatch_score: 0\nsource: greenhouse\ndate_found: 2026-05-15\n---\n# Sample\n"
    )
    assert job_url_exists("https://example.com/jobs/123") is True
    assert job_url_exists("https://example.com/jobs/456") is False


def test_list_job_notes_returns_all_files(temp_vault):
    from compass.vault.reader import list_job_notes
    assert list_job_notes() == []
    (temp_vault / "jobs" / "a.md").write_text("---\ntype: job\n---\n")
    (temp_vault / "jobs" / "b.md").write_text("---\ntype: job\n---\n")
    paths = list_job_notes()
    assert len(paths) == 2
    assert all(p.name in {"a.md", "b.md"} for p in paths)
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/vault/test_reader.py -v`
Expected: 7 FAILs with `NotImplementedError`.

- [ ] **Step 4: Implement the reader**

Replace `compass/vault/reader.py` with:

```python
"""
Vault reader — reads structured notes from the Obsidian vault.
"""
from __future__ import annotations

from pathlib import Path

import frontmatter

from compass.config import VAULT_PATH


def read_profile_section(section: str) -> str:
    """Read a file from _profile/. Returns empty string if missing."""
    path = VAULT_PATH / "_profile" / f"{section}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def read_skill_inventory() -> str:
    return read_profile_section("skill-inventory")


def read_resume() -> str:
    return read_profile_section("resume")


def job_url_exists(url: str) -> bool:
    """Check whether any job note in the vault has the given URL in its frontmatter."""
    jobs_dir = VAULT_PATH / "jobs"
    if not jobs_dir.exists():
        return False
    for path in jobs_dir.glob("*.md"):
        try:
            post = frontmatter.load(path)
        except Exception:
            continue
        if post.metadata.get("url") == url:
            return True
    return False


def list_job_notes() -> list[Path]:
    jobs_dir = VAULT_PATH / "jobs"
    if not jobs_dir.exists():
        return []
    return sorted(jobs_dir.glob("*.md"))
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/vault/test_reader.py -v`
Expected: 7 PASSES.

- [ ] **Step 6: Commit**

```bash
git add compass/vault/reader.py tests/vault/test_reader.py tests/conftest.py
git commit -m "feat(vault): implement reader for profile + dedup + listing"
```

---

## Task 6: Vault writer

**Files:**
- Modify: `compass/vault/writer.py`
- Create: `tests/vault/test_writer.py`

Four functions: `write_job_note(JobNote)`, `update_skill_note(canonical_skill, job_url)`, `write_company_note(CompanyNote)`, `append_agent_log(line)`. All use `python-frontmatter` for round-trip safety and validate against the schemas in `compass.vault.schemas`.

- [ ] **Step 1: Write the failing tests**

Write `tests/vault/test_writer.py`:

```python
"""Tests for compass.vault.writer."""
from datetime import date

import frontmatter
import pytest


def _make_job_note(**overrides):
    from compass.vault.schemas import JobNote
    defaults = dict(
        company="Sierra",
        title="Agent Engineer",
        url="https://jobs.ashbyhq.com/sierra/abc-123",
        source="ashby",
        date_found=date(2026, 5, 17),
        match_score=4.2,
        score_reasoning="Strong MCP match",
        location="New York, NY",
        skills_required=["MCP", "LangGraph"],
        skills_matched=["MCP"],
        skills_missing=["LangGraph"],
        jd_summary="Build agentic systems",
    )
    defaults.update(overrides)
    return JobNote(**defaults)


def test_write_job_note_creates_file(temp_vault):
    from compass.vault.writer import write_job_note
    note = _make_job_note()
    path = write_job_note(note)
    assert path.exists()
    assert path.parent == temp_vault / "jobs"
    # Filename pattern: YYYY-MM-DD-Company-Title.md
    assert path.name.startswith("2026-05-17-Sierra-")
    assert path.suffix == ".md"


def test_write_job_note_frontmatter_roundtrips(temp_vault):
    from compass.vault.writer import write_job_note
    note = _make_job_note()
    path = write_job_note(note)
    loaded = frontmatter.load(path)
    assert loaded.metadata["company"] == "Sierra"
    assert loaded.metadata["match_score"] == 4.2
    assert loaded.metadata["url"] == note.url
    assert "MCP" in loaded.metadata["skills_required"]


def test_write_job_note_sanitizes_filename(temp_vault):
    from compass.vault.writer import write_job_note
    note = _make_job_note(title="Senior Engineer / Slash & Special: Chars?")
    path = write_job_note(note)
    # No slashes, colons, question marks, or ampersands in filename.
    assert "/" not in path.name
    assert ":" not in path.name
    assert "?" not in path.name


def test_write_job_note_idempotent_on_duplicate_url(temp_vault):
    """Writing the same URL twice should overwrite the same file, not create a second."""
    from compass.vault.writer import write_job_note
    note = _make_job_note()
    p1 = write_job_note(note)
    p2 = write_job_note(_make_job_note(match_score=4.5))
    assert p1 == p2
    assert len(list((temp_vault / "jobs").glob("*.md"))) == 1
    loaded = frontmatter.load(p2)
    assert loaded.metadata["match_score"] == 4.5


def test_update_skill_note_increments_counter(temp_vault):
    from compass.vault.writer import update_skill_note
    # Seed an existing skill note like seed_skills.py would.
    skill_path = temp_vault / "skills" / "LangGraph.md"
    skill_path.write_text(
        "---\ntype: skill\nskill: LangGraph\ncategory: agent-framework\nappears_in_jobs: 5\n---\n# LangGraph\n"
    )
    update_skill_note("LangGraph", "https://example.com/jobs/x")
    loaded = frontmatter.load(skill_path)
    assert loaded.metadata["appears_in_jobs"] == 6


def test_update_skill_note_creates_if_missing(temp_vault):
    from compass.vault.writer import update_skill_note
    # No existing skill note — function should create a minimal one.
    update_skill_note("Python", "https://example.com/jobs/x")
    skill_path = temp_vault / "skills" / "Python.md"
    assert skill_path.exists()
    loaded = frontmatter.load(skill_path)
    assert loaded.metadata["skill"] == "Python"
    assert loaded.metadata["appears_in_jobs"] == 1


def test_write_company_note_creates_file(temp_vault):
    from compass.vault.writer import write_company_note
    from compass.vault.schemas import CompanyNote
    note = CompanyNote(company="Sierra", tier="apply-now", roles_seen=1, geo=["NYC"])
    path = write_company_note(note)
    assert path.exists()
    assert path.name == "Sierra.md"
    loaded = frontmatter.load(path)
    assert loaded.metadata["tier"] == "apply-now"
    assert loaded.metadata["roles_seen"] == 1


def test_write_company_note_increments_roles_seen(temp_vault):
    from compass.vault.writer import write_company_note
    from compass.vault.schemas import CompanyNote
    write_company_note(CompanyNote(company="Sierra", tier="apply-now", roles_seen=1))
    write_company_note(CompanyNote(company="Sierra", tier="apply-now", roles_seen=1))
    loaded = frontmatter.load(temp_vault / "companies" / "Sierra.md")
    assert loaded.metadata["roles_seen"] == 2


def test_append_agent_log_writes_line(temp_vault):
    from compass.vault.writer import append_agent_log
    append_agent_log("test action")
    log_text = (temp_vault / "_meta" / "agent-log.md").read_text()
    assert "test action" in log_text
    assert "\n" in log_text  # newline-terminated


def test_append_agent_log_preserves_existing_content(temp_vault):
    from compass.vault.writer import append_agent_log
    append_agent_log("first")
    append_agent_log("second")
    log_text = (temp_vault / "_meta" / "agent-log.md").read_text()
    assert "first" in log_text
    assert "second" in log_text
    # second should come after first
    assert log_text.index("first") < log_text.index("second")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/vault/test_writer.py -v`
Expected: 10 FAILs with `NotImplementedError`.

- [ ] **Step 3: Implement the writer**

Replace `compass/vault/writer.py` with:

```python
"""
Vault writer — writes structured notes to the Obsidian vault.

Rules:
- Never write raw markdown directly — always go through these functions.
- Every write validates frontmatter against compass.vault.schemas.
- Every mutation appends a one-line entry to _meta/agent-log.md.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import frontmatter

from compass.config import AGENT_LOG_PATH, VAULT_PATH
from compass.vault.schemas import CompanyNote, JobNote, SkillNote


_FILENAME_BAD = re.compile(r"[^\w\-.]+")


def _safe_segment(s: str) -> str:
    return _FILENAME_BAD.sub("_", s).strip("_")


def _job_filename(note: JobNote) -> str:
    return f"{note.date_found.isoformat()}-{_safe_segment(note.company)}-{_safe_segment(note.title)}.md"


def _to_metadata(model) -> dict:
    """Serialize a Pydantic model to a frontmatter-safe dict.

    JSON mode converts dates / datetimes / enums to strings; everything else
    we already use is YAML-friendly.
    """
    return model.model_dump(mode="json", by_alias=True)


def write_job_note(note: JobNote) -> Path:
    """Write a JobNote to vault/jobs/. Idempotent on URL — same URL overwrites the same file."""
    jobs_dir = VAULT_PATH / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)

    # Look for an existing file with the same URL first; if found, overwrite it.
    target: Path | None = None
    for existing in jobs_dir.glob("*.md"):
        try:
            post = frontmatter.load(existing)
        except Exception:
            continue
        if post.metadata.get("url") == note.url:
            target = existing
            break
    if target is None:
        target = jobs_dir / _job_filename(note)

    post = frontmatter.Post(content=f"# {note.company} — {note.title}\n\n{note.jd_summary}\n")
    post.metadata = _to_metadata(note)
    target.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    append_agent_log(f"vault_write job {note.company} {note.title} score={note.match_score}")
    return target


def update_skill_note(canonical_skill: str, job_url: str) -> Path:
    """Increment appears_in_jobs on a skill note. Creates a minimal note if missing."""
    skills_dir = VAULT_PATH / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    path = skills_dir / f"{_safe_segment(canonical_skill)}.md"

    if path.exists():
        post = frontmatter.load(path)
        post.metadata["appears_in_jobs"] = int(post.metadata.get("appears_in_jobs", 0)) + 1
    else:
        # Minimal placeholder — Phase 0.B `seed_skills.py` already creates richer notes for
        # canonical skills. This is a safety net for new skills the assessor hasn't seen yet.
        skill = SkillNote(
            skill=canonical_skill,
            category="agent-framework",  # placeholder; gap_aggregator/assessor can update later
            appears_in_jobs=1,
        )
        post = frontmatter.Post(content=f"# {canonical_skill}\n")
        post.metadata = _to_metadata(skill)

    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    append_agent_log(f"vault_write skill {canonical_skill} += 1 (from {job_url})")
    return path


def write_company_note(note: CompanyNote) -> Path:
    """Write or update a company note. Merges roles_seen if the file already exists."""
    companies_dir = VAULT_PATH / "companies"
    companies_dir.mkdir(parents=True, exist_ok=True)
    path = companies_dir / f"{_safe_segment(note.company)}.md"

    if path.exists():
        existing = frontmatter.load(path)
        existing_roles = int(existing.metadata.get("roles_seen", 0))
        note = note.model_copy(update={"roles_seen": existing_roles + note.roles_seen})

    post = frontmatter.Post(content=f"# {note.company}\n\n{note.why_interesting}\n")
    post.metadata = _to_metadata(note)
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    append_agent_log(f"vault_write company {note.company} roles_seen={note.roles_seen}")
    return path


def append_agent_log(action: str) -> None:
    """Append a one-line, timestamped entry to _meta/agent-log.md."""
    AGENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {action}\n"
    with AGENT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/vault/test_writer.py -v`
Expected: 10 PASSES.

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest -q`
Expected: 27 PASSES total (4 greenhouse + 3 lever + 3 ashby + 7 reader + 10 writer).

- [ ] **Step 6: Commit**

```bash
git add compass/vault/writer.py tests/vault/test_writer.py
git commit -m "feat(vault): implement writer with frontmatter + schema validation + agent log"
```

---

## Task 7: Live-API smoke test script (`scripts/test_scrape.py`)

**Files:**
- Create: `scripts/test_scrape.py`

Hits the real Greenhouse, Lever, and Ashby APIs against a known-good slug from each. NOT a pytest test — it makes real network calls.

- [ ] **Step 1: Write the script**

```python
"""
scripts/test_scrape.py — live-API smoke test for the three scrapers.

Runs against one known-good board per ATS. Expects each to return ≥ 1 RawJob.

Usage:
    uv run python scripts/test_scrape.py
"""
from __future__ import annotations

import asyncio
import sys

from compass.scrapers.ashby import scrape_ashby
from compass.scrapers.greenhouse import scrape_greenhouse
from compass.scrapers.lever import scrape_lever


async def main() -> int:
    targets = [
        ("greenhouse", "anthropic", scrape_greenhouse),
        ("lever", "shieldai", scrape_lever),
        ("ashby", "sierra", scrape_ashby),
    ]
    failures = 0
    for source, slug, fn in targets:
        try:
            jobs = await fn(slug)
        except Exception as e:
            print(f"  ❌ {source} {slug}: raised {type(e).__name__}: {e}")
            failures += 1
            continue
        if not jobs:
            print(f"  ❌ {source} {slug}: returned 0 jobs (expected ≥ 1)")
            failures += 1
            continue
        print(f"  ✅ {source} {slug}: {len(jobs)} jobs (sample: {jobs[0].title!r})")
    if failures:
        print(f"\nFAILED: {failures} of {len(targets)} sources")
        return 1
    print(f"\nPASSED: all {len(targets)} sources returned jobs")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: Run the smoke script**

Run: `cd ~/Documents/compass && VAULT_PATH=~/Documents/compass-vault OPENROUTER_API_KEY=stub uv run python scripts/test_scrape.py`
Expected: 3 ✅ lines, exit 0. If any ATS is having a bad day, retry — but a single failure should not break the build.

- [ ] **Step 3: Commit**

```bash
git add scripts/test_scrape.py
git commit -m "test(smoke): add live-API scraper smoke test"
```

---

## Task 8: Vault round-trip smoke test (`scripts/test_vault_roundtrip.py`)

**Files:**
- Create: `scripts/test_vault_roundtrip.py`

Writes a fake JobNote + Company + Skill to the real vault, reads them back, and confirms the schemas validate. Then deletes the fake artifacts so the vault stays clean.

- [ ] **Step 1: Write the script**

```python
"""
scripts/test_vault_roundtrip.py — round-trip a fake JobNote through the real vault.

Writes → reads → validates → cleans up. Intended to be run before deploying.

Usage:
    uv run python scripts/test_vault_roundtrip.py
"""
from __future__ import annotations

import sys
from datetime import date

import frontmatter

from compass.config import VAULT_PATH
from compass.vault.reader import job_url_exists, list_job_notes
from compass.vault.schemas import CompanyNote, JobNote
from compass.vault.writer import (
    append_agent_log,
    update_skill_note,
    write_company_note,
    write_job_note,
)

SENTINEL_URL = "https://example.com/compass-smoke-test/job/SENTINEL"
SENTINEL_COMPANY = "_SmokeTestCo"


def main() -> int:
    print(f"Vault path: {VAULT_PATH}")
    if not VAULT_PATH.exists():
        print(f"  ❌ VAULT_PATH does not exist")
        return 1

    note = JobNote(
        company=SENTINEL_COMPANY,
        title="Smoke Test Role",
        url=SENTINEL_URL,
        source="smoke",
        date_found=date.today(),
        match_score=0.0,
        skills_required=["Python"],
        jd_summary="(smoke test — safe to delete)",
    )

    # 1. Write
    job_path = write_job_note(note)
    print(f"  ✅ wrote job note: {job_path.name}")

    company_path = write_company_note(CompanyNote(company=SENTINEL_COMPANY, tier="unknown", roles_seen=1))
    print(f"  ✅ wrote company note: {company_path.name}")

    skill_path = update_skill_note("Python", SENTINEL_URL)
    print(f"  ✅ updated skill note: {skill_path.name}")

    append_agent_log("smoke test ran")
    print(f"  ✅ appended to agent-log")

    # 2. Read
    if not job_url_exists(SENTINEL_URL):
        print(f"  ❌ job_url_exists returned False for {SENTINEL_URL}")
        return 1
    print(f"  ✅ job_url_exists found the URL")

    if job_path not in list_job_notes():
        print(f"  ❌ list_job_notes did not include the new path")
        return 1
    print(f"  ✅ list_job_notes includes the new file")

    # 3. Validate round-tripped frontmatter
    loaded = frontmatter.load(job_path)
    if loaded.metadata.get("company") != SENTINEL_COMPANY:
        print(f"  ❌ company mismatch on reload: {loaded.metadata.get('company')!r}")
        return 1
    print(f"  ✅ frontmatter round-trips cleanly")

    # 4. Clean up
    job_path.unlink()
    company_path.unlink()
    print(f"  ✅ cleaned up sentinel files (skill note retained — has real counter)")

    print(f"\nPASSED: vault round-trip works end-to-end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the smoke script**

Run: `cd ~/Documents/compass && VAULT_PATH=~/Documents/compass-vault OPENROUTER_API_KEY=stub uv run python scripts/test_vault_roundtrip.py`
Expected: 8 ✅ lines, exit 0, vault has no `_SmokeTestCo*` files left.

- [ ] **Step 3: Commit**

```bash
git add scripts/test_vault_roundtrip.py
git commit -m "test(smoke): add vault round-trip smoke test"
```

---

## Task 9: Verify everything together

**Files:** none (verification only)

- [ ] **Step 1: Run the full pytest suite one more time**

Run: `cd ~/Documents/compass && uv run pytest -v`
Expected: 27 PASSES, 0 FAILs.

- [ ] **Step 2: Run both smoke scripts in sequence**

```bash
cd ~/Documents/compass
VAULT_PATH=~/Documents/compass-vault OPENROUTER_API_KEY=stub uv run python scripts/test_scrape.py
VAULT_PATH=~/Documents/compass-vault OPENROUTER_API_KEY=stub uv run python scripts/test_vault_roundtrip.py
```
Expected: both exit 0.

- [ ] **Step 3: Verify the vault is clean**

Run: `ls ~/Documents/compass-vault/jobs/ ~/Documents/compass-vault/companies/ | grep -i smoke`
Expected: no output (smoke sentinels cleaned up).

- [ ] **Step 4: Verify the agent log captured the writes**

Run: `tail -20 ~/Documents/compass-vault/_meta/agent-log.md`
Expected: see `vault_write job _SmokeTestCo`, `vault_write company _SmokeTestCo`, `smoke test ran` entries from the round-trip script.

- [ ] **Step 5: Tag the Phase 0.A completion**

```bash
git tag phase-0a-foundation -m "Phase 0.A complete: scrapers + vault I/O working independently"
```

- [ ] **Step 6: Confirm definition of done**

Verify all of the following are true:
- ✅ All three scrapers return live data when given a real slug
- ✅ Vault writer round-trips a JobNote, CompanyNote, and Skill update through schema validation
- ✅ `job_url_exists` correctly detects duplicates
- ✅ `agent-log.md` appends a line per write
- ✅ `pytest` reports 27 passing tests
- ✅ No new files in the vault that aren't real artifacts

If all six are checked, Phase 0.A is done. Phase 0.B is the pipeline-node + LLM build (separate plan).

---

## Quick reference

**Run all tests:** `uv run pytest -q`
**Run one test file:** `uv run pytest tests/vault/test_writer.py -v`
**Live smoke tests:** `uv run python scripts/test_scrape.py && uv run python scripts/test_vault_roundtrip.py`
**Total expected LoC:** ~280 net new across the 12 files in scope.

**If a step fails:** stop, read the error, fix the smallest thing that addresses it, re-run. Do not pile fixes — one fix per failure. Commit only when the failure is resolved AND tests pass.
