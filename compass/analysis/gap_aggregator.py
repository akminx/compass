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
from pathlib import Path

import yaml

from compass.config import (
    DEFAULT_TIER_WEIGHTS,
    MASTER_GAP_PLAN_PATH,
    PREFERENCES_PATH,
    VAULT_PATH,
)
from compass.vault.schemas import GapPlanEntry, SkillLevel, TierDemand
from compass.vault.taxonomy import all_canonicals, load_taxonomy


@dataclass
class JobSummary:
    file: Path
    company: str
    title: str
    match_score: float
    tier: str
    skills_required: list[str]
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
        out.append(JobSummary(
            file=f,
            company=fm.get("company", ""),
            title=fm.get("title", ""),
            match_score=float(fm.get("match_score", 0)),
            tier=fm.get("tier", "unknown"),
            skills_required=fm.get("skills_required", []) or [],
            skills_missing=fm.get("skills_missing", []) or [],
        ))
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
        score_factor = max(job.match_score / 5.0, 0.1)  # don't zero out low-match jobs entirely
        for raw in job.skills_required:
            canon = normalize(raw)
            if not canon:
                continue
            appears[canon] += 1
            tier_breakdown[canon][job.tier] += 1
            if skill_levels.get(canon, 0) < 3:  # only count as gap if you're below "shipped"
                gap_accum[canon] += weight * score_factor

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
        entries.append(GapPlanEntry(
            skill=canon,
            your_level=skill_levels.get(canon, 0),  # type: ignore[arg-type]
            appears_in_jobs=appears[canon],
            tier_demand=td,
            gap_score=round(gap_accum[canon], 2),
            suggested_next_step=_suggest_next_step(canon, skill_levels.get(canon, 0)),
            cheap_win=_is_cheap_win(canon, skill_levels.get(canon, 0)),
        ))
    entries.sort(key=lambda e: e.gap_score, reverse=True)
    return entries


# ── heuristics ───────────────────────────────────────────────────────────────

_CHEAP_WIN_CANDIDATES = {
    "Temporal", "Stagehand", "Playwright", "Guardrails", "Prompt caching",
    "Response streaming", "Re-ranking", "pgvector", "BigQuery",
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
    return f"Maintained — keep evidence fresh."


# ── writer ───────────────────────────────────────────────────────────────────

def render_master_plan(entries: list[GapPlanEntry], jobs_n: int) -> str:
    now = datetime.now().isoformat(timespec="seconds")
    top = entries[:10]
    cheap = [e for e in entries if e.cheap_win][:5]
    rows = "\n".join(
        f"| {i+1} | {e.skill} | {e.your_level} | {e.gap_score} | {e.appears_in_jobs} | "
        f"apply-now: {e.tier_demand.apply_now} · 6m: {e.tier_demand.six_month} · stretch: {e.tier_demand.stretch} "
        f"| {e.suggested_next_step} |"
        for i, e in enumerate(top)
    )
    cheap_rows = "\n".join(f"- **{e.skill}** (level {e.your_level}) — {e.suggested_next_step}" for e in cheap) or "_none right now_"
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
        MASTER_GAP_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
        MASTER_GAP_PLAN_PATH.write_text(rendered, encoding="utf-8")
    return entries, rendered


if __name__ == "__main__":
    entries, _ = regenerate()
    print(f"Wrote {MASTER_GAP_PLAN_PATH} with {len(entries)} skills, top 10 gaps:")
    for e in entries[:10]:
        print(f"  {e.gap_score:>6.2f}  {e.skill} (level {e.your_level}, in {e.appears_in_jobs} JDs)")
