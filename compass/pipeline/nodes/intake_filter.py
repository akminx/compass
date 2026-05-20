"""intake_filter_node — role-family gate.

Runs BEFORE extract so out-of-scope JDs never burn an LLM extract+score call.

Pipeline cost optimization: this saves ~$0.003 per dropped JD (skipping
extract+score+tailor) for the ~30–50% of postings on most boards that are
sales / PM / design / CS. With MAX_JOBS_PER_RUN=50, that's ~$0.10/day saved.

More importantly: it fixes the gap-aggregator bias introduced by Phase 0.B's
SCORE_THRESHOLD write-gate. Now ALL in-scope JDs reach the vault regardless
of current match score, so stretch-role gaps (the ones the candidate should
be studying toward) actually drive the master gap plan.
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
# mirrors the "AND" clause in _profile/target-roles.md::JD-master-boolean.
#
# Tiered to avoid false positives:
#
# STRONG signals are unambiguous — they only appear in JDs that actually
# describe agent/LLM-platform work. At least ONE strong signal is required
# for the gate to pass on an agent-oriented title.
#
# WEAK signals (just "agent" / "agents" / "agentic" on their own) are noisy:
# every corporate JD has phrases like "be a change agent", "user-agent header",
# "outage management agent". Weak hits are tracked for the auto-tag (so the
# dashboard can surface JDs with rich agentic language) but DON'T satisfy the
# gate on their own.
_AGENT_STRONG_TERMS = [
    # === Agent-system terms (original spine) ===
    r"\bagent[-\s]?orchestration\b",
    r"\bmulti[-\s]?agent\b",
    r"\bagentic\s+(ai|workflows?|systems?|engineering)\b",
    r"\bai\s+agent[s]?\b",
    r"\bllm\s+agent[s]?\b",
    r"\bmcp\b",
    r"\bmodel context protocol\b",
    r"\blanggraph\b",
    r"\blangchain\b",
    r"\bpydantic\s+ai\b",
    r"\bagents\s+sdk\b",
    r"\bopenai\s+agents\b",
    r"\bcrewai\b",
    r"\bautogen\b",
    r"\bdspy\b",
    r"\bautonomous\s+agent[s]?\b",
    r"\bsub[-\s]?agents?\b",
    r"\bagent[-\s]?reliability\b",
    r"\bagent\s+evaluation\b",
    r"\bagent\s+platform\b",
    r"\bagent\s+framework\b",
    r"\bagent\s+development\b",
    r"\bagent\s+system\b",
    r"\btool[-\s]?calling\b",
    r"\bfunction[-\s]?calling\b",
    r"\bdurable\s+execution\b",
    # === LLM products / vendors ===
    r"\bopenai\s+api\b",
    r"\banthropic\s+api\b",
    r"\bclaude\s+api\b",
    r"\bgpt[-\s]?[0-9]\b",
    r"\bllama\s+[0-9]\b",
    r"\bgemini\s+(api|pro|2)\b",
    r"\bvertex\s+ai\b",
    r"\baws\s+bedrock\b",
    r"\bgenerative\s+ai\b",
    r"\bgenai\b",
    r"\bgen[-\s]?ai\b",
    r"\blarge\s+language\s+model[s]?\b",
    # === RAG / retrieval / vector ===
    r"\brag\b",
    r"\bretrieval[-\s]?augmented\s+generation\b",
    r"\bvector\s+(search|database|store|index|embedding[s]?)\b",
    r"\bsemantic\s+search\b",
    r"\bembedding[s]?\b",
    r"\bpinecone\b",
    r"\bchroma(db)?\b",
    r"\bweaviate\b",
    r"\bqdrant\b",
    r"\bmilvus\b",
    r"\bllamaindex\b",
    r"\bllama[-\s]?index\b",
    # === Prompt eng / fine-tune / training ===
    r"\bprompt\s+engineering\b",
    r"\bprompt\s+optimization\b",
    r"\bfine[-\s]?tun(e|ing)\b",
    r"\binstruction[-\s]?tuning\b",
    r"\blora\b",
    r"\brlhf\b",
    # === Eval / observability ===
    r"\blangfuse\b",
    r"\blangsmith\b",
    r"\bbraintrust\b",
    r"\bdeepeval\b",
    r"\bragas\b",
    r"\bllm[-\s]?as[-\s]?(a[-\s]?)?judge\b",
    r"\bllm\s+evaluation\b",
    r"\bmodel\s+evaluation\b",
    # === Inference / serving ===
    r"\bvllm\b",
    r"\bsglang\b",
    r"\btriton\s+inference\b",
    r"\bray\s+serve\b",
    r"\bmodel\s+serving\b",
    r"\binference\s+(optimization|serving|engine|platform)\b",
]
_AGENT_WEAK_TERMS = [
    r"\bagentic\b",
    r"\bagents?\b",
]
_AGENT_STRONG_RE = re.compile("|".join(_AGENT_STRONG_TERMS), re.IGNORECASE)
_AGENT_WEAK_RE = re.compile("|".join(_AGENT_WEAK_TERMS), re.IGNORECASE)


def _agent_signal_count(body: str) -> int:
    """Combined unique-hit count across strong + weak terms — preserved as the
    `agent_signal_count` exposed in state for downstream tagging. The gate
    uses `_has_strong_agent_signal` instead for the actual drop decision."""
    if not body:
        return 0
    hits = {m.group(0).lower() for m in _AGENT_STRONG_RE.finditer(body)}
    hits |= {m.group(0).lower() for m in _AGENT_WEAK_RE.finditer(body)}
    return len(hits)


def _has_strong_agent_signal(body: str) -> bool:
    """True iff the body contains at least one STRONG agent term. This is the
    gate criterion — weak terms ("agent" / "agentic" alone) don't satisfy.

    Without this, JDs containing phrases like "be a change agent in our team"
    or "set the User-Agent header" survive the gate on weak signal alone.
    """
    if not body:
        return False
    return bool(_AGENT_STRONG_RE.search(body))


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
            return {"in_scope": False, "role_family": "out-of-scope", "agent_signal_count": 0}
    for needle in rules["jd"]:
        if needle and needle in body_lc:
            _log_filtered(job.company, job.title, f"jd rejects: {needle!r}")
            logger.info(
                "intake_filter: dropped %s — %s (jd rule: %r)",
                job.company,
                job.title,
                needle,
            )
            return {"in_scope": False, "role_family": "out-of-scope", "agent_signal_count": 0}

    # Location gate — preferences.md lists US cities + Remote-US as preferred /
    # acceptable. Drop unambiguous non-US locations BEFORE the LLM stage. The
    # check is conservative: ambiguous strings ("Remote", "Multiple Locations",
    # "") pass through. See compass/pipeline/location_filter.py.
    from compass.pipeline.location_filter import is_us_compatible

    keep, loc_reason = is_us_compatible(job.location)
    if not keep:
        _log_filtered(job.company, job.title, loc_reason)
        logger.info(
            "intake_filter: dropped %s — %s (%s)",
            job.company,
            job.title,
            loc_reason,
        )
        return {"in_scope": False, "role_family": "out-of-scope", "agent_signal_count": 0}

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

    The candidate target is AI/agentic engineering specifically — not generic
    SWE work at AI-adjacent companies. So we require at least one STRONG
    signal in the JD body (LangGraph / MCP / RAG / vector search / fine-tuning
    / LLM API / etc.) for the job to be in scope.

    Applies to ALL in-scope role families (agent-engineer, applied-ai,
    infra-llm, swe-backend, swe-fullstack, swe-frontend, swe-mobile, fde-eng,
    other-eng). Pre-fix this only gated AI-titled roles, letting generic
    SWE-titled roles at AI-adjacent companies through without any AI body
    language.

    Sets `agent_signal_count` in state so downstream nodes (vault_write,
    score) can tag/weight by signal strength.
    """
    signal_count = _agent_signal_count(body)
    has_strong = _has_strong_agent_signal(body)
    if not has_strong:
        _log_filtered(company, title, "no-strong-agent-signal in body")
        logger.info(
            "intake_filter: dropped %s — %s (role_family=%s; body has no strong AI/agent signal; signal_count=%d)",
            company,
            title,
            role_family,
            signal_count,
        )
        return {
            "in_scope": False,
            "role_family": "out-of-scope",
            "agent_signal_count": signal_count,
        }
    return {
        "in_scope": True,
        "role_family": role_family,
        "agent_signal_count": signal_count,
    }
