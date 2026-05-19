"""
Gap aggregator — turns scored jobs into a ranked, weighted study plan.

Reads:
- compass-vault/jobs/*.md            (every scored job in the vault)
- compass-vault/skills/*.md          (current skill levels)
- compass-vault/_profile/preferences.md  (tier weights)

Writes:
- compass-vault/study-plans/master-gap-plan.md  (regenerated every run)
- compass-vault/skills/<skill>.md    (updates appears_in_jobs, tier_demand, gap_score)

Run after every pipeline batch. Also exposed as MCP tool `regenerate_gap_plan`.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import yaml

from compass.config import (
    DEFAULT_TIER_WEIGHTS,
    MASTER_GAP_PLAN_PATH,
    PREFERENCES_PATH,
    VAULT_PATH,
)
from compass.vault.schemas import GapPlanEntry, SkillLevel, TierDemand
from compass.vault.taxonomy import all_canonicals

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class JobSummary:
    file: Path
    company: str
    title: str
    match_score: float
    tier: str
    skills_required: list[str]
    skills_nice_to_have: list[str]
    skills_missing: list[str]


# ── loaders ──────────────────────────────────────────────────────────────────


def _parse_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    return yaml.safe_load(m.group(1)) or {}


def load_jobs() -> list[JobSummary]:
    out: list[JobSummary] = []
    jobs_dir = VAULT_PATH / "jobs"
    if not jobs_dir.exists():
        return out
    for f in jobs_dir.glob("*.md"):
        fm = _parse_frontmatter(f)
        if not fm:
            continue
        # Skip out-of-scope JobNotes — they shouldn't influence the gap plan.
        # role_family is set once at intake; if a stale entry's title would
        # now classify as out-of-scope, the migration script handles that.
        if fm.get("role_family") == "out-of-scope":
            continue
        out.append(
            JobSummary(
                file=f,
                company=fm.get("company", ""),
                title=fm.get("title", ""),
                match_score=float(fm.get("match_score", 0)),
                tier=fm.get("tier", "unknown"),
                skills_required=fm.get("skills_required", []) or [],
                skills_nice_to_have=fm.get("skills_nice_to_have", []) or [],
                skills_missing=fm.get("skills_missing", []) or [],
            )
        )
    return out


def load_skill_levels() -> dict[str, SkillLevel]:
    out: dict[str, SkillLevel] = {}
    skills_dir = VAULT_PATH / "skills"
    if not skills_dir.exists():
        return out
    for f in skills_dir.glob("*.md"):
        fm = _parse_frontmatter(f)
        canonical = fm.get("skill")
        if canonical:
            out[canonical] = int(fm.get("my_level", 0))  # type: ignore[assignment]
    return out


def load_tier_weights() -> dict[str, float]:
    """Parse tier_weights from preferences.md. Falls back to DEFAULT_TIER_WEIGHTS."""
    if not PREFERENCES_PATH.exists():
        return dict(DEFAULT_TIER_WEIGHTS)
    text = PREFERENCES_PATH.read_text(encoding="utf-8")
    block = re.search(r"tier_weights:\s*\n((?:\s+[\w\-]+:\s*[\d.]+\s*\n?)+)", text)
    if not block:
        return dict(DEFAULT_TIER_WEIGHTS)
    weights = dict(DEFAULT_TIER_WEIGHTS)
    for line in block.group(1).splitlines():
        m = re.match(r"\s+([\w\-]+):\s*([\d.]+)", line)
        if m:
            weights[m.group(1)] = float(m.group(2))
    return weights


# ── aggregation ──────────────────────────────────────────────────────────────


def aggregate(
    jobs: list[JobSummary],
    skill_levels: dict[str, SkillLevel],
    tier_weights: dict[str, float],
) -> list[GapPlanEntry]:
    from compass.vault.taxonomy import normalize

    appears: dict[str, int] = defaultdict(int)
    tier_breakdown: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    gap_accum: dict[str, float] = defaultdict(float)

    for job in jobs:
        weight = tier_weights.get(job.tier, tier_weights.get("unknown", 0.5))
        # Below 1.0 the rubric says "wrong field entirely" or "fundamental
        # skill gaps" — these jobs shouldn't contribute to gap math even at
        # 10% weight. Cap at 5.0 to defend against out-of-range LLM output
        # (Pydantic now constrains JobScore.score to [0,5] but defense is cheap).
        clamped = max(0.0, min(job.match_score, 5.0))
        score_factor = 0.0 if clamped < 1.0 else clamped / 5.0
        # Required skills count at full weight; nice-to-haves at half (they're
        # signal of market direction but not job-required gaps).
        seen_for_this_job: set[str] = set()
        for raw, source_weight in (
            *((s, 1.0) for s in job.skills_required),
            *((s, 0.5) for s in job.skills_nice_to_have),
        ):
            canon = normalize(raw)
            if not canon or canon in seen_for_this_job:
                continue
            seen_for_this_job.add(canon)
            appears[canon] += 1
            tier_breakdown[canon][job.tier] += 1
            if skill_levels.get(canon, 0) < 3:  # only count as gap if you're below "shipped"
                gap_accum[canon] += weight * score_factor * source_weight

    entries: list[GapPlanEntry] = []
    for canon in all_canonicals():
        if appears[canon] == 0:
            continue
        td = TierDemand(
            **{
                "apply-now": tier_breakdown[canon].get("apply-now", 0),
                "6-month": tier_breakdown[canon].get("6-month", 0),
                "stretch": tier_breakdown[canon].get("stretch", 0),
            }
        )
        entries.append(
            GapPlanEntry(
                skill=canon,
                your_level=skill_levels.get(canon, 0),  # type: ignore[arg-type]
                appears_in_jobs=appears[canon],
                tier_demand=td,
                gap_score=round(gap_accum[canon], 2),
                suggested_next_step=_suggest_next_step(canon, skill_levels.get(canon, 0)),
                cheap_win=_is_cheap_win(canon, skill_levels.get(canon, 0)),
            )
        )
    entries.sort(key=lambda e: e.gap_score, reverse=True)
    return entries


# ── heuristics ───────────────────────────────────────────────────────────────

_CHEAP_WIN_CANDIDATES = {
    "Temporal",
    "Stagehand",
    "Playwright",
    "Guardrails",
    "Prompt caching",
    "Response streaming",
    "Re-ranking",
    "pgvector",
    "BigQuery",
}


def _is_cheap_win(canonical: str, current_level: int) -> bool:
    return canonical in _CHEAP_WIN_CANDIDATES and current_level <= 2


def _suggest_next_step(canonical: str, current_level: int) -> str:
    if current_level == 0:
        return f"Read 1 conceptual doc + run a hello-world for {canonical}."
    if current_level == 1:
        return f"Use {canonical} in a personal project. Cite the file as evidence."
    if current_level == 2:
        return f"Ship {canonical} usage somewhere observable (eval, trace, or external user)."
    if current_level == 3:
        return f"Add observability + a documented failure recovery for {canonical}."
    return "Maintained — keep evidence fresh."


# ── writer ───────────────────────────────────────────────────────────────────


def render_master_plan(entries: list[GapPlanEntry], jobs_n: int) -> str:
    now = datetime.now().isoformat(timespec="seconds")
    top = entries[:10]
    cheap = [e for e in entries if e.cheap_win][:5]
    rows = "\n".join(
        f"| {i + 1} | {e.skill} | {e.your_level} | {e.gap_score} | {e.appears_in_jobs} | "
        f"apply-now: {e.tier_demand.apply_now} · 6m: {e.tier_demand.six_month} · stretch: {e.tier_demand.stretch} "
        f"| {e.suggested_next_step} |"
        for i, e in enumerate(top)
    )
    cheap_rows = (
        "\n".join(
            f"- **{e.skill}** (level {e.your_level}) — {e.suggested_next_step}" for e in cheap
        )
        or "_none right now_"
    )
    return f"""---
