"""
score_node — score a job against the candidate profile.

Profile context is the full resume plus top-k chunks retrieved from the
skill-inventory Chroma index, queried with the JD's skills + summary.
Returns a JobScore (0.0–5.0) with matched/missing/tailoring breakdown.

Model: SCORE_MODEL (default google/gemini-2.5-flash).
"""

from __future__ import annotations

import functools
import logging

from compass.config import CALIBRATOR_ENABLED, SCORE_ENSEMBLE_N, SCORE_THRESHOLD
from compass.evals.calibrator import apply as _calibrator_apply
from compass.evals.calibrator import load as _calibrator_load
from compass.llm import make_agent
from compass.pipeline.state import CompassState, JobRequirements, JobScore, RawJob
from compass.rag.retriever import retrieve as rag_retrieve
from compass.vault.reader import read_resume
from compass.vault.target_companies import get_company_meta

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You score a job description against a candidate's profile.

Score 0.0–5.0:
- 5.0 = perfect match, candidate has every required skill at production level
- 4.0 = strong match, candidate has ~80% of required skills with real evidence
- 3.0 = decent match, candidate has core skills but missing some required ones
- 2.0 = stretch, candidate has adjacent skills but lacks several required ones
- 1.0 = poor match, fundamental skill gaps
- 0.0 = wrong field entirely

Calibration:
- Use the FULL 0–5 range. A 3.5 means "realistic apply" — don't hedge it down to 3.0.
- A candidate with most required skills + evidence of building real systems with them
  is a 4.0, not a 3.5. Reserve 5.0 for exact-stack matches at the right seniority.
- Use 0.25 granularity (3.25, 3.75) when between rubric anchors — flat .0/.5 clustering
  is a calibration smell.
- "Conceptual but not shipped" knocks ONE skill down, not the whole score. Score the
  whole-candidate fit, not the worst gap.

HARD GATES — cap the score regardless of stack overlap when ANY of these
multi-year hands-on prerequisites appear. These are not "minor gaps" — they
are deal-breakers a strong stack cannot offset:

- 5+ years of CUDA / GPU kernel programming / vLLM-Triton-TensorRT internals
  → cap at 1.5 (multi-year hands-on, not learnable in interview prep)
- 5+ years of Rust systems programming / Linux kernel / eBPF / runc / Firecracker
  → cap at 1.5
- 5+ years of embedded firmware / FreeRTOS / real-time OS / ARM bring-up
  → cap at 0.5 (entirely different discipline)
- Senior frontend specialization (5+ yr React + editor frameworks like
  Slate/Lexical/ProseMirror, or "pixel-perfect" + design-system fluency)
  → cap at 0.75 (candidate is not a frontend specialist)
- Staff / Principal / Distinguished engineer titles when YoE ask >= 7
  → cap at 1.75 (severe over-level; candidate is L3 equivalent)

Do NOT trigger these gates on "Deployed Engineer", "Solutions Architect",
"Forward Deployed Engineer", or "GTM Engineer" — those are handled by the
role-family cap, not by hard-gate logic, and read as 2.5–3.25 strong-stack
matches per the rubric above.

These gates apply AFTER all other rubric and YoE logic. Clearance gates
(US Secret / TS/SCI / Public Trust) are enforced in code, not in this
prompt — you don't need to look for them.

INCLUSIVE READING OF JD REQUIREMENTS (do not treat reqs as strict checklists):
- "particularly X and Y" / "X or Y" / "such as X, Y, or Z" → preference, not gate.
  If the candidate has ANY one of the listed items, that requirement is met.
  Example: "particularly Java and Python" — strong Python alone satisfies this.
  Example: "Azure preferred; AWS or GCP acceptable" — AWS basic satisfies this.
- "Including X" with a list of examples → X is an example, not a literal gate.
  Example: "relational and NoSQL datastores, including Cassandra" — any SQL +
  any NoSQL (MongoDB, Firebase, Redis) satisfies this; Cassandra is not required.
- "Bonus" / "nice-to-have" / "preferred" requirements NEVER drag a score DOWN.
  Their only effect is to push a score UP when satisfied.
