"""Parse _profile/target-companies.md into a company→tier map AND
_profile/target-companies.yaml into a company→full-metadata map.

Two files cooperate:
- target-companies.md — human-readable narrative + tier tables. Source of truth
  for `get_tier` lookups (legacy, tested).
- target-companies.yaml — machine-readable per-company metadata: ATS coords,
  geos, interview_difficulty, role_family_hints, notes.
  Source of truth for `get_company_meta` lookups (added 2026-05-19).

Both are kept in sync by hand. Eventually the YAML may absorb the md tier
column outright, but for the 3-month pivot they coexist.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    # Tier vocabulary lives in compass.vault.schemas — single source of truth.
    # Type-only import: TIER_ORDER stores the literal strings; the Tier
    # alias is only referenced in annotations (`list[Tier]`, `dict[str, Tier]`).
    from compass.vault.schemas import Tier

logger = logging.getLogger(__name__)

# Order: most-preferred first. Used by `get_tier` to break bidirectional-match
# ties (prefer the strongest tier when a company name matches multiple entries).
TIER_ORDER: list[Tier] = [
    "apply-now",
    "opportunistic",
    "backend-prep",
    "6-month",
    "stretch",
    "skip",
]

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

    Lookup precedence (highest first):
      1. YAML exact match — `target-companies.yaml` is the 3-month-pivot source
         of truth and carries newer entries (banks/consulting/manual-provider)
         that the legacy markdown hasn't been updated to reflect.
      2. Markdown exact match — legacy lookup; still useful for entries that
         exist only in `target-companies.md`.
      3. Bidirectional substring fallback against the markdown (handles the
         common case where a scraper board_token is a single word but the
         markdown uses a longer descriptive name).
      4. If multiple substring matches with different tiers, the highest tier
         (apply-now > opportunistic > backend-prep > ... > skip) wins.

    Returns "unknown" when no source resolves the company.
    """
    if _company_to_tier is None:
        refresh()
    assert _company_to_tier is not None  # mypy: refresh sets it

    query = _normalize(company)
    if not query:
        return "unknown"

    # 1. YAML exact match — newest source of truth.
    yaml_meta = get_company_meta(company)
    if yaml_meta is not None:
        yaml_tier = yaml_meta.get("tier")
        if yaml_tier in TIER_ORDER:
            return yaml_tier  # type: ignore[return-value]

    # 2. Markdown exact match.
    direct = _company_to_tier.get(query)
    if direct is not None:
        return direct

    # 3. Bidirectional substring fallback (guarded by min-length to avoid noise).
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


# ── YAML-driven per-company metadata ─────────────────────────────────────────

_yaml_meta: dict[str, dict] | None = None
_yaml_mtime: float | None = None  # last-seen mtime of target-companies.yaml


def _yaml_path():
    """Resolve VAULT_PATH at call time — required so tests that monkeypatch
    `compass.config.VAULT_PATH` don't get the module-import-time value."""
    import compass.config as cfg

    return cfg.VAULT_PATH / "_profile" / "target-companies.yaml"


def _parse_yaml() -> dict[str, dict]:
    """Load _profile/target-companies.yaml into {normalized_company: meta_dict}.

    Returns {} when the file is missing — callers fall through to the legacy
    markdown-only behavior.
    """
    path = _yaml_path()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        logger.warning("target-companies.yaml is malformed: %s", e)
        return {}
    out: dict[str, dict] = {}
    for entry in data.get("companies") or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("company")
        if not name:
            continue
        # Index by primary name AND any aliases (e.g. JPMorgan ↔ JPMC, BofA ↔ BankofAmerica)
        keys = [_normalize(name)]
        aliases = entry.get("aliases") or []
        if isinstance(aliases, list):
            keys.extend(_normalize(a) for a in aliases if isinstance(a, str))
        for k in keys:
            if k:
                out[k] = entry
    return out


def refresh_yaml() -> None:
    """Re-parse target-companies.yaml. Call from tests or after manual edits.
    Cheap — small file, < 1ms read."""
    global _yaml_meta, _yaml_mtime
    _yaml_meta = _parse_yaml()
    path = _yaml_path()
    _yaml_mtime = path.stat().st_mtime if path.exists() else None
    logger.info("target_companies (yaml): parsed %d entries", len(_yaml_meta))


def _maybe_reload_yaml() -> None:
    """Reload _yaml_meta if the file on disk has been modified since last
    parse. Called by every YAML-reading accessor so a long-running MCP
    server picks up edits within ~one mtime check.

    Cheap — a single stat() call per accessor invocation.
    """
    global _yaml_meta, _yaml_mtime
    if _yaml_meta is None:
        refresh_yaml()
        return
    path = _yaml_path()
    if not path.exists():
        if _yaml_meta:
            _yaml_meta = {}
            _yaml_mtime = None
        return
    current_mtime = path.stat().st_mtime
    if _yaml_mtime is None or current_mtime > _yaml_mtime:
        refresh_yaml()


def get_company_meta(company: str) -> dict | None:
    """Return the full YAML metadata dict for a company, or None if absent.

    Lookup uses the same normalize + bidirectional-substring strategy as
    `get_tier`. Returns None — not a default — so callers can distinguish
    "company not in target list" from "company has empty metadata".
    """
    _maybe_reload_yaml()
    assert _yaml_meta is not None  # mypy: _maybe_reload_yaml ensures non-None

    query = _normalize(company)
    if not query:
        return None

    direct = _yaml_meta.get(query)
    if direct is not None:
        return direct

    if len(query) < _MIN_FUZZY_LEN:
        return None

    for key, meta in _yaml_meta.items():
        if len(key) < _MIN_FUZZY_LEN:
            continue
        if query in key or key in query:
            return meta
    return None


_VALID_DIFFICULTIES = {
    "hackerrank",
    "case",
    "lc-easy",
    "lc-medium",
    "lc-medium-hard",
    "lc-hard",
    "takehome",
    "unknown",
}


def get_interview_difficulty(company: str) -> str:
    """Return one of `_VALID_DIFFICULTIES`. YAML typos collapse to "unknown"
    so JobNote/CompanyNote schema validation never fails on human edits."""
    meta = get_company_meta(company)
    if meta is None:
        return "unknown"
    raw = str(meta.get("interview_difficulty") or "unknown").strip().lower()
    return raw if raw in _VALID_DIFFICULTIES else "unknown"


def get_ats(company: str) -> tuple[str, str] | None:
    """Return (provider, slug) or None if not in YAML or not scrapable."""
    meta = get_company_meta(company)
    if meta is None:
        return None
    ats = meta.get("ats") or {}
    provider = ats.get("provider")
    slug = ats.get("slug")
    if not provider or not slug:
        return None
    return (str(provider), str(slug))


def list_yaml_companies(tier_filter: str | None = None) -> list[dict]:
    """Return the raw company entries from the YAML, optionally filtered to
    one tier. Used by seed scripts + scraper positive-filtering.

    `_yaml_meta` indexes each entry by primary name AND all aliases — so a
    naive `list(_yaml_meta.values())` returns N+1 copies for a company with
    N aliases (JPMorgan has 5 aliases ⇒ 6 entries). Deduplicate by object
    identity so callers (seed_companies_from_yaml, gap_aggregator, MCP tools)
    see each company exactly once.
    """
    _maybe_reload_yaml()
    assert _yaml_meta is not None
    # dict-by-id deduplication preserves order of first encounter
    unique = list({id(e): e for e in _yaml_meta.values()}.values())
    if tier_filter is not None:
        unique = [e for e in unique if e.get("tier") == tier_filter]
    return unique


refresh_yaml()
