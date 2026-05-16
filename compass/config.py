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

# ── Langfuse ──────────────────────────────────────────────────────────────────
LANGFUSE_HOST: str = os.getenv("LANGFUSE_HOST", "http://localhost:3000")
LANGFUSE_PUBLIC_KEY: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY: str = os.getenv("LANGFUSE_SECRET_KEY", "")

# ── Vault ─────────────────────────────────────────────────────────────────────
VAULT_PATH: Path = Path(os.environ["VAULT_PATH"])

# ── Pipeline ──────────────────────────────────────────────────────────────────
MAX_JOBS_PER_RUN: int = int(os.getenv("MAX_JOBS_PER_RUN", "50"))
SCORE_THRESHOLD: float = float(os.getenv("SCORE_THRESHOLD", "3.5"))
HITL_TIMEOUT_HOURS: int = int(os.getenv("HITL_TIMEOUT_HOURS", "4"))

# ── ATS targets ───────────────────────────────────────────────────────────────
GREENHOUSE_BOARDS: list[str] = [
    b.strip() for b in os.getenv("GREENHOUSE_BOARDS", "").split(",") if b.strip()
]
LEVER_COMPANIES: list[str] = [
    c.strip() for c in os.getenv("LEVER_COMPANIES", "").split(",") if c.strip()
]
ASHBY_BOARDS: list[str] = [
    b.strip() for b in os.getenv("ASHBY_BOARDS", "").split(",") if b.strip()
]
