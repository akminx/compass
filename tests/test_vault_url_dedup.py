"""Tests for compass.pipeline.graph._vault_url_set — the URL dedup set
that prevents the same job from being re-scraped/re-paused across runs.

Pre-fix (2026-05-20) it only read from `jobs/`. URLs in `jobs-archive/`
or `hitl-pending/` were invisible to dedup, so:
- Archived jobs would get re-scored on the next run
- Paused HiTL jobs would get re-paused with new thread_ids on each run
  (LangChain pile-up bug — user had 17 LangChain pending rows for 6 URLs)
"""

from __future__ import annotations

import frontmatter

from compass.pipeline.graph import _vault_url_set


def _write_note(path, url_field: str, url: str):
    post = frontmatter.Post(content="body", **{url_field: url, "type": "test"})
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")


def test_returns_empty_when_no_dirs(temp_vault):
    # temp_vault creates jobs/ but not jobs-archive/ or hitl-pending/
    assert _vault_url_set() == set()


def test_picks_up_jobs(temp_vault):
    _write_note(temp_vault / "jobs" / "a.md", "url", "https://example.com/a")
    _write_note(temp_vault / "jobs" / "b.md", "url", "https://example.com/b")
    urls = _vault_url_set()
    assert "https://example.com/a" in urls
    assert "https://example.com/b" in urls


def test_picks_up_archive(temp_vault):
    archive = temp_vault / "jobs-archive"
    archive.mkdir(parents=True, exist_ok=True)
    _write_note(archive / "old.md", "url", "https://example.com/old")
    urls = _vault_url_set()
    assert "https://example.com/old" in urls


def test_picks_up_hitl_pending_via_job_url_field(temp_vault):
    """HiTL pending notes use `job_url`, not `url`. Make sure dedup reads
    the right field."""
    hitl = temp_vault / "hitl-pending"
    hitl.mkdir(parents=True, exist_ok=True)
    _write_note(hitl / "pending.md", "job_url", "https://example.com/pending")
    urls = _vault_url_set()
    assert "https://example.com/pending" in urls


def test_dedups_normalize_url_variants(temp_vault):
    """Two URLs that normalize-equal should appear once in the set."""
    _write_note(temp_vault / "jobs" / "a.md", "url", "https://Example.com/X/")
    archive = temp_vault / "jobs-archive"
    archive.mkdir(parents=True, exist_ok=True)
    _write_note(archive / "b.md", "url", "https://example.com/X?utm_source=foo")
    urls = _vault_url_set()
    assert len(urls) == 1


def test_handles_missing_url_field(temp_vault):
    _write_note(temp_vault / "jobs" / "no_url.md", "type", "broken")
    urls = _vault_url_set()
    assert urls == set()


def test_handles_malformed_file(temp_vault, caplog):
    bad = temp_vault / "jobs" / "bad.md"
    bad.write_text("---\nbroken: yaml: : :\n---\n", encoding="utf-8")
    # Should not raise — logged-and-continue is the contract
    urls = _vault_url_set()
    assert urls == set()
