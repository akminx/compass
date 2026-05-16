"""
seed_skills.py — creates a skills/SkillName.md note for every skill
in _profile/skill-inventory.md that doesn't already exist.

Run: uv run python scripts/seed_skills.py
"""
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from compass.config import VAULT_PATH

INVENTORY_PATH = VAULT_PATH / "_profile" / "skill-inventory.md"
SKILLS_DIR = VAULT_PATH / "skills"

# Map section headers to skill categories
CATEGORY_MAP = {
    "Agent Frameworks": "agent-framework",
    "MCP": "mcp",
    "Observability": "observability",
    "RAG": "ml",
    "LLM": "ml",
    "Prompt Engineering": "ml",
    "Data Engineering": "data",
    "Infrastructure": "infra",
    "Languages": "language",
    "ML": "ml",
    "Memory": "ml",
    "Soft Skills": "soft",
}

PRIORITY_MAP = {
    "none": "high",
    "learning": "high",
    "familiar": "medium",
    "proficient": "low",
    "expert": "low",
}


def parse_skill_inventory(path: Path) -> list[dict]:
    """Parse skill-inventory.md tables into a list of skill dicts."""
    content = path.read_text()
    skills = []
    current_category = "ml"

    for line in content.splitlines():
        # Detect section headers (## heading)
        if line.startswith("## "):
            section = line.lstrip("# ").strip()
            for key, cat in CATEGORY_MAP.items():
                if key.lower() in section.lower():
                    current_category = cat
                    break

        # Detect table rows: | Skill | Level | Evidence | Notes |
        if line.startswith("|") and not line.startswith("| Skill") and not line.startswith("|---"):
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) >= 2 and parts[0] and parts[0] != "Skill":
                skill_name = parts[0].strip("`")
                level = parts[1].strip() if len(parts) > 1 else "none"
                evidence = parts[2].strip() if len(parts) > 2 else ""
                notes = parts[3].strip() if len(parts) > 3 else ""

                if level not in ("none", "learning", "familiar", "proficient", "expert"):
                    continue

                skills.append({
                    "name": skill_name,
                    "category": current_category,
                    "level": level,
                    "evidence": evidence,
                    "notes": notes,
                    "priority": PRIORITY_MAP.get(level, "medium"),
                })

    return skills


def skill_note_content(skill: dict) -> str:
    evidence_list = f'  - "{skill["evidence"]}"' if skill["evidence"] else ""
    return f"""---
skill: {skill["name"]}
category: {skill["category"]}
my_level: {skill["level"]}
evidence:
{evidence_list if evidence_list else "  []"}
appears_in_jobs: 0
priority: {skill["priority"]}
resources: []
---

## What it is

## Why it matters for target roles

## Current level: {skill["level"]}
{skill["notes"] if skill["notes"] else ""}

## How to level up

## Interview questions

"""


def main():
    if not INVENTORY_PATH.exists():
        print(f"ERROR: skill-inventory not found at {INVENTORY_PATH}")
        return

    SKILLS_DIR.mkdir(exist_ok=True)
    skills = parse_skill_inventory(INVENTORY_PATH)
    created = 0
    skipped = 0

    for skill in skills:
        # Sanitize filename
        filename = re.sub(r'[^\w\-.]', '-', skill["name"]) + ".md"
        path = SKILLS_DIR / filename

        if path.exists():
            skipped += 1
            continue

        path.write_text(skill_note_content(skill))
        print(f"  ✓ skills/{filename}  ({skill['level']})")
        created += 1

    print(f"\n✓ Created {created} skill notes, skipped {skipped} existing")
    print(f"  RAG indexer can now embed {created + skipped} skills from skills/")


if __name__ == "__main__":
    main()