type: study-plan
scope: master
generated_by: gap_aggregator
last_generated: {now}
jobs_considered: {jobs_n}
---

# Master Gap Plan

> Auto-regenerated. Edits will be overwritten — make notes in `learning-vault/roadmap/NOW.md`.

## Top 10 gaps (weighted)

| Rank | Skill | Your level | Gap score | Jobs requiring | Tier breakdown | Suggested next step |
|---|---|---|---|---|---|---|
{rows}

_Gap score = Σ (jobs_requiring × match_score × tier_weight). Tier weights from `_profile/preferences.md`._

## Cheap wins (adjacent to existing projects)

{cheap_rows}

## All tracked skills (full list)

{len(entries)} skills appearing in at least one scored JD. See `compass-vault/skills/` for per-skill details.
"""


def regenerate(write: bool = True) -> tuple[list[GapPlanEntry], str]:
    jobs = load_jobs()
    levels = load_skill_levels()
    weights = load_tier_weights()
    entries = aggregate(jobs, levels, weights)
    rendered = render_master_plan(entries, jobs_n=len(jobs))
    if write:
        _sync_skill_counters(entries)
        _sync_skill_backlinks(jobs)
        _sync_company_counters(jobs)
        MASTER_GAP_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
        MASTER_GAP_PLAN_PATH.write_text(rendered, encoding="utf-8")
    return entries, rendered


_SKILL_BACKLINKS_HEADING = "## Jobs requiring this skill"
_SKILL_BACKLINKS_BLOCK = re.compile(
    r"(?ms)^## Jobs requiring this skill\s*\n.*?(?=^## |\Z)"
)


def _sync_skill_backlinks(jobs: list[JobSummary]) -> None:
    """Write a `## Jobs requiring this skill` block into each SkillNote body
    that lists every JobNote whose required/nice-to-have skills include the
    canonical name. Mirrors P2 of OBSIDIAN_LEVERAGE.md.

    Preserves any human-edited content above the block (skill notes are seeded
    with category headers + brief descriptions; we don't want to clobber that).
    Replaces an existing block if present, appends otherwise.

    Jobs are ordered by match_score DESC so the strongest fits sit at the top
    of each SkillNote.
    """
    from collections import defaultdict

    from compass.vault.taxonomy import normalize

    skills_dir = VAULT_PATH / "skills"
    if not skills_dir.exists():
        return

    by_skill: dict[str, list[JobSummary]] = defaultdict(list)
    for job in jobs:
        seen: set[str] = set()
        for raw in (*job.skills_required, *job.skills_nice_to_have):
            canon = normalize(raw)
            if not canon or canon in seen:
                continue
            seen.add(canon)
            by_skill[canon].append(job)

    for path in skills_dir.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        m = re.match(r"^(---\n.*?\n---\n)(.*)", text, re.DOTALL)
        if not m:
            continue
        head, body = m.group(1), m.group(2)
        # Resolve canonical from frontmatter
        fm_m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        if not fm_m:
            continue
        fm = yaml.safe_load(fm_m.group(1)) or {}
        canonical = fm.get("skill")
        if not canonical:
            continue

        bl_jobs = sorted(
            by_skill.get(canonical, []),
            key=lambda j: (-j.match_score, j.company, j.title),
        )
        rendered = _render_skill_backlinks(bl_jobs)

        if _SKILL_BACKLINKS_BLOCK.search(body):
            replacement = rendered + "\n" if rendered else ""
            new_body = _SKILL_BACKLINKS_BLOCK.sub(replacement, body, count=1)
            new_body = re.sub(r"\n{3,}", "\n\n", new_body)
        elif rendered:
            new_body = body.rstrip() + "\n\n" + rendered + "\n"
        else:
            new_body = body

        if new_body != body:
            path.write_text(head + new_body, encoding="utf-8")


def _render_skill_backlinks(jobs: list[JobSummary]) -> str:
    if not jobs:
        return ""
    lines = [_SKILL_BACKLINKS_HEADING, ""]
    for j in jobs:
        stem = j.file.stem  # filename minus .md — matches Obsidian's wikilink target
        display = f"{j.company} — {j.title}"
        score = f"score {j.match_score:.1f}"
        tier = j.tier or "unknown"
        lines.append(f"- [[{stem}|{display}]] · {score} · {tier}")
    return "\n".join(lines) + "\n"


def _sync_company_counters(jobs: list[JobSummary]) -> None:
    """Rewrite `roles_seen` on each `companies/*.md` to match the actual JobNote
    count for that company. Same pattern as `_sync_skill_counters` — treat the
    counter as derived data instead of an incrementing field that races under
    parallel writes (MAX_CONCURRENT_JOBS=5 jobs at once for the same company
    would lose increments without a file lock).
    """
    from collections import Counter

    import yaml

    companies_dir = VAULT_PATH / "companies"
    if not companies_dir.exists():
        return

    counts = Counter(j.company for j in jobs if j.company)

    for path in companies_dir.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        m = re.match(r"^(---\n)(.*?)(\n---\n)(.*)", text, re.DOTALL)
        if not m:
            continue
        fm = yaml.safe_load(m.group(2)) or {}
        company = fm.get("company")
        if not company:
            continue
        new_count = counts.get(company, 0)
        if fm.get("roles_seen") == new_count:
            continue
        fm["roles_seen"] = new_count
        new_fm = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
        path.write_text(f"---\n{new_fm}\n---\n{m.group(4)}", encoding="utf-8")


def _sync_skill_counters(entries: list[GapPlanEntry]) -> None:
    """Rewrite `appears_in_jobs` on each `skills/*.md` so the counter matches
    the actual JobNote frontmatter (the source of truth).

    Previously `update_skill_note` accumulated on every pipeline run — even
    re-writes of the same JobNote — causing drift. Now we treat the counter
    as derived data and recompute from JobNotes at gap_aggregator time.

    Creates missing skill notes for canonicals that appear in JobNotes but
    weren't yet seeded by scripts/seed_skills.py. Skills not appearing in any
    JobNote get appears_in_jobs=0 (resets stale data from previous runs).
    """
    import yaml

    from compass.vault.taxonomy import category_for

    skills_dir = VAULT_PATH / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    by_canonical = {e.skill: e for e in entries}

    # Update existing skill notes
    seen_canonicals: set[str] = set()
    for path in skills_dir.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        m = re.match(r"^(---\n)(.*?)(\n---\n)(.*)", text, re.DOTALL)
        if not m:
            continue
        fm = yaml.safe_load(m.group(2)) or {}
        canonical = fm.get("skill")
        if not canonical:
            continue
        seen_canonicals.add(canonical)
        entry = by_canonical.get(canonical)
        new_count = entry.appears_in_jobs if entry else 0
        if fm.get("appears_in_jobs") == new_count:
            continue
        fm["appears_in_jobs"] = new_count
        new_fm = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
        path.write_text(f"---\n{new_fm}\n---\n{m.group(4)}", encoding="utf-8")

    # Create skill notes for canonicals seen in JobNotes but missing on disk
    safe_filename = re.compile(r"[^\w\-.]+")
    for canonical, entry in by_canonical.items():
        if canonical in seen_canonicals:
            continue
        category = category_for(canonical) or "language"
        filename = safe_filename.sub("_", canonical).strip("_") + ".md"
        new_path = skills_dir / filename
        stub_fm = {
            "type": "skill",
            "skill": canonical,
            "category": category,
            "appears_in_jobs": entry.appears_in_jobs,
            "my_level": 0,
        }
        yaml_text = yaml.safe_dump(stub_fm, sort_keys=False, allow_unicode=True).strip()
        new_path.write_text(f"---\n{yaml_text}\n---\n# {canonical}\n", encoding="utf-8")


if __name__ == "__main__":
    entries, _ = regenerate()
    print(f"Wrote {MASTER_GAP_PLAN_PATH} with {len(entries)} skills, top 10 gaps:")
    for e in entries[:10]:
        print(
            f"  {e.gap_score:>6.2f}  {e.skill} (level {e.your_level}, in {e.appears_in_jobs} JDs)"
        )
