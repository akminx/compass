"""Regression test for B6 fix: out-of-scope JobNotes must not contribute to gap plan."""
from __future__ import annotations
from pathlib import Path
import frontmatter
import pytest


def _write_job(vault: Path, name: str, role_family: str, required: list[str], score: float) -> None:
    (vault / "jobs").mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(
        "# Test job\n",
        company="Test",
        title=f"Test Title {name}",
        url=f"https://x/{name}",
        source="manual",
        date_found="2026-05-19",
        match_score=score,
        score_reasoning="t",
        seniority="mid",
        role_family=role_family,
        tier="apply-now",
        skills_required=required,
        skills_nice_to_have=[],
        skills_matched=[],
        skills_missing=required,
        jd_summary="t",
    )
    (vault / "jobs" / f"{name}.md").write_text(frontmatter.dumps(post), encoding="utf-8")


def test_gap_aggregator_skips_out_of_scope_jobs(temp_vault):
    from compass.analysis import gap_aggregator

    _write_job(temp_vault, "inscope", "agent-engineer", ["Python"], score=4.0)
    _write_job(temp_vault, "outofscope", "out-of-scope", ["TypeScript"], score=4.0)

    jobs = gap_aggregator.load_jobs()
    titles = sorted(j.title for j in jobs)
    assert titles == ["Test Title inscope"]  # out-of-scope job excluded
