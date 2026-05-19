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


def _build_agent():
    # Use SCORE_MODEL by default — Gemini Flash is plenty for judging accuracy
    # of another LLM call. Override via env if you want a stronger judge.
    return make_agent("score", output_type=JudgeVerdict, system_prompt=_SYSTEM_PROMPT)


async def judge_jd(
    jd_text: str,
    profile_text: str,
    agent_predicted_skills: list[str],
    agent_predicted_score: float,
) -> JudgeVerdict:
    """Single-JD judgment. Tests patch this function (the pydantic-ai Agent
    itself is harder to stub)."""
    agent = _build_agent()
    prompt = (
        f"# CANDIDATE PROFILE\n{profile_text}\n\n"
        f"# JOB DESCRIPTION\n{jd_text}\n\n"
        f"# AGENT OUTPUT (to be evaluated, not to anchor on)\n"
        f"agent_extracted_skills: {', '.join(agent_predicted_skills) or '(none)'}\n"
        f"agent_score: {agent_predicted_score:.2f}\n"
    )
    result = await agent.run(prompt)
    return result.output
