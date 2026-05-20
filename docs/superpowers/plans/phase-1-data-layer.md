# Phase 1 — Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Real job data flows in from Greenhouse, Lever, Ashby, and JobSpy, gets normalized into `RawJob` objects, lands cleanly in the Obsidian vault, and the RAG index is populated from skill notes.

**Architecture:** Each ATS scraper hits a public (no-auth) API, normalizes to `RawJob` via Pydantic, and returns a list. Vault writer serializes YAML frontmatter using `python-frontmatter`. RAG indexer reads `skills/*.md` notes and upserts into a ChromaDB `PersistentClient`, so the retriever can do semantic lookup by job description query.

**Tech Stack:** `httpx` (async HTTP), `python-frontmatter` (vault I/O), `chromadb` (vector store), `sentence-transformers` + `all-MiniLM-L6-v2` (embeddings), `python-jobspy` (LinkedIn/Indeed aggregator), `pytest` + `pytest-asyncio` + `pytest-httpx` (testing)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `compass/config.py` | Modify | Add CHROMA_PATH, EMBEDDING_MODEL, HITL_STATE_DB, MAX_CONCURRENT_JOBS |
| `compass/scrapers/greenhouse.py` | Implement | `scrape_greenhouse(board_token)` → `list[RawJob]` |
| `compass/scrapers/lever.py` | Implement | `scrape_lever(company)` → `list[RawJob]` |
| `compass/scrapers/ashby.py` | Implement | `scrape_ashby(board_name)` → `list[RawJob]` |
| `compass/scrapers/jobspy_wrapper.py` | Implement | `scrape_jobspy(search_term, location)` → `list[RawJob]` |
| `compass/vault/writer.py` | Implement | `write_job_note()`, `update_skill_note()`, `write_company_note()` |
| `compass/vault/reader.py` | Implement | `read_skill_inventory()`, `read_profile_section()`, `read_resume()`, `job_url_exists()`, `list_job_notes()` |
| `compass/rag/indexer.py` | Create | `build_index()` → int (populates Chroma from skills/*.md) |
| `compass/rag/retriever.py` | Create | `retrieve_relevant_skills(query, n_results)` → `list[str]` |
| `tests/test_scrapers.py` | Expand | Add Lever, Ashby, JobSpy tests (Greenhouse tests already exist) |
| `tests/test_vault.py` | Expand | Fill in writer/reader integration tests using tmp_path |
| `tests/test_rag.py` | Implement | Index build + retrieval tests using tmp_path |

---

## Task 0: Config Additions

**Files:**
- Modify: `compass/config.py`

- [ ] **Step 1: Add missing config entries**

Add to the end of `compass/config.py` (after the ATS targets block):

```python
# ── RAG ───────────────────────────────────────────────────────────────────────
CHROMA_PATH: Path = Path(os.getenv("CHROMA_PATH", str(Path.home() / ".compass" / "chroma")))
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# ── HiTL state store ──────────────────────────────────────────────────────────
HITL_STATE_DB: Path = Path(os.getenv("HITL_STATE_DB", str(Path.home() / ".compass" / "hitl.db")))
MAX_CONCURRENT_JOBS: int = int(os.getenv("MAX_CONCURRENT_JOBS", "5"))
```

- [ ] **Step 2: Verify config loads without error**

```bash
cd /Users/<user>/Documents/compass && uv run python -c "from compass.config import CHROMA_PATH, EMBEDDING_MODEL, HITL_STATE_DB, MAX_CONCURRENT_JOBS; print(CHROMA_PATH, EMBEDDING_MODEL)"
```

Expected: prints the path and model name without ImportError.

- [ ] **Step 3: Commit**

```bash
git add compass/config.py
git commit -m "feat: add RAG and HiTL config entries"
```

---

## Task 1: Greenhouse Scraper

**Files:**
- Implement: `compass/scrapers/greenhouse.py`
- Test: `tests/test_scrapers.py` (tests already written — make them pass)

- [ ] **Step 1: Run the existing tests to confirm they fail**

```bash
cd /Users/<user>/Documents/compass && uv run pytest tests/test_scrapers.py::test_scrape_greenhouse_returns_jobs -v
```

Expected: `FAILED` with `NotImplementedError`.

- [ ] **Step 2: Implement `compass/scrapers/greenhouse.py`**

```python
"""
Greenhouse public API scraper.

Endpoint: GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
No authentication required — fully public.
Returns normalized RawJob objects.
"""
import html
import asyncio
from html.parser import HTMLParser
from datetime import date
import httpx
from compass.pipeline.state import RawJob


GREENHOUSE_BASE = "https://boards-api.greenhouse.io/v1/boards"
_SEMAPHORE = asyncio.Semaphore(5)


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(p.strip() for p in self._parts if p.strip())


def _strip_html(raw: str) -> str:
    stripper = _HTMLStripper()
    stripper.feed(html.unescape(raw or ""))
    return stripper.get_text()


async def _get_company_name(client: httpx.AsyncClient, board_token: str) -> str:
    try:
        r = await client.get(f"{GREENHOUSE_BASE}/{board_token}")
        if r.status_code == 200:
            return r.json().get("name", board_token.replace("-", " ").title())
    except httpx.HTTPError:
        pass
    return board_token.replace("-", " ").title()


async def scrape_greenhouse(board_token: str) -> list[RawJob]:
    """Scrape all open jobs from a Greenhouse board."""
    async with _SEMAPHORE:
        async with httpx.AsyncClient(timeout=30) as client:
            company = await _get_company_name(client, board_token)
            url = f"{GREENHOUSE_BASE}/{board_token}/jobs?content=true"
            try:
                r = await client.get(url)
                if r.status_code == 404:
                    return []
                r.raise_for_status()
            except httpx.HTTPError:
                return []

            jobs = []
            for item in r.json().get("jobs", []):
                location = (item.get("location") or {}).get("name")
                remote = location is not None and "remote" in location.lower()
                jobs.append(RawJob(
                    company=company,
                    title=item["title"],
                    url=item["absolute_url"],
                    source="greenhouse",
                    location=location,
                    remote=remote if remote else None,
                    description=_strip_html(item.get("content", "")),
                ))
            return jobs


async def scrape_greenhouse_many(board_tokens: list[str]) -> list[RawJob]:
    """Scrape multiple Greenhouse boards concurrently."""
    results = await asyncio.gather(
        *[scrape_greenhouse(token) for token in board_tokens],
        return_exceptions=True,
    )
    jobs: list[RawJob] = []
    for r in results:
        if isinstance(r, list):
            jobs.extend(r)
    return jobs
```

- [ ] **Step 3: Run the Greenhouse tests**

```bash
cd /Users/<user>/Documents/compass && uv run pytest tests/test_scrapers.py -k "greenhouse" -v
```

Expected: 4 tests PASS. (These hit the real Greenhouse API — needs internet.)

- [ ] **Step 4: Commit**

```bash
git add compass/scrapers/greenhouse.py
git commit -m "feat: implement Greenhouse scraper"
```

---

## Task 2: Lever Scraper

**Files:**
- Implement: `compass/scrapers/lever.py`
- Expand: `tests/test_scrapers.py`

- [ ] **Step 1: Add Lever tests to `tests/test_scrapers.py`**

Append to the file:

```python
from compass.scrapers.lever import scrape_lever, scrape_lever_many


@pytest.mark.asyncio
async def test_scrape_lever_returns_jobs():
    """Lever API is public — real integration test. Figma uses Lever."""
    jobs = await scrape_lever("figma")
    assert isinstance(jobs, list)
    assert len(jobs) > 0
    assert all(isinstance(j, RawJob) for j in jobs)


@pytest.mark.asyncio
async def test_scrape_lever_job_has_required_fields():
    jobs = await scrape_lever("figma")
    for job in jobs[:3]:
        assert job.title
        assert job.url.startswith("https://jobs.lever.co/")
        assert job.source == "lever"
        assert job.description


@pytest.mark.asyncio
async def test_scrape_lever_invalid_company():
    jobs = await scrape_lever("this-company-does-not-exist-xyz-999")
    assert jobs == []


@pytest.mark.asyncio
async def test_scrape_lever_many():
    jobs = await scrape_lever_many(["figma"])
    assert len(jobs) > 0
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/<user>/Documents/compass && uv run pytest tests/test_scrapers.py -k "lever" -v
```

Expected: `FAILED` with `NotImplementedError`.

- [ ] **Step 3: Implement `compass/scrapers/lever.py`**

```python
"""
Lever public API scraper.

Endpoint: GET https://api.lever.co/v0/postings/{company}?mode=json
No authentication required — fully public.
"""
import asyncio
import httpx
from compass.pipeline.state import RawJob


LEVER_BASE = "https://api.lever.co/v0/postings"
_SEMAPHORE = asyncio.Semaphore(5)


async def scrape_lever(company: str) -> list[RawJob]:
    """Scrape open jobs from a Lever company board."""
    async with _SEMAPHORE:
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                r = await client.get(f"{LEVER_BASE}/{company}?mode=json")
                if r.status_code == 404:
                    return []
                r.raise_for_status()
            except httpx.HTTPError:
                return []

            jobs = []
            for item in r.json():
                categories = item.get("categories", {})
                location = categories.get("location")
                workplace = item.get("workplaceType", "")
                remote = workplace == "remote" or (
                    location is not None and "remote" in location.lower()
                )
                salary = item.get("salaryRange") or {}
                jobs.append(RawJob(
                    company=company.replace("-", " ").title(),
                    title=item["text"],
                    url=item["hostedUrl"],
                    source="lever",
                    location=location,
                    remote=remote if remote else None,
                    salary_min=salary.get("min"),
                    salary_max=salary.get("max"),
                    description=item.get("descriptionPlain", ""),
                ))
            return jobs


async def scrape_lever_many(companies: list[str]) -> list[RawJob]:
    """Scrape multiple Lever boards concurrently."""
    results = await asyncio.gather(
        *[scrape_lever(company) for company in companies],
        return_exceptions=True,
    )
    jobs: list[RawJob] = []
    for r in results:
        if isinstance(r, list):
            jobs.extend(r)
    return jobs
```

- [ ] **Step 4: Run Lever tests**

```bash
cd /Users/<user>/Documents/compass && uv run pytest tests/test_scrapers.py -k "lever" -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add compass/scrapers/lever.py tests/test_scrapers.py
git commit -m "feat: implement Lever scraper"
```

---

## Task 3: Ashby Scraper

**Files:**
- Implement: `compass/scrapers/ashby.py`
- Expand: `tests/test_scrapers.py`

- [ ] **Step 1: Add Ashby tests**

Append to `tests/test_scrapers.py`:

```python
from compass.scrapers.ashby import scrape_ashby, scrape_ashby_many


@pytest.mark.asyncio
async def test_scrape_ashby_returns_jobs():
    """Ashby API is public. PostHog uses Ashby."""
    jobs = await scrape_ashby("posthog")
    assert isinstance(jobs, list)
    assert len(jobs) > 0
    assert all(isinstance(j, RawJob) for j in jobs)


@pytest.mark.asyncio
async def test_scrape_ashby_job_has_required_fields():
    jobs = await scrape_ashby("posthog")
    for job in jobs[:3]:
        assert job.title
        assert job.url.startswith("https://")
        assert job.source == "ashby"
        assert job.description


@pytest.mark.asyncio
async def test_scrape_ashby_invalid_board():
    jobs = await scrape_ashby("this-board-does-not-exist-xyz-999")
    assert jobs == []


@pytest.mark.asyncio
async def test_scrape_ashby_many():
    jobs = await scrape_ashby_many(["posthog"])
    assert len(jobs) > 0
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/<user>/Documents/compass && uv run pytest tests/test_scrapers.py -k "ashby" -v
```

Expected: `FAILED` with `NotImplementedError`.

- [ ] **Step 3: Implement `compass/scrapers/ashby.py`**

```python
"""
Ashby public API scraper.

Endpoint: GET https://api.ashbyhq.com/posting-api/job-board/{boardName}?includeCompensation=true
No authentication required.
Covers: PostHog, Linear, Ramp, Vercel, LangChain, and many AI-native companies.
"""
import asyncio
import html
from html.parser import HTMLParser
import httpx
from compass.pipeline.state import RawJob


ASHBY_BASE = "https://api.ashbyhq.com/posting-api/job-board"
_SEMAPHORE = asyncio.Semaphore(5)


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(p.strip() for p in self._parts if p.strip())


def _strip_html(raw: str) -> str:
    stripper = _HTMLStripper()
    stripper.feed(html.unescape(raw or ""))
    return stripper.get_text()


async def scrape_ashby(board_name: str) -> list[RawJob]:
    """Scrape open jobs from an Ashby job board."""
    async with _SEMAPHORE:
        async with httpx.AsyncClient(timeout=30) as client:
            url = f"{ASHBY_BASE}/{board_name}?includeCompensation=true"
            try:
                r = await client.get(url)
                if r.status_code in (404, 422):
                    return []
                r.raise_for_status()
            except httpx.HTTPError:
                return []

            jobs = []
            for item in r.json().get("jobs", []):
                comp = item.get("compensation") or {}
                job_url = item.get("jobUrl", "")
                description = _strip_html(item.get("descriptionHtml", "")) or item.get("descriptionPlain", "")
                jobs.append(RawJob(
                    company=board_name.replace("-", " ").title(),
                    title=item["title"],
                    url=job_url,
                    source="ashby",
                    location=item.get("locationName"),
                    remote=item.get("isRemote"),
                    salary_min=comp.get("minValue"),
                    salary_max=comp.get("maxValue"),
                    description=description,
                ))
            return jobs


async def scrape_ashby_many(board_names: list[str]) -> list[RawJob]:
    """Scrape multiple Ashby boards concurrently."""
    results = await asyncio.gather(
        *[scrape_ashby(name) for name in board_names],
        return_exceptions=True,
    )
    jobs: list[RawJob] = []
    for r in results:
        if isinstance(r, list):
            jobs.extend(r)
    return jobs
```

- [ ] **Step 4: Run Ashby tests**

```bash
cd /Users/<user>/Documents/compass && uv run pytest tests/test_scrapers.py -k "ashby" -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add compass/scrapers/ashby.py tests/test_scrapers.py
git commit -m "feat: implement Ashby scraper"
```

---

## Task 4: JobSpy Wrapper

**Files:**
- Implement: `compass/scrapers/jobspy_wrapper.py`
- Expand: `tests/test_scrapers.py`

JobSpy hits live sites (LinkedIn/Indeed). Tests use `unittest.mock` to avoid network calls.

- [ ] **Step 1: Add JobSpy tests**

Append to `tests/test_scrapers.py`:

```python
from unittest.mock import patch, MagicMock
import pandas as pd
from compass.scrapers.jobspy_wrapper import scrape_jobspy


@pytest.mark.asyncio
async def test_scrape_jobspy_returns_jobs():
    """JobSpy is mocked — real calls hit LinkedIn which rate-limits."""
    mock_df = pd.DataFrame([{
        "title": "AI Engineer",
        "company": "OpenAI",
        "job_url": "https://openai.com/jobs/1",
        "location": "San Francisco, CA",
        "is_remote": True,
        "min_amount": 200000,
        "max_amount": 300000,
        "description": "Build the future of AI.",
        "site": "linkedin",
    }])
    with patch("compass.scrapers.jobspy_wrapper.scrape_jobs", return_value=mock_df):
        jobs = await scrape_jobspy("AI engineer", location="United States")
    assert len(jobs) == 1
    assert jobs[0].title == "AI Engineer"
    assert jobs[0].source == "jobspy"


@pytest.mark.asyncio
async def test_scrape_jobspy_graceful_on_empty():
    """Returns empty list when JobSpy returns no results."""
    with patch("compass.scrapers.jobspy_wrapper.scrape_jobs", return_value=pd.DataFrame()):
        jobs = await scrape_jobspy("extremely obscure role xyz", location="Mars")
    assert jobs == []


@pytest.mark.asyncio
async def test_scrape_jobspy_graceful_on_error():
    """Returns empty list when JobSpy raises (e.g., rate limited)."""
    with patch("compass.scrapers.jobspy_wrapper.scrape_jobs", side_effect=Exception("rate limited")):
        jobs = await scrape_jobspy("AI engineer")
    assert jobs == []
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /Users/<user>/Documents/compass && uv run pytest tests/test_scrapers.py -k "jobspy" -v
```

Expected: `FAILED` with `NotImplementedError`.

- [ ] **Step 3: Implement `compass/scrapers/jobspy_wrapper.py`**

```python
"""
JobSpy wrapper — aggregates LinkedIn, Indeed, Glassdoor, ZipRecruiter.

JobSpy's scrape_jobs() is synchronous. Run in a thread executor to avoid blocking.
Always design for graceful degradation: LinkedIn rate-limits aggressively.
"""
import asyncio
from compass.pipeline.state import RawJob

try:
    from jobspy import scrape_jobs
except ImportError:
    scrape_jobs = None  # type: ignore


async def scrape_jobspy(
    search_term: str,
    location: str = "United States",
    results_wanted: int = 20,
) -> list[RawJob]:
    """Scrape jobs via JobSpy aggregator. Falls back gracefully on errors."""
    if scrape_jobs is None:
        return []

    loop = asyncio.get_event_loop()
    try:
        df = await loop.run_in_executor(
            None,
            lambda: scrape_jobs(
                site_name=["linkedin", "indeed"],
                search_term=search_term,
                location=location,
                results_wanted=results_wanted,
                hours_old=72,
            ),
        )
    except Exception:
        return []

    if df is None or df.empty:
        return []

    jobs = []
    for _, row in df.iterrows():
        jobs.append(RawJob(
            company=str(row.get("company", "Unknown")),
            title=str(row.get("title", "")),
            url=str(row.get("job_url", "")),
            source="jobspy",
            location=row.get("location"),
            remote=bool(row.get("is_remote")) if row.get("is_remote") is not None else None,
            salary_min=int(row["min_amount"]) if row.get("min_amount") else None,
            salary_max=int(row["max_amount"]) if row.get("max_amount") else None,
            description=str(row.get("description", "")),
        ))
    return jobs
```

- [ ] **Step 4: Run JobSpy tests**

```bash
cd /Users/<user>/Documents/compass && uv run pytest tests/test_scrapers.py -k "jobspy" -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Run all scraper tests**

```bash
cd /Users/<user>/Documents/compass && uv run pytest tests/test_scrapers.py -v
```

Expected: All 11+ tests PASS.

- [ ] **Step 6: Commit**

```bash
git add compass/scrapers/jobspy_wrapper.py tests/test_scrapers.py
git commit -m "feat: implement JobSpy wrapper"
```

---

## Task 5: Vault Writer

**Files:**
- Implement: `compass/vault/writer.py`
- Expand: `tests/test_vault.py`

- [ ] **Step 1: Add writer tests to `tests/test_vault.py`**

Replace the two `pass` tests and add writer tests. Full additions:

```python
import frontmatter as fm
from pathlib import Path
from datetime import date
import pytest
from compass.vault.schemas import JobNote, SkillNote, CompanyNote
from compass.vault import writer
import compass.vault.writer as writer_mod
import compass.vault.reader as reader_mod


def _make_job_note(**kwargs) -> JobNote:
    defaults = dict(
        company="Databricks",
        title="AI Engineer",
        url="https://databricks.com/jobs/1",
        source="greenhouse",
        date_found=date.today(),
        match_score=4.2,
        jd_summary="Build LLM stuff on the Databricks Lakehouse.",
    )
    defaults.update(kwargs)
    return JobNote(**defaults)


def test_write_job_note_creates_file(tmp_path, monkeypatch):
    monkeypatch.setattr(writer_mod, "VAULT_PATH", tmp_path)
    note = _make_job_note()
    path = writer.write_job_note(note)
    assert path.exists()
    assert path.suffix == ".md"
    assert "Databricks" in path.name


def test_write_job_note_frontmatter(tmp_path, monkeypatch):
    monkeypatch.setattr(writer_mod, "VAULT_PATH", tmp_path)
    note = _make_job_note(match_score=3.9, skills_missing=["MLflow"])
    path = writer.write_job_note(note)
    post = fm.load(str(path))
    assert post["company"] == "Databricks"
    assert post["match_score"] == 3.9
    assert "MLflow" in post["skills_missing"]
    assert post["status"] == "reviewing"


def test_update_skill_note_creates_if_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(writer_mod, "VAULT_PATH", tmp_path)
    (tmp_path / "skills").mkdir()
    writer.update_skill_note("LangGraph", "https://example.com/job/1")
    path = tmp_path / "skills" / "LangGraph.md"
    assert path.exists()
    post = fm.load(str(path))
    assert post["appears_in_jobs"] == 1


def test_update_skill_note_increments_counter(tmp_path, monkeypatch):
    monkeypatch.setattr(writer_mod, "VAULT_PATH", tmp_path)
    (tmp_path / "skills").mkdir()
    writer.update_skill_note("LangGraph", "https://example.com/job/1")
    writer.update_skill_note("LangGraph", "https://example.com/job/2")
    post = fm.load(str(tmp_path / "skills" / "LangGraph.md"))
    assert post["appears_in_jobs"] == 2


def test_write_company_note(tmp_path, monkeypatch):
    monkeypatch.setattr(writer_mod, "VAULT_PATH", tmp_path)
    note = CompanyNote(company="Databricks", tier="apply-now", hiring_signal="active")
    path = writer.write_company_note(note)
    assert path.exists()
    post = fm.load(str(path))
    assert post["company"] == "Databricks"
    assert post["tier"] == "apply-now"
```

- [ ] **Step 2: Run to verify failures**

```bash
cd /Users/<user>/Documents/compass && uv run pytest tests/test_vault.py -k "write or update" -v
```

Expected: FAILED with `NotImplementedError`.

- [ ] **Step 3: Implement `compass/vault/writer.py`**

```python
"""
Vault writer — writes structured notes to the Obsidian vault.

Rules:
- Never write raw markdown directly — always use these functions
- Never delete vault files — the vault is append-only from the pipeline
- Always validate frontmatter against schemas before writing
- File naming: jobs/YYYY-MM-DD-Company-Title.md
"""
import re
from pathlib import Path
import frontmatter
from compass.config import VAULT_PATH
from compass.vault.schemas import JobNote, SkillNote, CompanyNote


def _slugify(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9-]", "-", text).strip("-")


def _serialize(d: dict) -> dict:
    """Convert Pydantic model dict to YAML-safe types."""
    result = {}
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


def write_job_note(note: JobNote) -> Path:
    """Write a job note to vault/jobs/. Creates the file, returns its path."""
    date_str = note.date_found.isoformat()
    company_slug = _slugify(note.company)
    title_slug = _slugify(note.title)[:50]
    filename = f"{date_str}-{company_slug}-{title_slug}.md"

    path = VAULT_PATH / "jobs" / filename
    path.parent.mkdir(parents=True, exist_ok=True)

    body = f"## Summary\n\n{note.jd_summary}\n"
    post = frontmatter.Post(body, **_serialize(note.model_dump()))

    with open(path, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))
    return path


def update_skill_note(skill: str, job_url: str) -> None:
    """Increment appears_in_jobs counter on a skill note. Creates it if missing."""
    path = VAULT_PATH / "skills" / f"{skill}.md"
    if path.exists():
        post = frontmatter.load(str(path))
        post["appears_in_jobs"] = post.get("appears_in_jobs", 0) + 1
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        post = frontmatter.Post(
            "",
            skill=skill,
            category="unknown",
            my_level="none",
            appears_in_jobs=1,
            priority="medium",
            resources=[],
            evidence=[],
        )
    with open(path, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))


def write_company_note(note: CompanyNote) -> Path:
    """Write or update a company note. Creates the file if it doesn't exist."""
    path = VAULT_PATH / "companies" / f"{note.company}.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        post = frontmatter.load(str(path))
        for key, value in _serialize(note.model_dump()).items():
            post[key] = value
    else:
        post = frontmatter.Post("", **_serialize(note.model_dump()))

    with open(path, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))
    return path
```

- [ ] **Step 4: Run writer tests**

```bash
cd /Users/<user>/Documents/compass && uv run pytest tests/test_vault.py -k "write or update" -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add compass/vault/writer.py tests/test_vault.py
git commit -m "feat: implement vault writer"
```

---

## Task 6: Vault Reader

**Files:**
- Implement: `compass/vault/reader.py`
- Expand: `tests/test_vault.py`

- [ ] **Step 1: Replace the placeholder tests in `tests/test_vault.py`**

Delete the two existing `pass`-stub async tests (`test_vault_reader_skill_inventory` and `test_job_url_deduplication`) and append the following real implementations (they supersede the stubs — same test names, sync not async, actual assertions):

```python
import compass.vault.reader as reader_mod
from compass.vault.reader import (
    read_profile_section,
    read_skill_inventory,
    read_resume,
    job_url_exists,
    list_job_notes,
)


def test_read_profile_section(tmp_path, monkeypatch):
    monkeypatch.setattr(reader_mod, "VAULT_PATH", tmp_path)
    profile = tmp_path / "_profile"
    profile.mkdir()
    (profile / "skill-inventory.md").write_text("# Skills\n- Python\n")
    result = read_profile_section("skill-inventory")
    assert "Python" in result


def test_read_profile_section_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(reader_mod, "VAULT_PATH", tmp_path)
    result = read_profile_section("nonexistent-section")
    assert result == ""


def test_read_skill_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(reader_mod, "VAULT_PATH", tmp_path)
    (tmp_path / "_profile").mkdir()
    (tmp_path / "_profile" / "skill-inventory.md").write_text("| Skill | Level |\n|---|---|\n| Python | proficient |")
    content = read_skill_inventory()
    assert "Python" in content


def test_job_url_deduplication(tmp_path, monkeypatch):
    """job_url_exists correctly identifies duplicate job URLs."""
    monkeypatch.setattr(writer_mod, "VAULT_PATH", tmp_path)
    monkeypatch.setattr(reader_mod, "VAULT_PATH", tmp_path)
    note = _make_job_note(url="https://databricks.com/jobs/unique-42")
    writer.write_job_note(note)
    assert job_url_exists("https://databricks.com/jobs/unique-42") is True
    assert job_url_exists("https://databricks.com/jobs/other-999") is False


def test_list_job_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(writer_mod, "VAULT_PATH", tmp_path)
    monkeypatch.setattr(reader_mod, "VAULT_PATH", tmp_path)
    writer.write_job_note(_make_job_note(url="https://databricks.com/jobs/1"))
    writer.write_job_note(_make_job_note(url="https://databricks.com/jobs/2", title="ML Engineer"))
    notes = list_job_notes()
    assert len(notes) == 2
    assert all(p.suffix == ".md" for p in notes)
```

- [ ] **Step 2: Run to verify failures**

```bash
cd /Users/<user>/Documents/compass && uv run pytest tests/test_vault.py -k "read or url or list_job" -v
```

Expected: FAILED with `NotImplementedError`.

- [ ] **Step 3: Implement `compass/vault/reader.py`**

```python
"""
Vault reader — reads structured notes from the Obsidian vault.
"""
from pathlib import Path
import frontmatter
from compass.config import VAULT_PATH


def read_profile_section(section: str) -> str:
    """Read a section from _profile/. section = filename without .md"""
    path = VAULT_PATH / "_profile" / f"{section}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def read_skill_inventory() -> str:
    """Read the full skill-inventory.md as a string for LLM context."""
    return read_profile_section("skill-inventory")


def read_resume() -> str:
    """Read resume.md as a string."""
    return read_profile_section("resume")


def job_url_exists(url: str) -> bool:
    """Check if a job with this URL already exists in the vault (deduplication)."""
    jobs_dir = VAULT_PATH / "jobs"
    if not jobs_dir.exists():
        return False
    for path in jobs_dir.glob("*.md"):
        try:
            post = frontmatter.load(str(path))
            if post.get("url") == url:
                return True
        except Exception:
            continue
    return False


def list_job_notes() -> list[Path]:
    """Return all job note paths in vault/jobs/, sorted by name."""
    jobs_dir = VAULT_PATH / "jobs"
    if not jobs_dir.exists():
        return []
    return sorted(jobs_dir.glob("*.md"))
```

- [ ] **Step 4: Run all vault tests**

```bash
cd /Users/<user>/Documents/compass && uv run pytest tests/test_vault.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add compass/vault/reader.py tests/test_vault.py
git commit -m "feat: implement vault reader"
```

---

## Task 7: RAG Indexer + Retriever

**Files:**
- Create: `compass/rag/indexer.py`
- Create: `compass/rag/retriever.py`
- Implement: `tests/test_rag.py`

The RAG layer requires `compass.config.CHROMA_PATH` and `compass.config.VAULT_PATH`. Both modules reference `config.CHROMA_PATH` at call time (not import time), so monkeypatching `compass.config.CHROMA_PATH` in tests works correctly.

- [ ] **Step 1: Write `tests/test_rag.py`**

```python
"""
RAG indexer + retriever tests.
Run: uv run pytest tests/test_rag.py -v
"""
import pytest
from pathlib import Path
import compass.config as config
from compass.rag.indexer import build_index
from compass.rag.retriever import retrieve_relevant_skills


def _seed_skills(skills_dir: Path) -> None:
    (skills_dir / "LangGraph.md").write_text(
        "---\nskill: LangGraph\ncategory: agent-framework\nmy_level: proficient\n---\n"
        "LangGraph is a stateful graph framework for building LLM agents with checkpointing."
    )
    (skills_dir / "Python.md").write_text(
        "---\nskill: Python\ncategory: language\nmy_level: expert\n---\n"
        "Python is the primary language for data science and machine learning."
    )
    (skills_dir / "ChromaDB.md").write_text(
        "---\nskill: ChromaDB\ncategory: data\nmy_level: learning\n---\n"
        "ChromaDB is an open-source vector database for semantic search."
    )


def test_build_index_returns_count(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHROMA_PATH", tmp_path / "chroma")
    monkeypatch.setattr(config, "VAULT_PATH", tmp_path)
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _seed_skills(skills_dir)
    count = build_index()
    assert count == 3


def test_build_index_is_idempotent(tmp_path, monkeypatch):
    """Running build_index twice should not raise and count stays correct."""
    monkeypatch.setattr(config, "CHROMA_PATH", tmp_path / "chroma")
    monkeypatch.setattr(config, "VAULT_PATH", tmp_path)
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _seed_skills(skills_dir)
    build_index()
    count = build_index()
    assert count == 3


def test_build_index_empty_skills_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHROMA_PATH", tmp_path / "chroma")
    monkeypatch.setattr(config, "VAULT_PATH", tmp_path)
    (tmp_path / "skills").mkdir()
    count = build_index()
    assert count == 0


def test_retrieve_relevant_skills(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHROMA_PATH", tmp_path / "chroma")
    monkeypatch.setattr(config, "VAULT_PATH", tmp_path)
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    _seed_skills(skills_dir)
    build_index()

    results = retrieve_relevant_skills("agentic LLM pipeline stateful graph", n_results=3)
    assert len(results) >= 1
    assert any("LangGraph" in r for r in results)


def test_retrieve_relevant_skills_no_index_returns_empty(tmp_path, monkeypatch):
    """Retriever returns empty list gracefully if index doesn't exist."""
    monkeypatch.setattr(config, "CHROMA_PATH", tmp_path / "chroma-empty")
    results = retrieve_relevant_skills("anything")
    assert results == []
```

- [ ] **Step 2: Run to verify failures**

```bash
cd /Users/<user>/Documents/compass && uv run pytest tests/test_rag.py -v
```

Expected: `ERROR` or `FAILED` (modules don't exist yet).

- [ ] **Step 3: Create `compass/rag/indexer.py`**

```python
"""
RAG indexer — builds or refreshes the skill index in ChromaDB.

Call build_index() before any pipeline run or when skills/*.md notes change.
Operation is idempotent: upsert by skill name (file stem).
"""
from sentence_transformers import SentenceTransformer
import chromadb
import compass.config as config

_COLLECTION = "skill-index"
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(config.EMBEDDING_MODEL)
    return _model


def build_index() -> int:
    """Build or refresh the skill index. Returns number of documents indexed."""
    skills_dir = config.VAULT_PATH / "skills"
    if not skills_dir.exists():
        return 0

    skill_files = list(skills_dir.glob("*.md"))
    if not skill_files:
        return 0

    model = _get_model()
    client = chromadb.PersistentClient(path=str(config.CHROMA_PATH))
    collection = client.get_or_create_collection(_COLLECTION)

    docs, ids, embeddings = [], [], []
    for path in skill_files:
        text = path.read_text(encoding="utf-8")
        docs.append(text)
        ids.append(path.stem)
        embeddings.append(model.encode(text).tolist())

    collection.upsert(documents=docs, ids=ids, embeddings=embeddings)
    return len(docs)
```

- [ ] **Step 4: Create `compass/rag/retriever.py`**

```python
"""
RAG retriever — semantic skill lookup for the score_node.

retrieve_relevant_skills() returns the top-k skill note texts most relevant
to the given query (typically a job description or list of required skills).
"""
import chromadb
import compass.config as config
from compass.rag.indexer import _get_model, _COLLECTION


def retrieve_relevant_skills(query: str, n_results: int = 10) -> list[str]:
    """Return top-k skill note texts relevant to query. Returns [] if index empty."""
    try:
        client = chromadb.PersistentClient(path=str(config.CHROMA_PATH))
        collection = client.get_collection(_COLLECTION)
    except Exception:
        return []

    total = collection.count()
    if total == 0:
        return []

    model = _get_model()
    query_embedding = model.encode(query).tolist()

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(n_results, total),
    )
    return results.get("documents", [[]])[0]
```

- [ ] **Step 5: Run RAG tests**

```bash
cd /Users/<user>/Documents/compass && uv run pytest tests/test_rag.py -v
```

Expected: 5 tests PASS. (First run downloads the `all-MiniLM-L6-v2` model — ~80MB, takes ~30 seconds.)

- [ ] **Step 6: Commit**

```bash
git add compass/rag/indexer.py compass/rag/retriever.py tests/test_rag.py
git commit -m "feat: implement RAG indexer and retriever"
```

---

## Task 8: Full Test Sweep + Smoke Test

**Files:**
- No new files

- [ ] **Step 1: Run the full test suite**

```bash
cd /Users/<user>/Documents/compass && uv run pytest tests/test_scrapers.py tests/test_vault.py tests/test_rag.py -v
```

Expected: All tests PASS. Fix any remaining failures before continuing.

- [ ] **Step 2: Smoke test — scrape a real board end-to-end**

```bash
cd /Users/<user>/Documents/compass && uv run python -c "
import asyncio
from compass.scrapers.greenhouse import scrape_greenhouse
jobs = asyncio.run(scrape_greenhouse('databricks'))
print(f'{len(jobs)} jobs scraped from Databricks Greenhouse')
print(f'First job: {jobs[0].title} — {jobs[0].url}')
"
```

Expected: prints job count (typically 50-200) and first job title.

- [ ] **Step 3: Smoke test — build RAG index from real vault**

```bash
cd /Users/<user>/Documents/compass && uv run python -c "
from compass.rag.indexer import build_index
from compass.rag.retriever import retrieve_relevant_skills
n = build_index()
print(f'Indexed {n} skill notes')
results = retrieve_relevant_skills('LangGraph agentic pipeline stateful', n_results=5)
print(f'Top result snippet: {results[0][:100] if results else \"(empty)\"}')
"
```

Expected: prints your seeded skill count (70 if seed_skills.py ran without issues), then a LangGraph skill snippet.

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "feat: phase 1 data layer complete — scrapers, vault I/O, RAG index"
```

---

## Definition of Done

- [ ] `uv run pytest tests/test_scrapers.py tests/test_vault.py tests/test_rag.py` — all green
- [ ] `scrape_greenhouse("databricks")` returns real jobs
- [ ] `build_index()` returns the count of your seeded skill notes (70 if seed_skills.py ran)
- [ ] `retrieve_relevant_skills("LangGraph stateful graph")` returns relevant skill text

**What comes next:** Phase 2 — wire the pipeline. `START → intake_node → extract_node → score_node → vault_write_node → END`. First Langfuse traces appear.
