"""LLM-as-judge — produces synthetic "expected" labels for a JD without
manual annotation.

Use case: you've just done a refresh and have 100 new JobNotes. Hand-labeling
all of them takes hours, but you want a directional signal NOW on whether the
score_node + extract_node are doing the right thing. The judge reads the JD
body + Compass's output and emits its own (skills, score) — which the runner
can compare against Compass.

This is NOT a substitute for hand-labels. Two LLMs may share biases. But it
catches gross failures (e.g. extract_node returning 2 skills when the JD
lists 12) at near-zero cost.

Cost: ~$0.002 per JD on Flash. 100 JDs = $0.20.
"""

from __future__ import annotations

import functools
import logging

from pydantic import BaseModel, Field

from compass.llm import make_agent

logger = logging.getLogger(__name__)


class JudgeVerdict(BaseModel):
    """Structured judgment of one JD."""

    expected_skills: list[str] = Field(
        description="Every distinct technical skill / framework / tool the JD asks for."
    )
    expected_score: float = Field(
        ge=0.0,
        le=5.0,
        description="0-5 estimate of fit between the candidate profile and the JD.",
    )
    reasoning: str = Field(description="2-3 sentence justification.")


_SYSTEM_PROMPT = """You are an independent reviewer evaluating an AI agent's
job-matching output. You are given:
- A raw job description.
- A candidate profile (resume + role-clarifications).
- The agent's own extraction (skills it found) and score (0-5).

Your job is to produce YOUR OWN reading of:
  expected_skills: every distinct technical skill the JD ACTUALLY asks for.
                   List both required and nice-to-have. Use exact phrases from
                   the JD when possible. Do NOT list skills the agent guessed
                   that aren't actually in the JD.
  expected_score: your independent 0-5 score of candidate-to-JD fit. Use the
                  same scale as the agent (5 = perfect match with production
                  evidence; 3 = decent match with some gaps; 1 = poor match).
  reasoning: 2-3 sentences justifying your score, naming the strongest match
             signal and the biggest gap.

Be HONEST. Don't anchor on the agent's numbers — produce your own read first.
If you disagree with the agent, say so plainly in the reasoning.
"""


@functools.cache
def _build_agent():
    # Route judge through REFLECT_MODEL (claude-sonnet) — using the same model
    # for both scorer and judge masks shared biases (under-scoring, taxonomy
    # blind-spots). A stronger, different-family judge is a more honest signal.
    return make_agent("reflect", output_type=JudgeVerdict, system_prompt=_SYSTEM_PROMPT)


async def judge_jd(
    jd_text: str,
    profile_text: str,
    agent_predicted_skills: list[str],
    agent_predicted_score: float,  # kept in signature for API stability; no longer shown to judge
    *,
    ensemble_n: int = 3,
) -> JudgeVerdict:
    """Single-JD judgment with optional ensembling for stability.

    NOTE: The agent's predicted score is intentionally NOT shown to the judge.
    Anchoring is real even with "don't anchor" instructions; the judge must
    produce its score blind. The skills list IS shown — the judge needs to
    know what the agent extracted in order to fairly assess extract quality.

    ENSEMBLING (`ensemble_n=3`): even at temp=0, the OpenRouter provider
    layer + Sonnet's structured-output retry mechanism can produce small
    variance across runs. We call the judge N times and take the median
    score + the most-frequent skill list. This is industry-standard for
    LLM-as-judge — eliminates the residual provider noise and gives a
    true measurement signal. Cost scales linearly with N; N=3 catches
    most variance, N=5 catches the long tail.

    Set ensemble_n=1 to disable (faster, cheaper, noisier — useful for
    smoke tests or when iterating on the scorer).
    """
    import statistics

    if ensemble_n < 1:
        raise ValueError(f"ensemble_n must be >= 1, got {ensemble_n}")

    agent = _build_agent()
    prompt = (
        f"# CANDIDATE PROFILE\n{profile_text}\n\n"
        f"# JOB DESCRIPTION\n{jd_text}\n\n"
        f"# AGENT EXTRACTION (for skill-list comparison only — no score shown)\n"
        f"agent_extracted_skills: {', '.join(agent_predicted_skills) or '(none)'}\n"
    )

    verdicts: list[JudgeVerdict] = []
    for _ in range(ensemble_n):
        result = await agent.run(prompt, model_settings={"temperature": 0.0})
        verdicts.append(result.output)

    if ensemble_n == 1:
        return verdicts[0]

    # Median score across the N verdicts. Skills: take the union of skills
    # that appear in at least ceil(N/2) verdicts ("majority vote per skill").
    # Reasoning: pick the verdict closest to the median score, so the
    # rationale stays internally consistent with the reported number.
    scores = [v.expected_score for v in verdicts]
    median_score = statistics.median(scores)
    # Skill vote: count each skill across verdicts (case-insensitive), keep
    # those that show up in >= half. Preserves stable JD-skill detection
    # while filtering out one-off LLM noise.
    threshold = (ensemble_n + 1) // 2  # majority
    skill_counts: dict[str, int] = {}
    canonical_form: dict[str, str] = {}  # lowered -> first-seen casing
    for v in verdicts:
        for s in v.expected_skills:
            key = s.lower()
            skill_counts[key] = skill_counts.get(key, 0) + 1
            canonical_form.setdefault(key, s)
    majority_skills = [canonical_form[k] for k, c in skill_counts.items() if c >= threshold]
    closest_verdict = min(verdicts, key=lambda v: abs(v.expected_score - median_score))
    return JudgeVerdict(
        expected_skills=majority_skills,
        expected_score=median_score,
        reasoning=f"[ensemble-{ensemble_n} median] {closest_verdict.reasoning}",
    )
