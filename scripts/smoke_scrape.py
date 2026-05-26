"""
scripts/test_scrape.py — live-API smoke test for the three scrapers.

Runs against one known-good board per ATS. Expects each to return >= 1 RawJob.

Usage:
    uv run python scripts/test_scrape.py
"""

from __future__ import annotations

import asyncio
import sys

from compass.scrapers.ashby import scrape_ashby
from compass.scrapers.greenhouse import scrape_greenhouse
from compass.scrapers.lever import scrape_lever


async def main() -> int:
    targets = [
        ("greenhouse", "stripe", scrape_greenhouse),
        ("lever", "netflix", scrape_lever),
        ("ashby", "posthog", scrape_ashby),
    ]
    failures = 0
    for source, slug, fn in targets:
        try:
            jobs = await fn(slug)
        except Exception as e:
            print(f"  X {source} {slug}: raised {type(e).__name__}: {e}")
            failures += 1
            continue
        if not jobs:
            print(f"  X {source} {slug}: returned 0 jobs (expected >= 1)")
            failures += 1
            continue
        print(f"  OK {source} {slug}: {len(jobs)} jobs (sample: {jobs[0].title!r})")
    if failures:
        print(f"\nFAILED: {failures} of {len(targets)} sources")
        return 1
    print(f"\nPASSED: all {len(targets)} sources returned jobs")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
