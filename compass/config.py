"""
Compass configuration — all settings loaded from .env.
Import this module everywhere instead of reading os.environ directly.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── LLM ──────────────────────────────────────────────────────────────────────
OPENROUTER_API_KEY: str = os.environ["OPENROUTER_API_KEY"]
COMPASS_MODEL: str = os.getenv("COMPASS_MODEL", "anthropic/claude-sonnet-4-6")
ASSESSOR_MODEL: str = os.getenv("ASSESSOR_MODEL", "anthropic/claude-sonnet-4-6")

# ── Per-node model routing (OpenRouter model IDs) ────────────────────────────
EXTRACT_MODEL: str = os.getenv("EXTRACT_MODEL", "google/gemini-2.5-flash")
SCORE_MODEL: str = os.getenv("SCORE_MODEL", "google/gemini-2.5-flash")
REFLECT_MODEL: str = os.getenv("REFLECT_MODEL", "anthropic/claude-sonnet-4-6")
TAILOR_MODEL: str = os.getenv("TAILOR_MODEL", "anthropic/claude-sonnet-4-6")
# ASSESSOR_MODEL already defined above; defaults to anthropic/claude-sonnet-4-6.

# ── Langfuse ──────────────────────────────────────────────────────────────────
LANGFUSE_HOST: str = os.getenv("LANGFUSE_HOST", "http://localhost:3000")
LANGFUSE_PUBLIC_KEY: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY: str = os.getenv("LANGFUSE_SECRET_KEY", "")

# ── Vaults ────────────────────────────────────────────────────────────────────
VAULT_PATH: Path = Path(os.environ["VAULT_PATH"]).expanduser()
LEARNING_VAULT_PATH: Path = Path(
    os.getenv("LEARNING_VAULT_PATH", "~/Documents/learning-vault")
).expanduser()
TAXONOMY_PATH: Path = VAULT_PATH / "_meta" / "skill-taxonomy.md"
SKILL_INVENTORY_PATH: Path = VAULT_PATH / "_profile" / "skill-inventory.md"
PREFERENCES_PATH: Path = VAULT_PATH / "_profile" / "preferences.md"
MASTER_GAP_PLAN_PATH: Path = VAULT_PATH / "study-plans" / "master-gap-plan.md"
AGENT_LOG_PATH: Path = VAULT_PATH / "_meta" / "agent-log.md"

# ── RAG ───────────────────────────────────────────────────────────────────────
CHROMA_PATH: Path = Path(os.getenv("CHROMA_PATH", "~/.compass/chroma")).expanduser()
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# ── HiTL ──────────────────────────────────────────────────────────────────────
HITL_STATE_DB: Path = Path(os.getenv("HITL_STATE_DB", "~/.compass/hitl.db")).expanduser()
HITL_CHECKPOINT_DB: Path = Path(
    os.getenv("HITL_CHECKPOINT_DB", "~/.compass/checkpoints.db")
).expanduser()
HITL_TIMEOUT_HOURS: int = int(os.getenv("HITL_TIMEOUT_HOURS", "4"))

# ── Pipeline ──────────────────────────────────────────────────────────────────
MAX_JOBS_PER_RUN: int = int(os.getenv("MAX_JOBS_PER_RUN", "50"))
SCORE_THRESHOLD: float = float(os.getenv("SCORE_THRESHOLD", "3.5"))
MAX_CONCURRENT_JOBS: int = int(os.getenv("MAX_CONCURRENT_JOBS", "5"))

# ── Tier weights (gap_aggregator) — overrides from preferences.md at runtime ─
DEFAULT_TIER_WEIGHTS: dict[str, float] = {
    "apply-now": 1.0,
    "6-month": 0.7,
    "stretch": 0.3,
    "skip": 0.0,
    "unknown": 0.5,
}

# ── ATS targets ───────────────────────────────────────────────────────────────
GREENHOUSE_BOARDS: list[str] = [
    b.strip() for b in os.getenv("GREENHOUSE_BOARDS", "").split(",") if b.strip()
]
LEVER_COMPANIES: list[str] = [
    c.strip() for c in os.getenv("LEVER_COMPANIES", "").split(",") if c.strip()
]
ASHBY_BOARDS: list[str] = [b.strip() for b in os.getenv("ASHBY_BOARDS", "").split(",") if b.strip()]
