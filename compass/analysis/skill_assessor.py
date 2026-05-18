"""
Skill assessor — regrades a skill against its evidence URIs.

Uses an adversarial-grader prompt + Pydantic AI for structured output.
Asymmetric promotion: jumping 2+ levels requires HiTL approval.

Run as a node in the pipeline (after vault_write) OR as a Modal cron OR as the
MCP tool `assess_skills(scope=[...])`.

Reads:
- compass-vault/skills/<Skill>.md     (evidence URIs, current level, grade_override)
- compass-vault/_meta/skill-taxonomy.md (rubric, canonical name)
- learning-vault://...                 (evidence file content via learning_bridge)

Writes:
- compass-vault/skills/<Skill>.md      (my_level, last_assessed, assessor_notes)
- compass-vault/_profile/skill-inventory.md (regenerated table)
- compass-vault/_meta/agent-log.md     (one line per regrade)
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import TYPE_CHECKING

import yaml

from compass.config import (
    AGENT_LOG_PATH,
    SKILL_INVENTORY_PATH,
    VAULT_PATH,
)
from compass.vault.learning_bridge import EvidenceArtifact, resolve_many
from compass.vault.schemas import SkillAssessment, SkillLevel
from compass.vault.taxonomy import all_canonicals

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic_ai import Agent

SKEPTICAL_GRADER_SYSTEM_PROMPT = """\
You are a senior hiring manager who has interviewed 500 engineering candidates for
agentic-AI roles. You assume the candidate is overstating their experience.

Apply this rubric strictly. Demand specific artifacts; conceptual notes alone cap at level 1.

Level rubric:
  0 - No exposure.
  1 - Tutorial-level: course notes, "hello world", or a read paper.
  2 - Applied in a personal project. Repo or vault note showing real use, no users beyond self.
  3 - Shipped. Deployed, evals exist, OR used by people other than the candidate.
  4 - Production-grade. Shipped WITH observability + cost tracking + recovered from a real failure.
  5 - Authority. Taught it, merged upstream PR, or fixed a non-trivial bug in the library itself.

Rules:
1. Cite specific evidence URIs (from the provided list) that support your grade. If you cannot
   cite at least one artifact for a grade of 3+, lower the grade.
2. Conceptual evidence (course notes, blog posts, "I read the docs") is capped at level 1.
3. To award level 4 you must see (a) shipped artifact + (b) observability evidence
   (traces, metrics, eval results) + (c) a failure-and-recovery story.
4. To award level 5, demand evidence of teaching, merged upstream contributions, or library bug fixes.
5. Before committing to a grade, write a `dissenting_view` arguing the OPPOSITE case.
   If the dissent is strong, lower the grade by 1.
6. Output a confidence: low / medium / high. Low confidence => requires_hitl = true.
7. If proposed_level differs from current_level by 2+ in either direction, set requires_hitl = true.

You will receive: skill name, current level, list of evidence artifacts (URI + snippet + kind + last_modified).
Output a SkillAssessment object.
"""


# ── helpers ──────────────────────────────────────────────────────────────────


def _parse_frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def _write_frontmatter(path: Path, fm: dict, body: str) -> None:
    yaml_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    path.write_text(f"---\n{yaml_text}\n---\n{body}", encoding="utf-8")


def _load_skill_note(canonical: str) -> tuple[Path, dict, str] | None:
    path = VAULT_PATH / "skills" / f"{canonical}.md"
    if not path.exists():
        return None
    fm, body = _parse_frontmatter(path)
    return path, fm, body


def _log(line: str) -> None:
    AGENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AGENT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")


# ── agent ────────────────────────────────────────────────────────────────────


def _get_agent() -> Agent:
    """Build the assessor agent via the shared OpenRouter factory.

    Reads ASSESSOR_MODEL at call time (matches the no-cache contract in
    compass.llm — env changes pick up without restart).
    """
    from compass.llm import make_agent

    return make_agent(
        "assessor",
        output_type=SkillAssessment,
        system_prompt=SKEPTICAL_GRADER_SYSTEM_PROMPT,
    )


def _format_evidence_block(artifacts: list[EvidenceArtifact]) -> str:
    if not artifacts:
        return "(no evidence artifacts provided)"
    blocks = []
    for a in artifacts:
        blocks.append(
            f"URI: {a.uri}\n"
            f"Kind: {a.kind}\n"
            f"Last modified: {a.last_modified.isoformat(timespec='minutes')}\n"
            f"Snippet:\n{a.snippet}\n"
        )
    return "\n---\n".join(blocks)


# ── main entrypoint ──────────────────────────────────────────────────────────


async def assess_one(canonical: str) -> SkillAssessment | None:
    """Assess a single skill. Returns None if skill note doesn't exist."""
    loaded = _load_skill_note(canonical)
    if loaded is None:
        return None
    _path, fm, _body = loaded

    # Human-locked grade — short-circuit.
    if fm.get("grade_override") is not None:
        return SkillAssessment(
            skill=canonical,
            proposed_level=fm["grade_override"],
            current_level=fm.get("my_level", 0),
            confidence="high",
            cited_evidence=[],
            reasoning="grade_override set by human; assessor skipped.",
            dissenting_view="",
            requires_hitl=False,
        )

    current_level: SkillLevel = fm.get("my_level", 0)
    evidence_uris: list[str] = fm.get("evidence", []) or []
    artifacts = resolve_many(evidence_uris)

    prompt = (
        f"Skill: {canonical}\n"
        f"Category: {fm.get('category', 'unknown')}\n"
        f"Current level: {current_level}\n\n"
        f"Evidence artifacts:\n{_format_evidence_block(artifacts)}\n"
    )

    result = await _get_agent().run(prompt)
    assessment: SkillAssessment = result.output

    if abs(assessment.proposed_level - current_level) >= 2:
        assessment.requires_hitl = True

    return assessment