- Concepts that are 1–2 weeks of focused study (a new framework, a vector DB
  variant, a new prompting pattern, a specific MLOps tool) are NOT meaningful
  gaps for a candidate who has demonstrated the underlying concept elsewhere
  (e.g., "no Pinecone but shipped Chroma" is a 1-week ramp).
- Multi-year skills are real gaps: CUDA / GPU programming, deep Rust systems
  work, on-device ML kernels, specific security clearances, embedded firmware,
  staff-level distributed systems experience.

ROLE-FAMILY FIT IS THE PRIMARY SIGNAL:
- If the role family matches the candidate's targets (agent-engineer, applied-AI,
  AI-platform, MTS at frontier labs, L3/L4 agentic at big-tech, devtools-AI,
  junior agent-eng), default to the HIGH end of the rubric band. Strong stack
  + in-target role-family = 3.5+, not 2.75.
- Category-mismatch is the dominant penalty: frontend specialist, embedded
  firmware, EM track, customer-success engineer, hardware-clearance gates.
  A category-mismatch caps the score around 1.5–2.0 regardless of stack overlap.
- FDE / Deployed-Engineer / Forward-Deployed roles are softer-no for this
  candidate (no formal customer-facing pre-sales background) — score them at
  3.0–3.25 when the stack overlap is strong, NOT 2.0. Strict "no" only when
  the role title is literally "FDE" AND on-site/clearance gates also apply.

YEARS-OF-EXPERIENCE NUDGE (small, offsettable):
The JD's `years_experience` is the minimum-years ask. Compare against the
candidate's actual YoE (from the profile). The penalty is intentionally small
because exact-stack match can offset YoE in real hiring loops — deployed-
engineer / agent-engineer roles in particular often hire below the nominal YoE
when the candidate has shipped the exact stack.

Base nudge (applied AFTER rubric anchors):
- candidate YoE >= ask:                no nudge
- candidate YoE = ask - 1 or - 2:      subtract 0.25
- candidate YoE = ask - 3 or - 4:      subtract 0.5
- candidate YoE <= ask - 5:            subtract 0.75

Offsets (REDUCE the nudge by this much):
- Candidate has shipped 2+ of the JD's required tools at production:  +0.25
- Candidate has the exact-stack signal the JD describes (e.g., MCP    +0.25
  servers for an MCP role, LangGraph for a LangGraph role):
- Role tier is "apply-now" with case/hackerrank loop (loop > YoE):    +0.25

Cap the net nudge at 0 (never positive). If `years_experience` is None or
0, skip entirely. The point is to dampen "100% skill + half the YoE" from
scoring 4.5 down to a more realistic 3.5–4.0 — NOT to crater it to 2.5.

Return a JobScore with:
- score: float 0.0–5.0
- reasoning: 2–3 sentences justifying the score
- matched_skills: skills from the JD's required+nice-to-have list that the candidate has (level >= 2)
- missing_skills: skills from the JD's required+nice-to-have list that the candidate lacks (level < 2)
- tailoring_notes: ONE sentence suggesting how to frame the application (skip if score < 3.0)
- evidence: dict[str, str] mapping EVERY skill in matched_skills and missing_skills
  to a 5–15 word VERBATIM phrase from the JD that names the skill or asks for it.
  Example: {"LangGraph": "build agents using LangGraph and LangSmith", "CUDA": "experience with CUDA / Triton programming"}.
  This grounds each classification in the JD's own words. Skip evidence for a skill
  only if the JD's mention is too long to quote in 15 words (rare).

SECONDARY SIGNAL — company targeting context:
The job's company carries a tier classification from the candidate's strategic
target list (apply-now / opportunistic / backend-prep / stretch / skip), an
interview-loop difficulty (hackerrank / case / lc-easy / lc-medium / lc-hard /
takehome), and the candidate's notes about why the company matters. When that
context is provided in the JOB BLOCK below, use it as ONE input to the score —
not the dominant one. Skill match is still primary. But:
- An `apply-now` company with an `lc-easy` or `hackerrank` or `case` loop is a
  realistic landing — don't under-score those just because the candidate has
  gaps; tailoring + interview prep can close them.
