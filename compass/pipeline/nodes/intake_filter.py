"""intake_filter_node — role-family gate.

Runs BEFORE extract so out-of-scope JDs never burn an LLM extract+score call.

Pipeline cost optimization: this saves ~$0.003 per dropped JD (skipping
extract+score+tailor) for the ~30–50% of postings on most boards that are
sales / PM / design / CS. With MAX_JOBS_PER_RUN=50, that's ~$0.10/day saved.

More importantly: it fixes the gap-aggregator bias introduced by Phase 0.B's
SCORE_THRESHOLD write-gate. Now ALL in-scope JDs reach the vault regardless
of current match score, so stretch-role gaps (the ones Akash should be
studying toward) actually drive the master gap plan.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING

import compass.config as cfg
from compass.pipeline.role_family import keyword_classify, llm_classify, upgrade_family
from compass.vault.reader import load_reject_rules

# Body-level signal that the JD actually describes agentic work in production —
# mirrors the "AND" clause in _profile/target-roles.md::JD-master-boolean. Used
# as a secondary gate after title-based role_family classification: an AI-flavored
# title with ZERO of these terms in the body is almost always a generic ML/RAG
# role, not the agent-eng work the user wants. Word boundaries enforced so
# "agent" doesn't trip on "agenda" or "agentic" inside "non-agentic".
_AGENT_BODY_TERMS = [
    r"\bagents?\b",
    r"\bagentic\b",
    r"\bagent[-\s]?orchestration\b",
    r"\bmulti[-\s]?agent\b",
    r"\bmcp\b",
    r"\bmodel context protocol\b",
    r"\blanggraph\b",
    r"\blangchain\b",
    r"\bpydantic\s+ai\b",
    r"\bagents\s+sdk\b",
    r"\blangfuse\b",
    r"\blangsmith\b",
    r"\bbraintrust\b",
    r"\btool[-\s]?calling\b",
    r"\bfunction[-\s]?calling\b",
    r"\bdurable\s+execution\b",
    r"\bsub[-\s]?agents?\b",
]
_AGENT_BODY_RE = re.compile("|".join(_AGENT_BODY_TERMS), re.IGNORECASE)


def _agent_signal_count(body: str) -> int:
    """Count distinct agent-related term hits in the body. Returns the unique
    pattern count, so a body mentioning 'agents' 10 times still scores 1."""
    if not body:
        return 0
    return len({m.group(0).lower() for m in _AGENT_BODY_RE.finditer(body)})


if TYPE_CHECKING:
    from compass.pipeline.state import CompassState

logger = logging.getLogger(__name__)


def _log_filtered(company: str, title: str, reason: str) -> None:
    # IMPORTANT: read VAULT_PATH at call time. Module-level constants would
    # break the temp_vault test fixture (which monkeypatches cfg.VAULT_PATH).
    log_path = cfg.VAULT_PATH / "_meta" / "filtered-jobs.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = f"- [{datetime.now().isoformat(timespec='seconds')}] {company} {title!r} — {reason}\n"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line)


async def intake_filter_node(state: CompassState) -> dict:
    job = state.get("current_job")
    if job is None:
        return {
            "in_scope": False,
            "role_family": "out-of-scope",
            "errors": [*state.get("errors", []), "intake_filter_node: current_job is None"],
        }

    body = job.description or ""

    # Hard rejects from preferences.md — runs BEFORE LLM-stage classification so
    # senior/staff/principal/lead titles and "5+ years" / "PhD required" JDs are
    # dropped at zero LLM cost. On a 41-board scrape this is ~40-60% of volume.
    rules = load_reject_rules()
    title_lc = (job.title or "").lower()
    body_lc = body.lower()
    for needle in rules["title"]:
        if needle and needle in title_lc:
            _log_filtered(job.company, job.title, f"title rejects: {needle!r}")
            logger.info(
                "intake_filter: dropped %s — %s (title rule: %r)",
                job.company,
                job.title,
                needle,
            )
            return {"in_scope": False, "role_family": "out-of-scope"}
    for needle in rules["jd"]:
        if needle and needle in body_lc:
            _log_filtered(job.company, job.title, f"jd rejects: {needle!r}")
            logger.info(
                "intake_filter: dropped %s — %s (jd rule: %r)",
                job.company,
                job.title,
                needle,
            )
            return {"in_scope": False, "role_family": "out-of-scope"}

    decided, family = keyword_classify(job.title)
    if decided is True:
        upgraded = upgrade_family(family, body)
        return _gated_by_agent_signal(job.company, job.title, body, upgraded)
    if decided is False:
        _log_filtered(job.company, job.title, f"title keyword → {family}")
        logger.info("intake_filter: dropped %s — %s (keyword)", job.company, job.title)
        return {"in_scope": False, "role_family": family}

    # Borderline — escalate to LLM
    try:
        result = await llm_classify(job.title, body[:500])
    except Exception as e:
        logger.warning(
            "intake_filter: LLM classify failed for %r — %s; defaulting to IN", job.title, e
        )
        return {"in_scope": True, "role_family": upgrade_family("other-eng", body)}

    if not result.in_scope:
        _log_filtered(job.company, job.title, f"llm → {result.reason}")
        logger.info(
            "intake_filter: dropped %s — %s (llm: %s)", job.company, job.title, result.reason
        )
        return {"in_scope": False, "role_family": result.role_family}

    upgraded = upgrade_family(result.role_family, body)
    return _gated_by_agent_signal(job.company, job.title, body, upgraded)


def _gated_by_agent_signal(company: str, title: str, body: str, role_family: str) -> dict:
    """Final gate after title-based role_family classification.

    User's target market (from _profile/target-roles.md) requires JDs that
    talk about agents in production — not just titles that say "AI Engineer."
    A JD body with ZERO agent-related terms is almost always a generic
    ML/RAG/data-science role mis-titled, which the user doesn't want.

    Applied to in-scope agent-engineer / applied-ai / infra-llm classifications
    only; SWE family roles (swe-backend, swe-fullstack, swe-frontend) pass
    through unfiltered because they may be agent-eng IC roles posted under
    generic SWE titles at AI-native companies (Sierra "Software Engineer,
    Product" is real).

    Sets `agent_signal_count` in state so downstream nodes (vault_write,
    score) can tag/weight by signal strength.
    """
    signal_count = _agent_signal_count(body)
    agent_oriented = role_family in {"agent-engineer", "applied-ai", "infra-llm"}
    if agent_oriented and signal_count == 0:
        _log_filtered(company, title, "no-agent-signal in body")
        logger.info(
            "intake_filter: dropped %s — %s (agent-oriented title but body has no agent signal)",
            company,
            title,
        )
        return {
            "in_scope": False,
            "role_family": "out-of-scope",
            "agent_signal_count": 0,
        }
    return {
        "in_scope": True,
        "role_family": role_family,
        "agent_signal_count": signal_count,
    }
