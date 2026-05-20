"""US-friendly location gate for intake_filter.

The candidate profile in `_profile/preferences.md` declares preferred /
acceptable locations as US cities + Remote-US. Pre-fix, the pipeline ignored
this — a role posted in a non-US city was treated identically to a US-based
one, and any non-senior non-US posting could dominate the round-robin.

Strategy: conservative drop. Reject only when the `RawJob.location` string
contains an unambiguous non-US country/city token AND no US token. Ambiguous
strings ("Remote", "Multiple Locations", "") pass through. Tightening this
later (state-abbrev matching, region scoring) is fine; loosening accidentally
sent non-US jobs through.

The list is intentionally short and high-confidence — it's better for a
non-US JD to slip through than for a US Remote job to get dropped because
the city wasn't in our allowlist.
"""

from __future__ import annotations

import re

# Non-US country names + major non-US tech-hub cities. Lowercase, word-bounded.
# Keep this conservative — only tokens that, alone, indicate a non-US base.
_NON_US_TOKENS = [
    # Countries / regions
    "united kingdom", "uk", "england", "scotland", "wales", "ireland",
    "germany", "deutschland", "france", "spain", "italy", "portugal",
    "netherlands", "belgium", "luxembourg", "switzerland", "austria",
    "sweden", "norway", "denmark", "finland", "iceland",
    "poland", "czech republic", "romania", "hungary",
    "india", "singapore", "malaysia", "thailand", "vietnam", "philippines",
    "australia", "new zealand",
    "japan", "south korea", "korea", "china", "hong kong", "taiwan",
    "israel", "uae", "united arab emirates", "saudi arabia", "egypt",
    "brazil", "argentina", "chile", "colombia", "mexico", "peru",
    "south africa", "nigeria", "kenya",
    "canada",  # explicitly out per user's preferences.md
    "emea", "apac", "latam",
    # Major non-US cities (use only when unambiguous globally)
    "london", "manchester", "edinburgh", "dublin",
    "berlin", "munich", "hamburg", "frankfurt",
    "paris", "lyon", "marseille",
    "madrid", "barcelona", "lisbon", "porto",
    "amsterdam", "rotterdam", "brussels", "zurich", "geneva", "vienna",
    "stockholm", "oslo", "copenhagen", "helsinki",
    "warsaw", "prague", "budapest", "bucharest",
    "bengaluru", "bangalore", "mumbai", "delhi", "hyderabad", "chennai", "pune", "kolkata", "gurgaon", "noida",
    "tokyo", "osaka", "kyoto", "seoul", "shanghai", "beijing", "shenzhen", "guangzhou", "taipei",
    "sydney", "melbourne", "brisbane", "perth", "auckland",
    "toronto", "vancouver", "montreal", "ottawa",
    "tel aviv", "jerusalem", "haifa",
    "dubai", "abu dhabi", "riyadh", "doha",
    "são paulo", "sao paulo", "rio de janeiro", "buenos aires", "santiago", "bogotá", "bogota",
    "mexico city", "guadalajara",
]

# Tokens that, when present, prove the JD IS US-eligible — even alongside a
# non-US token (e.g. "Remote - US / Canada", "London or San Francisco").
_US_TOKENS = [
    "united states", "u.s.", " us ", " us,", " us.", "usa", " u.s ",
    "remote-us", "remote - us", "remote (us", "remote, us",
    "north america",  # ambiguous; tempering: also matched by "north america (canada+us)"
    # Common US cities
    "new york", "nyc", "manhattan", "brooklyn",
    "san francisco", "bay area", "palo alto", "menlo park", "mountain view", "sunnyvale", "santa clara", "san jose",
    "los angeles", " la,", " la ", "santa monica",
    "seattle", "bellevue", "redmond",
    "boston", "cambridge",
    "austin", "dallas", "houston", "san antonio", "plano", "frisco",
    "chicago",
    "denver", "boulder",
    "atlanta",
    "miami",
    "washington dc", "washington, d.c", "arlington", "mclean", "reston", "tysons",
    "charlotte", "raleigh", "durham",
    "philadelphia", "pittsburgh",
    "minneapolis", "st. paul",
    "phoenix", "scottsdale",
    "salt lake city",
    "portland, or",
    "san diego",
    "nashville",
]

_NON_US_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in sorted(_NON_US_TOKENS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
# US tokens use substring match (not word-bounded) because patterns like " us "
# need surrounding whitespace context that re.escape preserves verbatim.
_US_RE = re.compile(
    "(" + "|".join(re.escape(t) for t in sorted(_US_TOKENS, key=len, reverse=True)) + ")",
    re.IGNORECASE,
)


def is_us_compatible(location: str | None) -> tuple[bool, str]:
    """Return (keep, reason).

    keep=True: location is US-compatible (or ambiguous — empty / "Remote" /
        "Multiple Locations" / unrecognized city).
    keep=False: location contains an unambiguous non-US token and no US token.
    """
    if not location or not location.strip():
        return (True, "")
    loc = location.strip()
    # Quick exits: pure "Remote" with no qualifier → ambiguous, keep.
    if loc.lower() in {"remote", "anywhere", "worldwide", "multiple locations", "n/a"}:
        return (True, "")
    non_us = _NON_US_RE.search(loc)
    us = _US_RE.search(loc)
    if non_us and not us:
        return (False, f"non-US location: {loc!r}")
    return (True, "")
