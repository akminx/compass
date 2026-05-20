"""
Skill taxonomy loader + normalizer.

Reads compass-vault/_meta/skill-taxonomy.md, builds an index of canonical
skill -> {category, synonyms, tier_demand_baseline}, and exposes a `normalize()`
function that maps any string (from JD extraction) to a canonical skill or None.

The taxonomy is the spine of every downstream module — extract_node, score_node,
gap_aggregator, and skill_assessor all normalize through here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING

from compass.config import TAXONOMY_PATH

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class CanonicalSkill:
    name: str
    category: str
    synonyms: list[str] = field(default_factory=list)
    tier2_demand: str = "low"  # high | medium | low | highest
    tier3_demand: str = "low"


_CATEGORY_HEADERS: dict[str, str] = {
    "Languages": "language",
    "LLM APIs & SDKs": "llm-api",
    "Agent Frameworks": "agent-framework",
    "MCP (Model Context Protocol)": "mcp",
    "Prompt & Context Engineering": "prompt",
    "RAG": "rag",
    "Vector Databases": "vector-db",
    "Evals": "evals",
    "Observability": "observability",
    "Durable Execution / Workflow": "durable-execution",
    "Multi-Agent & Coordination": "multi-agent",
    "Human-in-the-Loop": "hitl",
    "Production Concerns": "production",
    "Cloud": "cloud",
    "Deployment": "deployment",
    "Browser / Computer Use": "browser-use",
    "Voice Stack (optional — skip unless voice-targeting)": "voice",
    "Fine-Tuning (awareness only)": "fine-tuning",
}


def _norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


_DEMAND_TOKENS = {"low", "medium", "high", "highest"}


@lru_cache(maxsize=1)
def load_taxonomy(path: Path | None = None) -> dict[str, CanonicalSkill]:
    """Parse the taxonomy markdown into a {canonical_name: CanonicalSkill} dict.

    Returns an empty dict if the taxonomy file is missing — callers should
    handle a missing canonical gracefully (e.g., `category_for()` returning None).

    Some sections of skill-taxonomy.md use 3-column tables (Canonical | Tier-2 |
    Tier-3) instead of 4 (Canonical | Synonyms | Tier-2 | Tier-3). The header
    row sets `synonyms_col_index` per-section so we don't misread tier columns
    as synonyms. Belt-and-suspenders: demand-level tokens are also filtered
    from any synonyms list.
    """
    path = path or TAXONOMY_PATH
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")

    result: dict[str, CanonicalSkill] = {}
    current_category: str | None = None
    synonyms_col_index: int | None = None  # set by each section's header row

    for line in text.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("## "):
            header = line_stripped[3:].strip()
            current_category = _CATEGORY_HEADERS.get(header)
            synonyms_col_index = None  # re-detected on next header row
            continue
        if current_category is None or not line_stripped.startswith("|"):
            continue
        # parse table row
        cells = [c.strip() for c in line_stripped.split("|")[1:-1]]
        if not cells:
            continue
        if all(set(c) <= {"-", ":", " "} for c in cells):
            continue
        # Header row — figure out which column (if any) holds synonyms
        if cells[0].lower() == "canonical":
            lowered = [c.lower() for c in cells]
            synonyms_col_index = lowered.index("synonyms") if "synonyms" in lowered else None
            continue
        canonical = cells[0]
        synonyms: list[str] = []
        if synonyms_col_index is not None and len(cells) > synonyms_col_index:
            raw_syn = cells[synonyms_col_index]
            synonyms = [s.strip() for s in raw_syn.split(",") if s.strip()]
            # Guard against demand-level tokens leaking into synonyms even when
            # the header detection misfires.
            synonyms = [s for s in synonyms if s.lower() not in _DEMAND_TOKENS]
        # Tier columns: last two cells in the row (after canonical/synonyms)
        tier2 = cells[-2] if len(cells) >= 3 else "low"
        tier3 = cells[-1] if len(cells) >= 2 else "low"
        result[canonical] = CanonicalSkill(
            name=canonical,
            category=current_category,
            synonyms=synonyms,
            tier2_demand=_clean_demand(tier2),
            tier3_demand=_clean_demand(tier3),
        )
    return result


def _clean_demand(s: str) -> str:
    s = s.strip().lower()
    if "highest" in s:
        return "highest"
    if "high" in s:
        return "high"
    if "medium" in s:
        return "medium"
    return "low"


@lru_cache(maxsize=1)
def _synonym_index() -> dict[str, str]:
    """Reverse lookup: any normalized synonym/canonical -> canonical name."""
    idx: dict[str, str] = {}
    for canon, skill in load_taxonomy().items():
        idx[_norm_key(canon)] = canon
        for syn in skill.synonyms:
            idx[_norm_key(syn)] = canon
    return idx


# Canonicals where case matters because dropping case creates a collision
# with a common English word or unrelated tech. e.g. "React" (the framework)
# vs "ReAct" (the prompting pattern) both normalize to "react" — we want JDs
# mentioning React.js to NOT silently become the agentic ReAct pattern.
_CASE_SENSITIVE_CANONICALS: frozenset[str] = frozenset({"ReAct", "Go"})


def normalize(raw_skill: str | None) -> str | None:
    """Map an arbitrary skill string to its canonical form, or None if unknown.

    Strict synonym match only. The previous substring fallback produced false
    positives like "Pythonist" -> Python, "Goblet" -> Go, "react" -> ReAct
    because short canonical keys (go, react, modal) appeared as substrings of
    unrelated input. Phase 0.B's extract_node injects the canonical taxonomy
    into the LLM prompt, so the model returns canonical names directly — the
    substring escape hatch is no longer needed.

    `_CASE_SENSITIVE_CANONICALS` blocks specific collisions: an input "React"
    (capital R only) won't map to canonical "ReAct" because the case patterns
    differ. The LLM has to emit the exact canonical case for those skills.

    Defensive: `None` / empty / non-str inputs return `None` rather than
    crash. A JobNote with a YAML list-entry written as `- ` parses as
    `[None]`; without this guard, gap_aggregator.aggregate() crashes the
    whole regenerate() call on a single malformed JobNote.
    """
    if not raw_skill or not isinstance(raw_skill, str):
        return None
    key = _norm_key(raw_skill)
    if not key:
        return None
    canonical = _synonym_index().get(key)
    if canonical is None:
        return None
    if canonical in _CASE_SENSITIVE_CANONICALS and raw_skill != canonical:
        # The input case-collapses to a sensitive canonical's key but isn't
        # the canonical itself. Accept only if it's one of the canonical's
        # explicit synonyms (those are deliberate aliases by the taxonomy
        # author — e.g. "Golang" -> "Go" is intentional, but bare "go" is not).
        skill_def = load_taxonomy().get(canonical)
        if skill_def and raw_skill in skill_def.synonyms:
            return canonical
        return None
    return canonical


def category_for(canonical: str) -> str | None:
    skill = load_taxonomy().get(canonical)
    return skill.category if skill else None


def all_canonicals() -> list[str]:
    return list(load_taxonomy().keys())


def refresh_taxonomy() -> None:
    """Clear the LRU caches so the next access re-reads `skill-taxonomy.md`.

    Both `load_taxonomy` and `_synonym_index` are `@lru_cache(maxsize=1)` —
    long-running processes (the MCP server, the pipeline) cache them at
    first call and never see file edits. Tests that monkeypatch
    `TAXONOMY_PATH` get stale data too.

    Call this:
      - From the MCP server before any analysis tool (so user edits to
        skill-taxonomy.md are picked up between invocations)
      - From test fixtures that swap the taxonomy file
      - After any script that rewrites the canonical taxonomy
    """
    load_taxonomy.cache_clear()
    _synonym_index.cache_clear()
