"""Substring-based remote-policy parser for ATS location strings.

Greenhouse + Lever encode remote in the human-readable location field rather
than a typed flag (Ashby has its own `isRemote` boolean — handled separately).

Conservative on purpose: ambiguous strings return None ("don't know") rather
than guessing. We'd rather have JobNote.remote=None than a wrong True/False.
"""

from __future__ import annotations

import re

_TRUE_TOKENS = [
    "remote - us",
    "remote, us",
    "us remote",
    "remote (united states)",
    "anywhere",
    "work from home",
    "wfh",
    "fully remote",
    "100% remote",
    "remote-us",
    "us-remote",
    "or remote",
    "remote position",
]
_TRUE_STANDALONE = re.compile(r"\bremote\b", re.IGNORECASE)
_FALSE_TOKENS = [
    "san francisco",
    "new york",
    "nyc",
    "los angeles",
    "seattle",
    "boston",
    "austin",
    "chicago",
    "atlanta",
    "london",
    "paris",
    "berlin",
    "toronto",
    "palo alto",
    "mountain view",
    "menlo park",
    "cambridge",
]
_AMBIGUOUS = ["hybrid"]
# "Remote AL" / "Remote NY" — looks like a US state abbrev, ambiguous
_AMBIGUOUS_REMOTE_GEO = re.compile(r"^remote\s+[a-z]{2}\b", re.IGNORECASE)


def infer_remote_policy(location: str | None) -> bool | None:
    if location is None:
        return None
    s = location.strip()
    if not s:
        return None
    lower = s.lower()

    if any(a in lower for a in _AMBIGUOUS):
        return None

    if _AMBIGUOUS_REMOTE_GEO.match(s):
        return None

    if any(t in lower for t in _TRUE_TOKENS):
        return True

    # Standalone "remote" — be cautious if a known city ALSO appears
    if _TRUE_STANDALONE.search(lower):
        if any(f in lower for f in _FALSE_TOKENS):
            if "or remote" in lower or "remote or" in lower:
                return True
            return None
        return True

    if any(f in lower for f in _FALSE_TOKENS):
        return False

    return None
