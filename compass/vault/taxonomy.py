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
from pathlib import Path

from compass.config import TAXONOMY_PATH


@dataclass
class CanonicalSkill:
    name: str
    category: str
    synonyms: list[str] = field(default_factory=list)
    tier2_demand: str = "low"   # high | medium | low | highest
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


@lru_cache(maxsize=1)
def load_taxonomy(path: Path | None = None) -> dict[str, CanonicalSkill]:
    """Parse the taxonomy markdown into a {canonical_name: CanonicalSkill} dict.

    Returns an empty dict if the taxonomy file is missing — callers should
    handle a missing canonical gracefully (e.g., `category_for()` returning None).
    """
    path = path or TAXONOMY_PATH
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")

    result: dict[str, CanonicalSkill] = {}
    current_category: str | None = None

    for line in text.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("## "):
            header = line_stripped[3:].strip()
            current_category = _CATEGORY_HEADERS.get(header)
            continue
        if current_category is None or not line_stripped.startswith("|"):
            continue
        # parse table row
        cells = [c.strip() for c in line_stripped.split("|")[1:-1]]
        if not cells or cells[0].lower() in {"canonical", "---", ":---"}:
            continue
        if all(set(c) <= {"-", ":", " "} for c in cells):
            continue
        canonical = cells[0]
        synonyms_raw = cells[1] if len(cells) > 1 else ""
        synonyms = [s.strip() for s in synonyms_raw.split(",") if s.strip()]
        tier2 = cells[2] if len(cells) > 2 else "low"
        tier3 = cells[3] if len(cells) > 3 else "low"
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


def normalize(raw_skill: str) -> str | None:
    """Map an arbitrary skill string to its canonical form, or None if unknown."""
    key = _norm_key(raw_skill)
    if not key:
        return None
    idx = _synonym_index()
    if key in idx:
        return idx[key]
    # token-level fallback: pick first canonical whose key is a substring
    for canon_key, canon_name in idx.items():
        if canon_key and canon_key in key:
            return canon_name
    return None


def category_for(canonical: str) -> str | None:
    skill = load_taxonomy().get(canonical)
    return skill.category if skill else None


def all_canonicals() -> list[str]:
    return list(load_taxonomy().keys())
