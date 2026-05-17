"""
Seed compass-vault/skills/*.md from the calibrated initial inventory.

Idempotent: preserves any `evidence:` URIs and `grade_override:` the user has set.

    uv run python scripts/seed_skills.py
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from compass.config import VAULT_PATH
from compass.vault.taxonomy import load_taxonomy


SEED: dict[str, tuple[int, list[str]]] = {
    # Languages
    "Python": (3, []),
    "SQL": (3, []),
    "JavaScript": (1, []),
    "TypeScript": (0, []),
    "Go": (0, []),

    # LLM APIs
    "Anthropic Claude API": (3, []),
    "OpenAI API": (1, []),
    "Gemini API": (0, []),
    "Function calling": (3, []),
    "Structured outputs": (3, []),
    "Pydantic": (2, []),

    # Agent frameworks
    "LangChain": (3, []),
    "LangGraph": (1, []),
    "Pydantic AI": (1, []),
    "Anthropic SDK": (2, []),
    "OpenAI Agents SDK": (0, []),
    "CrewAI": (1, []),
    "AutoGen": (1, []),
    "DSPy": (0, []),
    "Google ADK": (0, []),

    # MCP — strongest cluster
    "MCP": (4, []),
    "MCP server authoring": (4, []),
    "Sub-agents": (3, []),
    "Agent skills": (3, []),

    # Prompt / context
    "Prompt engineering": (3, []),
    "Context engineering": (2, []),
    "Chain-of-thought": (1, []),
    "Prompt caching": (0, []),

    # RAG
    "RAG": (1, []),
    "Embeddings": (1, []),
    "Vector search": (0, []),
    "Agentic RAG": (1, []),
    "Graph RAG": (1, []),
    "Hybrid retrieval": (1, []),
    "Re-ranking": (1, []),

    # Vector DBs
    "Chroma": (0, []), "Pinecone": (0, []), "pgvector": (0, []),
    "Weaviate": (0, []), "Qdrant": (0, []), "FAISS": (0, []),

    # Evals
    "Eval harness": (0, []), "LLM-as-judge": (1, []),
    "DeepEval": (0, []), "Ragas": (0, []), "Regression eval": (0, []),

    # Observability
    "Langfuse": (0, []), "LangSmith": (0, []), "Braintrust": (0, []),
    "Arize": (0, []), "Galileo": (0, []), "HoneyHive": (0, []),
    "Patronus": (0, []), "OpenTelemetry": (0, []),

    # Durable execution
    "Temporal": (0, []), "Inngest": (0, []), "Modal": (0, []), "Restate": (0, []),
    "LangGraph checkpointing": (1, []),

    # Multi-agent
    "ReAct": (1, []), "Self-reflection": (1, []),
    "Hierarchical delegation": (2, []), "Agent-as-tool": (1, []),

    # HITL
    "HiTL": (1, []), "Interrupt/resume": (0, []), "Escalation patterns": (1, []),

    # Production
    "Cost per run": (1, []), "Latency budgets": (1, []),
    "Response streaming": (1, []), "Retry / idempotency": (2, []),
    "Prompt injection defense": (2, []), "Guardrails": (0, []),

    # Cloud
    "AWS Bedrock": (0, []), "AWS Lambda": (1, []),
    "Azure AI Foundry": (0, []), "GCP Vertex AI": (0, []), "BigQuery": (0, []),

    # Deployment
    "Docker": (2, []), "Kubernetes": (0, []), "FastAPI": (1, []), "Serverless": (0, []),

    # Browser / computer use
    "Browserbase": (0, []), "Stagehand": (0, []),
    "Playwright": (0, []), "Computer Use API": (0, []),

    # Voice (skip)
    "Vapi": (0, []), "Retell": (0, []), "Livekit": (0, []),
    "Deepgram": (0, []), "ElevenLabs": (0, []), "Twilio": (0, []),

    # Fine-tuning (anti-claims)
    "SFT": (0, []), "LoRA": (0, []), "RLHF": (0, []), "DPO": (0, []),
}


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w\-.]+", "_", name)


def write_skill_note(canonical: str, level: int, evidence: list[str]) -> Path:
    taxonomy = load_taxonomy()
    skill_def = taxonomy.get(canonical)
    if not skill_def:
        raise ValueError(f"unknown canonical: {canonical}")

    skills_dir = VAULT_PATH / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    path = skills_dir / f"{_safe_filename(canonical)}.md"

    existing_evidence: list[str] = []
    existing_override = None
    if path.exists():
        text = path.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        if m:
            try:
                existing = yaml.safe_load(m.group(1)) or {}
                existing_evidence = existing.get("evidence", []) or []
                existing_override = existing.get("grade_override")
            except yaml.YAMLError:
                pass

    merged_evidence = list(dict.fromkeys([*existing_evidence, *evidence]))
    effective_level = existing_override if existing_override is not None else level
    fm = {
        "type": "skill",
        "skill": canonical,
        "category": skill_def.category,
        "synonyms": skill_def.synonyms,
        "my_level": effective_level,
        "grade_override": existing_override,
        "appears_in_jobs": 0,
        "tier_demand": {"apply-now": 0, "6-month": 0, "stretch": 0},
        "gap_score": 0.0,
        "priority": "medium",
        "evidence": merged_evidence,
        "study_resources": [],
        "tags": ["#skill", f"#cat/{skill_def.category}", f"#grade/{effective_level}"],
    }
    yaml_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    body = (
        f"\n# {canonical}\n\n"
        f"_Category: {skill_def.category} · Tier-2 demand: {skill_def.tier2_demand} · Tier-3 demand: {skill_def.tier3_demand}_\n\n"
        f"## Current level: {effective_level}/5\n\n"
        f"## Evidence\n"
        f"_Add `learning-vault://` URIs to the `evidence:` field in frontmatter; the assessor will regrade._\n\n"
        f"## Notes\n"
    )
    path.write_text(f"---\n{yaml_text}\n---\n{body}", encoding="utf-8")
    return path


def main() -> None:
    written = 0
    for canonical, (level, evidence) in SEED.items():
        try:
            write_skill_note(canonical, level, evidence)
            written += 1
        except ValueError as e:
            print(f"  skip: {e}")
    print(f"Wrote {written} skill notes to {VAULT_PATH / 'skills'}")


if __name__ == "__main__":
    main()