def _apply(assessment: SkillAssessment) -> None:
    loaded = _load_skill_note(assessment.skill)
    if loaded is None:
        return
    path, fm, body = loaded
    if assessment.requires_hitl:
        _log(
            f"[{datetime.now().isoformat(timespec='seconds')}] assess_skills HITL "
            f"{assessment.skill} {fm.get('my_level', 0)}->{assessment.proposed_level} "
            f"conf={assessment.confidence} (awaiting human approval)"
        )
        return
    fm["my_level"] = assessment.proposed_level
    fm["last_assessed"] = datetime.now().isoformat(timespec="seconds")
    body = _append_assessor_section(body, assessment)
    _write_frontmatter(path, fm, body)
    _log(
        f"[{datetime.now().isoformat(timespec='seconds')}] assess_skills APPLY "
        f"{assessment.skill} -> level {assessment.proposed_level} conf={assessment.confidence}"
    )


def _append_assessor_section(body: str, a: SkillAssessment) -> str:
    section = (
        f"\n## Latest assessment notes ({datetime.now().date()})\n"
        f"- Proposed level: {a.proposed_level} (confidence: {a.confidence})\n"
        f"- Reasoning: {a.reasoning}\n"
        f"- Dissenting view: {a.dissenting_view}\n"
        f"- Cited evidence: {', '.join(a.cited_evidence) or 'none'}\n"
    )
    # Replace existing "Latest assessment notes" section if present
    new_body = re.sub(
        r"\n## Latest assessment notes.*?(?=\n## |\Z)",
        section,
        body,
        count=1,
        flags=re.DOTALL,
    )
    if new_body == body:
        new_body = body.rstrip() + "\n" + section
    return new_body


async def assess_many(scope: list[str] | None = None) -> list[SkillAssessment]:
    """Assess all skills in scope (or every canonical skill if None)."""
    targets = scope or all_canonicals()
    results: list[SkillAssessment] = []
    for canonical in targets:
        a = await assess_one(canonical)
        if a is None:
            continue
        _apply(a)
        results.append(a)
    _regenerate_inventory_table()
    return results


def _regenerate_inventory_table() -> None:
    """Rewrite the table in skill-inventory.md from current skill note levels."""
    if not SKILL_INVENTORY_PATH.exists():
        return
    skills_dir = VAULT_PATH / "skills"
    levels: dict[str, dict] = {}
    for f in skills_dir.glob("*.md"):
        fm, _ = _parse_frontmatter(f)
        if fm.get("skill"):
            levels[fm["skill"]] = fm

    text = SKILL_INVENTORY_PATH.read_text(encoding="utf-8")
    # Append a generated section at the bottom — non-destructive of human edits above.
    marker = "<!-- ASSESSOR-GENERATED-BELOW -->"
    base = text.split(marker)[0].rstrip()
    rows = "\n".join(
        f"| {name} | {fm.get('my_level', 0)} | {fm.get('category', '')} | "
        f"{fm.get('last_assessed', '')} |"
        for name, fm in sorted(levels.items())
    )
    generated = (
        f"\n\n{marker}\n\n## Assessor-current grades (generated {datetime.now().isoformat(timespec='minutes')})\n\n"
        f"| Skill | Level | Category | Last assessed |\n|---|---|---|---|\n{rows}\n"
    )
    SKILL_INVENTORY_PATH.write_text(base + generated, encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(assess_many())
