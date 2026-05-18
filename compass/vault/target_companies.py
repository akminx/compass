"""Parse _profile/target-companies.md into a company→tier map.

The file is human-edited but follows a stable section structure:
  ## Tier `apply-now`
  | Company | ... |
  |---|---|
  | Sierra | ... |
  ...
  ## Tier `6-month`
  ...

Parser walks the file once at module import (and on refresh()) and builds a
dict keyed by normalized company name. Naive lookup; no fuzzy matching.

This is the source of truth for JobNote.tier and CompanyNote.tier during
pipeline runs. Human edits to a CompanyNote's tier are still preserved by
write_company_note (which we don't touch here).
"""

from __future__ import annotations

import logging
import re
from typing import Literal

logger = logging.getLogger(__name__)

Tier = Literal["apply-now", "6-month", "stretch", "skip", "unknown"]
TIER_ORDER: list[Tier] = ["apply-now", "6-month", "stretch", "skip"]

# NOTE: _TIER_HEADING is intentionally un-anchored so "Tier `apply-now` (in range)"
# still captures "apply-now". Don't tighten it without updating the real vault file.
_TIER_HEADING = re.compile(r"^##\s*Tier\s*`([^`]+)`", re.IGNORECASE)
_TABLE_DIVIDER = re.compile(r"^\|\s*-+\s*\|")
_TABLE_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|")

_company_to_tier: dict[str, Tier] | None = None


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.strip().lower())


def _parse() -> dict[str, Tier]:
    import compass.config as cfg

    path = cfg.VAULT_PATH / "_profile" / "target-companies.md"
    out: dict[str, Tier] = {}
    if not path.exists():
        return out

    current_tier: Tier | None = None
    in_table = False
    table_seen_divider = False

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        m = _TIER_HEADING.match(line)
        if m:
            tier_str = m.group(1).strip().lower()
            current_tier = tier_str if tier_str in TIER_ORDER else None  # type: ignore[assignment]
            in_table = False
            table_seen_divider = False
            continue

        if current_tier is None:
            continue

        if _TABLE_DIVIDER.match(line):
            table_seen_divider = True
            in_table = True
            continue

        if in_table and table_seen_divider:
            if not line.startswith("|"):
                in_table = False
                table_seen_divider = False
                continue
            mrow = _TABLE_ROW.match(line)
            if mrow:
                company = mrow.group(1).strip()
                if not company or company.lower() == "company":
                    continue
                key = _normalize(company)
                existing = out.get(key)
                if existing is None or TIER_ORDER.index(current_tier) < TIER_ORDER.index(existing):
                    out[key] = current_tier
        else:
            in_table = False
            table_seen_divider = False

    return out


def refresh() -> None:
    """Re-parse target-companies.md. Call from tests or after manual edits."""
    global _company_to_tier
    _company_to_tier = _parse()
    logger.info("target_companies: parsed %d entries", len(_company_to_tier))


# Minimum length for the bidirectional substring fallback. Prevents tiny tokens
# like "ai" / "ml" from matching every long key by accident.
_MIN_FUZZY_LEN = 4


def get_tier(company: str) -> Tier:
    """Resolve a tier for a company name.

    Lookup strategy:
      1. Exact normalized match.
      2. Bidirectional substring fallback — handles the common case where a
         scraper board_token is a single word (e.g. "gleanwork", "nvidia") but
         target-companies.md uses a longer descriptive name in one cell
         (e.g. "Glean", "NVIDIA Agentic AI", "Vapi, Retell, Wispr Flow").
         Either direction (query ⊂ key OR key ⊂ query) counts as a match.
      3. If multiple bidirectional matches with different tiers, the highest
         tier (apply-now > 6-month > stretch > skip) wins.
    """
    if _company_to_tier is None:
        refresh()
    assert _company_to_tier is not None  # mypy: refresh sets it

    query = _normalize(company)
    if not query:
        return "unknown"

    # Exact match
    direct = _company_to_tier.get(query)
    if direct is not None:
        return direct

    # Bidirectional substring fallback (guarded by min-length to avoid noise)
    if len(query) < _MIN_FUZZY_LEN:
        return "unknown"

    best_tier: Tier | None = None
    for key, tier in _company_to_tier.items():
        if len(key) < _MIN_FUZZY_LEN:
            continue
        if (query in key or key in query) and (
            best_tier is None or TIER_ORDER.index(tier) < TIER_ORDER.index(best_tier)
        ):
            best_tier = tier
    return best_tier or "unknown"


# Parse at import for callers that don't trigger refresh().
# At test-collection time conftest sets VAULT_PATH to a placeholder dir, so the
# import-time parse usually returns {}. Tests must call refresh() after their
# fixture monkeypatches cfg.VAULT_PATH.
refresh()