- An `opportunistic` or `backend-prep` company with an `lc-hard` loop is a
  stretch — score those honestly even if skill match looks strong, since the
  loop will be the actual blocker.
- The `notes` field tells you why the candidate cares — use it for the
  tailoring_notes if the score is >= 3.

HARD CONSTRAINTS on matched_skills and missing_skills:
1. Every skill in matched_skills MUST appear in the JD's required or nice_to_have list. Do NOT list skills from the candidate's profile that the JD did not ask for.
2. Every skill in missing_skills MUST appear in the JD's required or nice_to_have list. Do NOT list every skill in the canonical taxonomy that the candidate lacks.
3. The union (matched_skills ∪ missing_skills) MUST be a subset of the JD's required ∪ nice_to_have lists.
4. If the JD has no required or nice_to_have skills, matched_skills and missing_skills MUST both be empty lists.

Use the EXACT skill names from the JD's required/nice_to_have lists (don't paraphrase).

CALIBRATION EXAMPLES (apply this calibration, don't just acknowledge it):

Example 1 — exact-stack tier-2 agentic startup, candidate below YoE:
  JD: "Deployed Engineer, LangChain — work with customers shipping LangGraph
       agents in production. 3+ yrs eng experience. Bonus: MCP, evals."
  Candidate: ~2y YoE; shipped multiple production MCP servers at a
       previous role; built a LangGraph + Pydantic AI agentic pipeline
       with Langfuse traces.
  → score: 4.25  (rubric: 5.0 perfect-stack − 0.25 YoE nudge + 0.0 net offset.
                  Exact-stack + shipped match the rubric's "4.0 = strong match
                  with real evidence" anchor; the YoE gap is small for a
                  deployed-engineer loop.)

Example 2 — adjacent-stack tier-2 SaaS, candidate has 80% skill match:
  JD: "Senior Software Engineer — Python, REST APIs, Postgres, AWS.
       5+ yrs. Bonus: LangChain experience."
  Candidate: ~2y YoE; Python + FastAPI + Postgres + AWS Lambda in
       production. Some LangChain in side projects, no production.
  → score: 3.0   (skill match strong but YoE several years short → -0.5 base;
                  no exact-stack offset because LangChain is bonus-only.
                  Rubric "decent match with core skills, missing some required"
                  applies; the YoE gap drags it from 3.5 to 3.0.)

Example 3 — tier-3 systems/infra role, candidate domain mismatch:
  JD: "ML Engineer — Inference Engine. PyTorch, vLLM, CUDA, distributed
       systems, 3+ yrs HPC. Build production inference services."
  Candidate: ~2y YoE; Python + PyTorch from coursework; no CUDA, no
       inference engine experience, no distributed systems work.
  → score: 1.5   (only matches Python + PyTorch; missing all core
                  infrastructure skills; YoE gap exists but isn't the primary
                  blocker — the skill mismatch is. Rubric "stretch with
                  adjacent skills but lacks several required" applies.)

Example 4 — tier-3 big-tech generalist SWE, candidate adjacent:
  JD: "Software Engineer — backend services. Java/Kotlin, distributed
       systems, 2+ yrs. Some AI work a plus."
  Candidate: ~2y YoE; Python-primary, no Java production; built a
       single-machine LangGraph pipeline (not distributed); MCP/agents.
  → score: 2.5   (rubric "stretch, adjacent skills but lacks several
                  required" — Java + distributed systems are foundational
                  and the candidate lacks both. AI work is a plus, not a
                  primary signal.)

Example 5 — anti-fit, off-target role:
  JD: "Senior Frontend Engineer — React, TypeScript, design systems.
       5+ yrs frontend experience."
  Candidate: ~2y YoE backend/AI; no frontend production, basic TypeScript.
  → score: 1.0   (rubric "poor match, fundamental skill gaps" —
                  category mismatch, not just YoE.)

PATTERN: the residual under-scoring on exact-stack matches has been the
biggest calibration error. When the candidate has SHIPPED the exact tools
the JD asks about (MCP, LangGraph, agent frameworks), score in the 4.0+
range even when YoE is below ask. Reserve scores below 3.0 for true
skill-mismatch or category-mismatch cases, NOT for "good skills, light YoE."
"""


@functools.cache
def _build_agent():
    return make_agent("score", output_type=JobScore, system_prompt=_SYSTEM_PROMPT)


def _company_context_block(job: RawJob | None) -> str:
    """Render the company's YAML targeting metadata as a prompt block. Empty
    string when the company isn't in the user's target list — the LLM scores
    purely on skill match in that case (likely a JD that landed via fallback
    config, not the YAML)."""
    if job is None:
        return ""
    meta = get_company_meta(job.company)
    if not meta:
        return ""
    return (
        "# COMPANY TARGETING CONTEXT\n"
        f"company: {job.company}\n"
        f"tier: {meta.get('tier') or 'unknown'}\n"
        f"interview_difficulty: {meta.get('interview_difficulty') or 'unknown'}\n"
        f"section: {meta.get('section') or 'unknown'}\n"
        f"notes: {meta.get('notes') or '(none)'}\n\n"
    )


def _format_prompt(req: JobRequirements, profile_text: str, job: RawJob | None) -> str:
    return (
        f"# CANDIDATE PROFILE\n{profile_text}\n\n"
        f"{_company_context_block(job)}"
        f"# JOB REQUIREMENTS\n"
        f"required: {', '.join(req.required_skills) or '(none)'}\n"
        f"nice-to-have: {', '.join(req.nice_to_have_skills) or '(none)'}\n"
        f"years_experience: {req.years_experience}\n"
        f"seniority: {req.seniority}\n"
        f"remote_policy: {req.remote_policy}\n"
        f"summary: {req.summary}\n"
    )


async def _score(req: JobRequirements, profile_text: str, job: RawJob | None = None) -> JobScore:
    # Tests patch this function; the underlying pydantic-ai Agent is harder to stub.
    agent = _build_agent()
    result = await agent.run(_format_prompt(req, profile_text, job))
    return result.output


def _reasoning_complete(text: str) -> bool:
    """Gemini Flash occasionally streams a truncated reasoning string that ends
    mid-clause (e.g. "...entirely outside the candidate"). The structured-output
    schema doesn't catch this because any non-empty string is valid. Cheap check:
    require at least 20 chars and a terminal punctuation mark."""
    t = (text or "").strip()
    return len(t) >= 20 and t[-1] in '.!?"'


async def _score_with_retry(
    req: JobRequirements, profile_text: str, job: RawJob | None = None
) -> JobScore:
    result = await _score(req, profile_text, job)
    if _reasoning_complete(result.reasoning):
        return result
    logger.warning(
        "score_node: reasoning looks truncated (%d chars, tail=%r) — retrying once",
        len(result.reasoning or ""),
        (result.reasoning or "")[-40:],
    )
    retry = await _score(req, profile_text, job)
    if not _reasoning_complete(retry.reasoning):
        logger.warning("score_node: retry still produced incomplete reasoning — accepting anyway")
    return retry


# Score caps by role family. The intent is to dampen the over-scoring tail
# the eval surfaced: out-of-scope JDs (CS engineer, data engineer, embedded)
# scored +1.5 to +1.75 above what a strict judge gave them, because the
# Python/SQL/AWS overlap with the candidate profile is enough to push the
# scorer into the 2.5–3.0 band. These caps gate the score AFTER the LLM runs
# so the LLM's reasoning is still informative for the user, but the number
# can't escape the realistic ceiling for that role family.
ROLE_FAMILY_SCORE_CAP: dict[str, float] = {
    "out-of-scope": 1.5,
    "swe-mobile": 2.5,  # mobile is out-of-scope per role-clarifications
    "swe-frontend": 2.5,  # frontend-only roles are out-of-scope
    # FDE / Deployed-Engineer: softer-no, strong-stack matches around 3.0–3.25.
    "fde-eng": 3.25,
    # Other-eng (everything the LLM classifier wasn't sure about) gets a soft
    # cap that's high enough not to catch genuine agent-eng roles the
    # classifier mislabeled, but low enough to prevent a generic-backend JD
    # from sneaking into the "apply" tier on Python overlap alone. Note:
    # swe-backend / swe-fullstack are INTENTIONALLY NOT capped here — many
    # real L4 agentic-platform roles ship at big-tech under generic SWE
    # titles (we saw this in the eval), and the body-upgrader handles
    # promotion via `upgrade_family` for AI-rich JDs.
    "other-eng": 3.0,
}


def _apply_role_family_cap(score: JobScore, role_family: str | None) -> JobScore:
    """Cap the score when the role family doesn't fit the candidate's target."""
    if not role_family:
        return score
    cap = ROLE_FAMILY_SCORE_CAP.get(role_family)
    if cap is None or score.score <= cap:
        return score
    logger.info(
        "score_node: capping score %.2f → %.2f for role_family=%s",
        score.score,
        cap,
        role_family,
    )
    return score.model_copy(
        update={
            "score": cap,
            "reasoning": f"[capped at {cap} for role_family={role_family}] {score.reasoning}",
        }
    )


# Phrases that signal an explicit clearance / citizenship requirement in the JD
# body. Matched case-insensitively as substrings — false positives are
# acceptable here (a JD that mentions "clearance" as a benefit description
# without requiring one is rare), and the cost of a false positive is one
# under-scored job, vs the cost of a false negative being a 3.0 score on a
# job the candidate can't even apply to.
_CLEARANCE_GATES: tuple[str, ...] = (
    "secret clearance",
    "top secret clearance",
    "ts/sci",
    "active clearance",
    "u.s. government secret",
    "us government secret",
    "public trust clearance",
    "polygraph clearance",
    "must be a u.s. citizen",
    "must be a us citizen",
    "u.s. citizenship is required",
    "us citizenship is required",
    "u.s. citizenship and eligibility",
    "us citizenship and eligibility",
)

# When a clearance gate fires, cap the score at this level — clearance is a
# multi-year hands-on prerequisite that no amount of stack overlap can offset
# for an applicant who doesn't already have one.
_CLEARANCE_GATE_CAP = 1.5


def _apply_clearance_gate(score: JobScore, jd_text: str) -> JobScore:
    """Deterministic JD-body scan for clearance/citizenship gates.

    The scorer prompt asks the LLM to honor these, but flash-tier models drop
    that instruction unreliably on dense JDs. A code-level scan guarantees the
    cap fires — much more reliable than trusting prompt adherence on a low-
    frequency signal that's structurally important.
    """
    if score.score <= _CLEARANCE_GATE_CAP:
        return score
    body = (jd_text or "").lower()
    matched = next((g for g in _CLEARANCE_GATES if g in body), None)
    if matched is None:
        return score
    logger.info(
        "score_node: clearance gate fired (%r) — capping %.2f → %.2f",
        matched,
        score.score,
        _CLEARANCE_GATE_CAP,
    )
    return score.model_copy(
        update={
            "score": _CLEARANCE_GATE_CAP,
            "reasoning": f"[clearance gate: {matched!r}] {score.reasoning}",
        }
    )


async def _score_ensemble(
    req: JobRequirements,
    profile_text: str,
    job: RawJob | None,
    *,
    n: int = 3,
) -> JobScore:
    """Self-consistency for the scorer: run N times at temp=0, take the median
    score + majority-vote matched/missing skills + reasoning from the verdict
    closest to the median.

    Mirrors `compass.evals.judge.judge_jd`'s ensemble logic. Even at temp=0,
    the OpenRouter provider + structured-output retry can produce small
    variance run-to-run. The ensemble compresses random-noise MAE while
    preserving the scorer's "shape" — bias and rank ordering are unchanged.

    Use `n=1` to disable (production default, controlled by SCORE_ENSEMBLE_N).
    """
    import statistics

    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")

    # Run all samples in parallel — they're independent calls at temp=0; the
    # whole point of the ensemble is to smooth provider-side variance, not to
    # sequence anything. Wall-clock latency stays roughly equal to a single call.
    import asyncio as _asyncio

    if n == 1:
        return await _score_with_retry(req, profile_text, job)
    verdicts: list[JobScore] = await _asyncio.gather(
        *[_score_with_retry(req, profile_text, job) for _ in range(n)]
    )

    scores = [v.score for v in verdicts]
    median_score = statistics.median(scores)

    # Majority vote on matched/missing — keep a skill that appears in at
    # least ceil(N/2) verdicts. Filters out one-off LLM noise without
    # losing skills that the scorer is genuinely confident about.
    threshold = (n + 1) // 2
    matched_counts: dict[str, int] = {}
    matched_form: dict[str, str] = {}
    missing_counts: dict[str, int] = {}
    missing_form: dict[str, str] = {}
    evidence_pool: dict[str, str] = {}
    for v in verdicts:
        for s in v.matched_skills:
            k = s.lower()
            matched_counts[k] = matched_counts.get(k, 0) + 1
            matched_form.setdefault(k, s)
        for s in v.missing_skills:
            k = s.lower()
            missing_counts[k] = missing_counts.get(k, 0) + 1
            missing_form.setdefault(k, s)
        for skill, quote in (v.evidence or {}).items():
            # Keep the first quote we see for each skill — verdicts agree
            # closely on quotes when they agree on the skill at all.
            evidence_pool.setdefault(skill.lower(), quote)

    matched_majority = [matched_form[k] for k, c in matched_counts.items() if c >= threshold]
    missing_majority = [
        missing_form[k]
        for k, c in missing_counts.items()
        if c >= threshold
        and k not in {kk for kk in matched_counts if matched_counts[kk] >= threshold}
    ]
    closest = min(verdicts, key=lambda v: abs(v.score - median_score))
    # Restrict evidence to the surviving skills.
    surviving_keys = {s.lower() for s in (*matched_majority, *missing_majority)}
    evidence_out = {
        closest_form: evidence_pool[lk]
        for lk, closest_form in {**matched_form, **missing_form}.items()
        if lk in surviving_keys and lk in evidence_pool
    }

    return JobScore(
        score=median_score,
        reasoning=f"[ensemble-{n} median] {closest.reasoning}",
        matched_skills=matched_majority,
        missing_skills=missing_majority,
        tailoring_notes=closest.tailoring_notes,
        evidence=evidence_out,
    )


async def _profile_text(req: JobRequirements) -> str:
    """Build candidate-profile context for the score prompt.

    Resume stays inline; the prior full skill-inventory inject is now top-k
    chunks retrieved against the JD's skills + summary.
    """
    query_parts = [*req.required_skills, *req.nice_to_have_skills]
    if req.summary:
        query_parts.append(req.summary)
    query = " ".join(query_parts).strip()

    chunks = await rag_retrieve(query, k=8) if query else []

    profile = f"## RESUME\n{read_resume()}"
    if chunks:
        ranked = "\n\n".join(c.document for c in chunks)
        profile += f"\n\n## RELEVANT SKILLS (top-{len(chunks)} by similarity)\n{ranked}"
    return profile


async def score_node(state: CompassState) -> dict:
    req = state.get("extracted_requirements")
    if req is None:
        # All three return paths in this node set `score_threshold` so
        # `hitl_node`'s fallback fires consistently regardless of which
        # path triggered the early exit.
        return {
            "score_result": None,
            "errors": [*state.get("errors", []), "score_node: extracted_requirements is None"],
            "score_threshold": SCORE_THRESHOLD,
        }

    try:
        profile = await _profile_text(req)
        result = await _score_ensemble(req, profile, state.get("current_job"), n=SCORE_ENSEMBLE_N)
    except Exception as e:
        logger.exception("score_node: LLM call failed")
        return {
            "score_result": None,
            "errors": [*state.get("errors", []), f"score_node: {type(e).__name__}: {e}"],
            "score_threshold": SCORE_THRESHOLD,
        }

    constrained = _constrain_to_jd_skills(result, req)
    family_capped = _apply_role_family_cap(constrained, state.get("role_family"))
    job = state.get("current_job")
    clearance_capped = _apply_clearance_gate(
        family_capped, job.description if job is not None else ""
    )
    calibrated = _apply_calibrator(clearance_capped)
    return {
        "score_result": calibrated,
        "score_threshold": SCORE_THRESHOLD,
    }


def _apply_calibrator(score: JobScore) -> JobScore:
    """Apply the isotonic calibrator to the score, if one has been fit AND
    `CALIBRATOR_ENABLED=1` is set in the environment.

    Opt-in by design: tests, debugging runs, and the eval harness (when
    measuring the un-calibrated scorer's contribution) all want to bypass
    the calibrator. Production sets the env var.

    Loaded lazily and memoized at module level — re-reading the JSON on every
    score call would dominate the per-call cost. To re-fit and pick up changes,
    run `python -m compass.evals.calibrator fit` and restart the process.
    """
    if not CALIBRATOR_ENABLED:
        return score
    cal = _get_calibrator()
    if cal is None:
        return score
    adjusted = _calibrator_apply(cal, score.score)
    if abs(adjusted - score.score) < 0.005:
        return score
    logger.info(
        "score_node: calibrator adjusted %.2f → %.2f (n=%d training pairs)",
        score.score,
        adjusted,
        cal.n_training_pairs,
    )
    return score.model_copy(
        update={
            "score": round(adjusted, 2),
            "reasoning": f"[calibrated {score.score:.2f}→{adjusted:.2f}] {score.reasoning}",
        }
    )


@functools.cache
def _get_calibrator():
    """Memoized load of the isotonic calibrator from disk. Mirrors the
    `taxonomy.refresh()` pattern: call `_get_calibrator.cache_clear()` to
    pick up a fresh fit without restarting the process — necessary for the
    long-running MCP server when the user runs
    `python -m compass.evals.calibrator fit` in another shell.
    """
    return _calibrator_load()


def _constrain_to_jd_skills(score: JobScore, req: JobRequirements) -> JobScore:
    """Defense in depth: drop matched/missing skills the JD didn't actually ask for,
    AND remove any skill that appears in BOTH matched and missing (matched wins).

    The score prompt forbids the LLM from inventing matched/missing skills
    outside the JD's required+nice_to_have lists. This filter enforces the
    same constraint at code-level. Gemini Flash also occasionally puts a
    borderline skill in both lists — without dedup, gap_aggregator would
    count the skill as a gap even though it's also "matched". We resolve
    overlaps in favor of matched (the LLM is more likely to over-flag gaps
    than over-claim matches).

    CANONICAL FOLDING: The LLM occasionally emits a JD-raw phrase ("LangGraph
    framework", "pydantic-ai") while the extract layer canonicalized the same
    skill ("LangGraph", "Pydantic AI"). An exact-string subset check would
    drop the legitimate match. We fold BOTH sides through `taxonomy.normalize`
    before the subset check, then return the SCORE's spelling (so downstream
    consumers see the LLM's chosen form, not the canonical, in matched_skills
    — that matters for tailoring_notes which references matched skills).
    """
    from compass.vault.taxonomy import normalize as _canon

    def _key(s: str) -> str:
        # Fold to canonical; fall back to lowercased raw if not in taxonomy.
        return (_canon(s) or s).lower()

    jd_universe_keys = {_key(s) for s in (*req.required_skills, *req.nice_to_have_skills)}

    matched_keys: set[str] = set()
    matched_out: list[str] = []
    for s in score.matched_skills:
        k = _key(s)
        if k in jd_universe_keys and k not in matched_keys:
            matched_keys.add(k)
            matched_out.append(s)

    missing_out: list[str] = []
    seen_missing: set[str] = set()
    for s in score.missing_skills:
        k = _key(s)
        if k in jd_universe_keys and k not in matched_keys and k not in seen_missing:
            seen_missing.add(k)
            missing_out.append(s)

    dropped_matched = [s for s in score.matched_skills if _key(s) not in jd_universe_keys]
    dropped_missing = [s for s in score.missing_skills if _key(s) not in jd_universe_keys]
    if dropped_matched or dropped_missing:
        logger.info(
            "score_node: dropped %d matched + %d missing skills not in JD universe "
            "(post-canonical-fold). dropped_matched=%s dropped_missing=%s",
            len(dropped_matched),
            len(dropped_missing),
            dropped_matched,
            dropped_missing,
        )
    return score.model_copy(update={"matched_skills": matched_out, "missing_skills": missing_out})
