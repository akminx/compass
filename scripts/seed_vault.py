"""
seed_vault.py — initializes the compass-vault folder structure.

Run once after cloning: uv run python scripts/seed_vault.py

Creates all required folders and placeholder files.
Does NOT overwrite existing files.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from compass.config import VAULT_PATH


FOLDERS = [
    "_raw/jd-captures",
    "_raw/company-research",
    "_raw/interview-notes",
    "_meta/templates",
    "_profile",
    "jobs",
    "companies",
    "skills",
    "applications",
    "interviews",
    "study-plans",
]

TEMPLATE_TAXONOMY = """# Taxonomy — controlled tag vocabulary

## Skill categories
- `agent-framework` — LangGraph, CrewAI, AutoGen, OpenClaw, Hermes, Claude Code
- `data` — Snowflake, Databricks, Delta Lake, SQL, Pandas, Spark
- `infra` — AWS, Azure, GCP, Docker, Modal, Prefect, Kubernetes
- `ml` — PyTorch, TensorFlow, MLflow, fine-tuning, embeddings, RAG
- `language` — Python, TypeScript, SQL, Java
- `observability` — Langfuse, LangSmith, MLflow tracking
- `mcp` — MCP server design, tool contracts, skill design

## Job status values
- `reviewing` — discovered, not yet decided
- `applied` — application submitted
- `interviewing` — active interview process
- `rejected` — no offer
- `offer` — received offer

## Company tier values
- `apply-now` — ready to apply today
- `3-months` — ready in ~3 months
- `6-months` — ready in ~6 months
- `stretch` — needs significant prep

## Skill level values
- `none` — haven't used it
- `learning` — read docs, understand concepts, nothing shipped
- `familiar` — used in a real project, need docs for complex things
- `proficient` — shipped real things, can answer interview questions
- `expert` — deep internals, could teach it
"""

TEMPLATE_JOB = """---
company: 
title: 
url: 
source: 
date_found: 
status: reviewing
match_score: 
salary_min: 
salary_max: 
location: 
remote: 
tags: []
skills_required: []
skills_missing: []
jd_summary: 
---

## Notes

"""

TEMPLATE_SKILL = """---
skill: 
category: 
my_level: none
evidence: []
appears_in_jobs: 0
priority: medium
resources: []
---

## What it is

## Why it matters

## How to learn it

## Interview questions

"""

DASHBOARD = """# Compass Dashboard

> Your career coaching command center. Powered by Dataview.

## Active pipeline
```dataview
TABLE match_score, status, company, title
FROM "jobs"
WHERE status = "reviewing"
SORT match_score DESC
LIMIT 20
```

## Applied — waiting for response
```dataview
TABLE applied_date, company, title, status
FROM "applications"
SORT applied_date DESC
```

## Top skill gaps (appearing in most jobs, level = none or learning)
```dataview
TABLE appears_in_jobs, my_level, priority
FROM "skills"
WHERE my_level = "none" OR my_level = "learning"
SORT appears_in_jobs DESC
LIMIT 15
```

## Companies to track
```dataview
TABLE tier, hiring_signal, roles_of_interest
FROM "companies"
SORT tier ASC
```
"""


def main():
    if not VAULT_PATH.exists():
        print(f"Creating vault at {VAULT_PATH}")
        VAULT_PATH.mkdir(parents=True)

    for folder in FOLDERS:
        path = VAULT_PATH / folder
        path.mkdir(parents=True, exist_ok=True)
        print(f"  ✓ {folder}/")

    # Write taxonomy
    write_if_missing(VAULT_PATH / "_meta" / "taxonomy.md", TEMPLATE_TAXONOMY)
    write_if_missing(VAULT_PATH / "_meta" / "agent-log.md", "# Agent Log\n\n")
    write_if_missing(VAULT_PATH / "_meta" / "templates" / "job.md", TEMPLATE_JOB)
    write_if_missing(VAULT_PATH / "_meta" / "templates" / "skill.md", TEMPLATE_SKILL)
    write_if_missing(VAULT_PATH / "dashboard.md", DASHBOARD)

    print(f"\n✓ Vault seeded at {VAULT_PATH}")
    print("Next: copy your _profile/ docs into the vault manually.")
    print("Then run: uv run pytest tests/ -q")


def write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(content)
        print(f"  ✓ {path.relative_to(VAULT_PATH)}")
    else:
        print(f"  — {path.relative_to(VAULT_PATH)} (already exists, skipped)")


if __name__ == "__main__":
    main()
