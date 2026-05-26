"""Shared frontmatter parser. Consolidates a regex+yaml.safe_load helper that
previously existed in three places (gap_aggregator, skill_assessor, and the
MCP server importing the gap_aggregator copy).

Returns the superset shape `(frontmatter_dict, body)`. Callers that only need
the dict can ignore the body.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def parse_frontmatter(path: Path) -> tuple[dict, str]:
    """Read `path` and split into (frontmatter dict, body string).

    Returns `({}, full_text)` when no YAML block is present — callers can
    treat that as "not a vault note" without a separate `exists()` check.
    """
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    return yaml.safe_load(m.group(1)) or {}, m.group(2)
