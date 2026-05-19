"""P2 Obsidian leverage: gap_aggregator writes a `## Jobs requiring this skill`
block into each SkillNote body so Linked Mentions + Dataview can surface the
reverse mapping (every JD asking for Python, sorted by match_score).

The block preserves existing body content above it (seed notes carry category
descriptions like `_Category: mcp · Tier-2 demand: highest_` that must not be
clobbered) and replaces itself on re-runs (idempotent).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import frontmatter

if TYPE_CHECKING:
    from pathlib import Path


def _seed_skill(vault: Path, canonical: str, category: str, body_extra: str = "") -> None:
    (vault / "skills").mkdir(parents=True, exist_ok=True)
    safe = canonical.replace(" ", "_").replace("/", "_")
    text = (
        "---\n"
        "type: skill\n"
        f"skill: {canonical}\n"
        f"category: {category}\n"
        "appears_in_jobs: 0\n"
        "my_level: 0\n"
        "---\n"
        f"# {canonical}\n"
        f"{body_extra}"
    )
    (vault / "skills" / f"{safe}.md").write_text(text, encoding="utf-8")


def _seed_job(
    vault: Path,
    name: str,
    *,
    company: str,
    title: str,
    required: list[str],
    score: float,
    tier: str = "apply-now",
) -> None:
    (vault / "jobs").mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(
        "# job\n",
        company=company,
        title=title,
        url=f"https://x/{name}",
        source="manual",
        date_found="2026-05-19",
        match_score=score,
        score_reasoning="t",
        role_family="agent-engineer",
        tier=tier,
        skills_required=required,
        skills_nice_to_have=[],
        skills_matched=[],
        skills_missing=required,
        jd_summary="t",
    )
    (vault / "jobs" / f"{name}.md").write_text(frontmatter.dumps(post), encoding="utf-8")


def test_skill_backlinks_block_added_to_skillnote(temp_vault):
    from compass.analysis import gap_aggregator

    _seed_skill(temp_vault, "Python", "language", body_extra="_Category: language_\n")
    _seed_job(
        temp_vault,
        "sierra",
        company="Sierra",
        title="Agent Eng",
        required=["Python"],
        score=4.0,
    )
    _seed_job(
        temp_vault,
        "decagon",
        company="Decagon",
        title="MTS",
        required=["Python"],
        score=3.0,
    )

    gap_aggregator.regenerate(write=True)

    body = (temp_vault / "skills" / "Python.md").read_text()
    assert "## Jobs requiring this skill" in body
    # Existing description preserved
    assert "_Category: language_" in body
    # Both jobs linked, with company — title display
    assert "[[sierra|Sierra — Agent Eng]]" in body
    assert "[[decagon|Decagon — MTS]]" in body
    # Sierra (score 4.0) appears before Decagon (score 3.0)
    assert body.index("Sierra — Agent Eng") < body.index("Decagon — MTS")
    # Score + tier rendered
    assert "score 4.0" in body
    assert "apply-now" in body


def test_skill_backlinks_idempotent_on_rerun(temp_vault):
    """Two regenerate calls must not duplicate the block."""
    from compass.analysis import gap_aggregator

    _seed_skill(temp_vault, "Python", "language")
    _seed_job(
        temp_vault,
        "sierra",
        company="Sierra",
        title="Agent Eng",
        required=["Python"],
        score=4.0,
    )
    gap_aggregator.regenerate(write=True)
    body1 = (temp_vault / "skills" / "Python.md").read_text()
    gap_aggregator.regenerate(write=True)
    body2 = (temp_vault / "skills" / "Python.md").read_text()

    assert body1 == body2
    assert body2.count("## Jobs requiring this skill") == 1


def test_skill_backlinks_removed_when_no_jobs_reference_skill(temp_vault):
    """If a skill's last referencing job is removed, the block goes away."""
    from compass.analysis import gap_aggregator

    _seed_skill(temp_vault, "Python", "language")
    _seed_job(
        temp_vault,
        "sierra",
        company="Sierra",
        title="Agent Eng",
        required=["Python"],
        score=4.0,
    )
    gap_aggregator.regenerate(write=True)
    assert "## Jobs requiring this skill" in (temp_vault / "skills" / "Python.md").read_text()

    # Remove the only job
    (temp_vault / "jobs" / "sierra.md").unlink()
    gap_aggregator.regenerate(write=True)
    assert "## Jobs requiring this skill" not in (temp_vault / "skills" / "Python.md").read_text()
