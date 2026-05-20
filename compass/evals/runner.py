"""Eval runner — runs Compass extract+score on every record in the dataset
and computes aggregate metrics.

Two modes:
  --labels      Compare against `EvalRecord.expected_*` (hand-labeled). Requires
                a populated dataset. Default.
  --judge       Compare against LLM-as-judge output. Cheaper but lower-confidence.
                Useful BEFORE you've hand-labeled anything.

Run:
  uv run python -m compass.evals.runner                       # labels (default)
  uv run python -m compass.evals.runner --judge               # LLM judge
  uv run python -m compass.evals.runner --judge --limit 10    # 10 random JDs

Output: prints a metrics summary to stdout and writes a results JSON to
`compass/evals/results-{mode}-{timestamp}.json`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from compass.evals.dataset import EvalRecord, load_dataset
from compass.evals.metrics import ScoreMetrics, aggregate
from compass.pipeline.nodes.extract import _extract
from compass.pipeline.nodes.score import _score
from compass.pipeline.state import JobRequirements, JobScore, RawJob
from compass.vault.reader import read_profile_section, read_resume

logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).parent


async def _run_extract_and_score(
    record: EvalRecord,
) -> tuple[JobRequirements | None, JobScore | None, float]:
    """Run the SAME extract → score logic the production graph runs, against
    one labeled JD. Returns (req, score, wall_seconds).

    Production fidelity matters here — earlier versions called `_extract` and
    `_score` directly, which skipped the post-LLM normalization and constraint
    layers, making the metrics measure something other than what the user
    actually experiences. Now we apply:

      extract: `_normalize_skill_list` (taxonomy folding) + seniority-from-title
               fallback.  Matches `extract_node`.
      score:   `_score_with_retry` (truncated-reasoning retry) +
               `_constrain_to_jd_skills` (drop hallucinated matched/missing).
               Matches `score_node`.

    We still call `_extract` and `_score` as the patchable surface so tests
    can stub them; the post-processing wraps the stub output.
    """
    from compass.pipeline.nodes.extract import (
        _normalize_skill_list,
        _seniority_with_title_fallback,
    )
    from compass.pipeline.nodes.score import _constrain_to_jd_skills, _reasoning_complete

    start = time.monotonic()
    try:
        raw_req = await _extract(record.jd_text)
    except Exception as e:
        logger.warning("extract failed for %s: %s", record.id, e)
        return None, None, time.monotonic() - start

    # Mirror extract_node: canonicalize skills, fall-back seniority.
    unknown: list[str] = []
    title_hint = ""  # eval JDs don't carry titles — seniority stays as LLM said
    req = JobRequirements(
        required_skills=_normalize_skill_list(raw_req.required_skills, record.jd_text, unknown),
        nice_to_have_skills=_normalize_skill_list(
            raw_req.nice_to_have_skills, record.jd_text, unknown
        ),
        years_experience=raw_req.years_experience,
        seniority=_seniority_with_title_fallback(raw_req.seniority, title_hint),
        remote_policy=raw_req.remote_policy,
        summary=raw_req.summary,
    )

    profile = f"{read_resume()}\n\n{read_profile_section('role-clarifications')}"
    fake_job = RawJob(
        company="(eval)",
        title="(eval)",
        url=f"eval://{record.id}",
        source="manual",
        description=record.jd_text,
    )
    try:
        raw_score = await _score(req, profile, fake_job)
    except Exception as e:
        logger.warning("score failed for %s: %s", record.id, e)
        return req, None, time.monotonic() - start

    # Mirror score_node: retry on truncated reasoning, constrain matched/missing
    # to the JD's actual skill universe. Without this the metric measures
    # un-constrained LLM output rather than what the pipeline actually persists.
    if not _reasoning_complete(raw_score.reasoning):
        logger.info("eval: reasoning looked truncated for %s — retrying once", record.id)
        try:
            raw_score = await _score(req, profile, fake_job)
        except Exception as e:
            logger.warning("score retry failed for %s: %s", record.id, e)
    constrained = _constrain_to_jd_skills(raw_score, req)
    return req, constrained, time.monotonic() - start


async def run_against_labels(records: list[EvalRecord]) -> tuple[ScoreMetrics, list[dict]]:
    """Run Compass on each record, compare to EvalRecord.expected_*."""
    per_record: list[dict] = []
    predicted_scores: list[float] = []
    expected_scores: list[float] = []
    predicted_skill_lists: list[list[str]] = []
    expected_skill_lists: list[list[str]] = []
    matched_skill_lists: list[list[str]] = []

    for r in records:
        req, score, elapsed = await _run_extract_and_score(r)
        if req is None or score is None:
            per_record.append(
                {"id": r.id, "error": "extract or score failed", "elapsed_s": elapsed}
            )
            continue
        extracted_skills = list(req.required_skills) + list(req.nice_to_have_skills)
        predicted_scores.append(score.score)
        expected_scores.append(r.expected_score)
        predicted_skill_lists.append(extracted_skills)
        expected_skill_lists.append(r.expected_skills)
        matched_skill_lists.append(list(score.matched_skills))
        per_record.append(
            {
                "id": r.id,
                "source": r.source,
                "expected_score": r.expected_score,
                "predicted_score": score.score,
                "score_delta": round(score.score - r.expected_score, 2),
                "expected_skills_n": len(r.expected_skills),
                "extracted_skills_n": len(extracted_skills),
                "missed_skills": sorted(
                    {s.lower() for s in r.expected_skills} - {s.lower() for s in extracted_skills}
                ),
                "extra_skills": sorted(
                    {s.lower() for s in extracted_skills} - {s.lower() for s in r.expected_skills}
                ),
                "elapsed_s": round(elapsed, 2),
            }
        )

    metrics = aggregate(
        predicted_scores,
        expected_scores,
        predicted_skill_lists,
        expected_skill_lists,
        matched_skill_lists,
    )
    return metrics, per_record


async def run_against_judge(records: list[EvalRecord]) -> tuple[ScoreMetrics, list[dict]]:
    """Run Compass on each record, compare to an LLM-as-judge verdict.

    No EvalRecord.expected_* needed — the judge produces them on the fly.
    Useful for first-pass sanity checks before you hand-label anything.
    """
    from compass.evals.judge import judge_jd

    profile = f"{read_resume()}\n\n{read_profile_section('role-clarifications')}"

    per_record: list[dict] = []
    predicted_scores: list[float] = []
    expected_scores: list[float] = []
    predicted_skill_lists: list[list[str]] = []
    expected_skill_lists: list[list[str]] = []
    matched_skill_lists: list[list[str]] = []

    for r in records:
        req, score, elapsed = await _run_extract_and_score(r)
        if req is None or score is None:
            per_record.append(
                {"id": r.id, "error": "extract or score failed", "elapsed_s": elapsed}
            )
            continue
        extracted_skills = list(req.required_skills) + list(req.nice_to_have_skills)
        try:
            verdict = await judge_jd(r.jd_text, profile, extracted_skills, score.score)
        except Exception as e:
            per_record.append({"id": r.id, "error": f"judge failed: {e}"})
            continue
        # IMPORTANT: the judge prompt instructs it to use exact phrases from the
        # JD. The JD uses raw forms ("LangGraph", "pydantic-ai"); Compass's
        # extract uses canonical forms ("LangGraph", "Pydantic AI"). Comparing
        # them directly systematically deflates recall on multi-word skills
        # with punctuation variants. Normalize the judge's output through the
        # same taxonomy folding extract_node uses so both sides are canonical.
        from compass.pipeline.nodes.extract import _normalize_skill_list

        judge_skills_canonical = _normalize_skill_list(list(verdict.expected_skills), r.jd_text)
        predicted_scores.append(score.score)
        expected_scores.append(verdict.expected_score)
        predicted_skill_lists.append(extracted_skills)
        expected_skill_lists.append(judge_skills_canonical)
        matched_skill_lists.append(list(score.matched_skills))
        per_record.append(
            {
                "id": r.id,
                "source": r.source,
                "judge_score": verdict.expected_score,
                "predicted_score": score.score,
                "score_delta": round(score.score - verdict.expected_score, 2),
                "judge_skills_n": len(verdict.expected_skills),
                "extracted_skills_n": len(extracted_skills),
                "judge_skills_missed": sorted(
                    {s.lower() for s in verdict.expected_skills}
                    - {s.lower() for s in extracted_skills}
                ),
                "judge_reasoning": verdict.reasoning,
                "elapsed_s": round(elapsed, 2),
            }
        )

    metrics = aggregate(
        predicted_scores,
        expected_scores,
        predicted_skill_lists,
        expected_skill_lists,
        matched_skill_lists,
    )
    return metrics, per_record


def _format_summary(metrics: ScoreMetrics, mode: str) -> str:
    return (
        f"\n=== Eval results ({mode}) ===\n"
        f"  n records:                  {metrics.n}\n"
        f"  score MAE:                  {metrics.score_mae:.2f}    (0 = perfect)\n"
        f"  score RMSE:                 {metrics.score_rmse:.2f}\n"
        f"  score bias (signed):        {metrics.score_bias:+.2f}   (+ = over-scores, - = under-scores)\n"
        f"  extract skill recall:       {metrics.extract_skill_recall:.1%}  (B1 detector)\n"
        f"  extract skill precision:    {metrics.extract_skill_precision:.1%}\n"
        f"  match skill recall:         {metrics.match_skill_recall:.1%}  (score_node attribution accuracy)\n"
    )


async def run_evals(*, mode: str = "labels", limit: int | None = None) -> dict:
    """Programmatic entry point — used by the MCP tool wrapper.

    Returns a dict with `metrics`, `per_record`, and `results_path`.
    """
    records = load_dataset()
    if not records:
        return {
            "error": (
                "labeled_dataset.json is empty. Add examples via "
                "compass.evals.dataset.add_example() or use --judge mode."
            ),
            "metrics": None,
        }
    if limit is not None and limit < len(records):
        records = random.sample(records, limit)

    if mode == "judge":
        metrics, per_record = await run_against_judge(records)
    else:
        metrics, per_record = await run_against_labels(records)

    # Include microseconds so two runs within the same second don't overwrite.
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out_path = RESULTS_DIR / f"results-{mode}-{timestamp}.json"
    out_path.write_text(
        json.dumps(
            {
                "mode": mode,
                "timestamp": timestamp,
                "metrics": {
                    "n": metrics.n,
                    "score_mae": metrics.score_mae,
                    "score_rmse": metrics.score_rmse,
                    "score_bias": metrics.score_bias,
                    "extract_skill_recall": metrics.extract_skill_recall,
                    "extract_skill_precision": metrics.extract_skill_precision,
                    "match_skill_recall": metrics.match_skill_recall,
                },
                "per_record": per_record,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"metrics": metrics, "per_record": per_record, "results_path": str(out_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Use LLM-as-judge instead of hand-labels (cheaper but lower confidence).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Sample N records instead of running the full dataset.",
    )
    args = parser.parse_args()

    result = asyncio.run(run_evals(mode="judge" if args.judge else "labels", limit=args.limit))
    if "error" in result:
        print(result["error"], file=sys.stderr)
        return 1

    metrics = result["metrics"]
    print(_format_summary(metrics, "judge" if args.judge else "labels"))
    print(f"Results written to: {result['results_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
