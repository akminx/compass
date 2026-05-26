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

from compass.evals.costs import estimate_cost
from compass.evals.dataset import EvalRecord, load_dataset
from compass.evals.metrics import ScoreMetrics, aggregate, top_k_precision
from compass.llm import get_model_id
from compass.pipeline.nodes.extract import _extract
from compass.pipeline.nodes.score import (
    _apply_clearance_gate,
    _apply_role_family_cap,
    _profile_text,
    _score,
    _score_ensemble,
)
from compass.pipeline.role_family import keyword_classify, llm_classify, upgrade_family
from compass.pipeline.state import JobRequirements, JobScore, RawJob
from compass.vault.reader import read_profile_section, read_resume

logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).parent


async def _classify_role_family_from_body(jd_text: str) -> str:
    """Eval helper: classify a JD's role family without a title (eval records
    intentionally don't carry titles). Falls through to the LLM classifier
    using the JD body as the signal. Returns the canonical family string
    used by `ROLE_FAMILY_SCORE_CAP`.
    """
    # Try the first ~3 lines as a pseudo-title — many synthetic JDs start
    # with the role name on line 1. Saves an LLM call on the easy cases.
    head = jd_text.strip().splitlines()[:3]
    pseudo_title = " ".join(head)[:200]
    in_scope, family = keyword_classify(pseudo_title)
    if in_scope is False:
        return "out-of-scope"
    if in_scope is True:
        return upgrade_family(family, jd_text)
    try:
        result = await llm_classify(pseudo_title, jd_text[:500])
        family = result.role_family if result.in_scope else "out-of-scope"
        return upgrade_family(family, jd_text)
    except Exception as e:
        logger.warning("eval: role_family LLM classify failed: %s", e)
        return "other-eng"  # neutral fallback — no cap applied


def _eval_trace_context(record: EvalRecord):
    """Tag every eval span with session_id=record.id + the `eval` feature tag
    so eval traces filter separately from production pipeline runs in the
    Langfuse UI."""
    import contextlib

    try:
        from compass.config import LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

        if not (LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY):
            return contextlib.nullcontext()
        from langfuse import propagate_attributes

        return propagate_attributes(
            session_id=f"eval-{record.id}",
            tags=["eval", "harness"],
            metadata={"source": record.source[:80]},
        )
    except Exception:
        return contextlib.nullcontext()


async def _run_extract_and_score(
    record: EvalRecord,
    *,
    ensemble_n: int = 3,
) -> tuple[JobRequirements | None, JobScore | None, float, str | None]:
    """Run the SAME extract → role-family → score → cap logic the production
    graph runs, against one labeled JD. Returns (req, score, wall_seconds,
    role_family).

    Production fidelity matters here — earlier versions called `_extract` and
    `_score` directly, which skipped the post-LLM normalization and constraint
    layers, making the metrics measure something other than what the user
    actually experiences. Now we apply:

      extract:       `_normalize_skill_list` (taxonomy folding) + seniority-
                     from-title fallback. Matches `extract_node`.
      classify:      `_classify_role_family_from_body` — derives role_family
                     from JD body (eval records lack titles). Matches the
                     `intake_filter` signal that production score_node sees
                     in `state["role_family"]`.
      score:         `_score_ensemble` (median of `ensemble_n` samples,
                     majority-vote on matched/missing) — matches `score_node`
                     when `SCORE_ENSEMBLE_N>1`. Wraps the per-sample
                     `_score_with_retry` (truncated-reasoning retry) and
                     `_constrain_to_jd_skills` is applied below.
      cap:           `_apply_role_family_cap` — caps the score when role
                     family is out-of-scope / mobile / frontend-only.
                     Matches the production `score_node`.

    `_extract` and `_score` remain the patchable surface for tests; the
    post-processing wraps the stub output. The whole body runs inside an
    `_eval_trace_context` so every Langfuse span emitted by the inner LLM
    calls gets tagged with `session_id=eval-<id>` and the `eval` feature
    tag — keeps eval traces filterable away from production runs.
    """
    from compass.pipeline.nodes.extract import (
        _normalize_skill_list,
        _seniority_with_title_fallback,
    )
    from compass.pipeline.nodes.score import _constrain_to_jd_skills

    start = time.monotonic()
    with _eval_trace_context(record):
        try:
            raw_req = await _extract(record.jd_text)
        except Exception as e:
            logger.warning("extract failed for %s: %s", record.id, e)
            return None, None, time.monotonic() - start, None

        # Mirror extract_node: canonicalize skills, fall-back seniority.
        unknown: list[str] = []
        title_hint = ""  # eval JDs don't carry titles — seniority stays as LLM said
        req = JobRequirements(
            required_skills=_normalize_skill_list(
                raw_req.required_skills, record.jd_text, unknown
            ),
            nice_to_have_skills=_normalize_skill_list(
                raw_req.nice_to_have_skills, record.jd_text, unknown
            ),
            years_experience=raw_req.years_experience,
            seniority=_seniority_with_title_fallback(raw_req.seniority, title_hint),
            remote_policy=raw_req.remote_policy,
            summary=raw_req.summary,
        )

        role_family = await _classify_role_family_from_body(record.jd_text)

        # PRODUCTION FIDELITY: the score node uses `_profile_text(req)` which
        # composes resume + RAG-retrieved top-k skill chunks. The previous eval
        # path used a flat `resume + role-clarifications` stitch which gave the
        # scorer LESS context than production. Measuring with less context
        # systematically degraded the eval and made the production scorer look
        # worse than it actually is. Wire the same path here.
        profile = await _profile_text(req)
        fake_job = RawJob(
            company="(eval)",
            title="(eval)",
            url=f"eval://{record.id}",
            source="manual",
            description=record.jd_text,
        )
        try:
            raw_score = await _score_ensemble(req, profile, fake_job, n=ensemble_n)
        except Exception as e:
            logger.warning("score failed for %s: %s", record.id, e)
            return req, None, time.monotonic() - start, role_family

        constrained = _constrain_to_jd_skills(raw_score, req)
        family_capped = _apply_role_family_cap(constrained, role_family)
        clearance_capped = _apply_clearance_gate(family_capped, record.jd_text)
        return req, clearance_capped, time.monotonic() - start, role_family


async def run_against_labels(
    records: list[EvalRecord], *, ensemble_n: int = 3
) -> tuple[ScoreMetrics, list[dict]]:
    """Run Compass on each record, compare to EvalRecord.expected_*."""
    per_record: list[dict] = []
    predicted_scores: list[float] = []
    expected_scores: list[float] = []
    predicted_skill_lists: list[list[str]] = []
    expected_skill_lists: list[list[str]] = []
    matched_skill_lists: list[list[str]] = []
    missing_skill_lists: list[list[str]] = []
    total_cost: float = 0.0
    profile = f"{read_resume()}\n\n{read_profile_section('role-clarifications')}"

    for r in records:
        req, score, elapsed, role_family = await _run_extract_and_score(r, ensemble_n=ensemble_n)
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
        missing_skill_lists.append(list(score.missing_skills))
        cost = _estimate_record_cost(r.jd_text, profile, req, score, ensemble_n=ensemble_n)
        total_cost += cost["cost_usd"]
        per_record.append(
            {
                "id": r.id,
                "source": r.source,
                "role_family": role_family,
                "expected_score": r.expected_score,
                "predicted_score": score.score,
                "score_delta": round(score.score - r.expected_score, 2),
                "expected_skills_n": len(r.expected_skills),
                "extracted_skills_n": len(extracted_skills),
                "matched_skills_n": len(score.matched_skills),
                "missing_skills_n": len(score.missing_skills),
                "missed_skills": sorted(
                    {s.lower() for s in r.expected_skills} - {s.lower() for s in extracted_skills}
                ),
                "extra_skills": sorted(
                    {s.lower() for s in extracted_skills} - {s.lower() for s in r.expected_skills}
                ),
                "elapsed_s": round(elapsed, 2),
                **cost,
            }
        )

    metrics = aggregate(
        predicted_scores,
        expected_scores,
        predicted_skill_lists,
        expected_skill_lists,
        matched_skill_lists,
        missing_skill_lists,
    )
    metrics._total_cost_usd = total_cost  # type: ignore[attr-defined]
    metrics._top_k_p_at_3 = top_k_precision(predicted_scores, expected_scores, min(3, len(predicted_scores)))  # type: ignore[attr-defined]
    return metrics, per_record


def _estimate_record_cost(
    jd_text: str,
    profile: str,
    req: JobRequirements | None,
    score: JobScore | None,
    *,
    ensemble_n: int = 1,
) -> dict:
    """Per-record cost estimate across extract + score nodes. Uses the
    chars-per-token approximation from costs.estimate_cost — accurate enough
    for cost/accuracy Pareto reporting; would need real-usage hooks for a
    billing dashboard.

    `ensemble_n`: number of score samples per JD. The extract call is single-
    shot; only score-side cost is multiplied.
    """
    import json as _json

    extract_in = jd_text  # taxonomy injection adds ~constant overhead — folded into estimate margin
    extract_out = _json.dumps(req.model_dump() if req is not None else {}) if req else ""
    score_in = f"{profile}\n{jd_text}\n{extract_out}"
    score_out = _json.dumps(score.model_dump() if score is not None else {}) if score else ""

    extract_cost = estimate_cost(get_model_id("extract"), extract_in, extract_out)
    score_cost = estimate_cost(get_model_id("score"), score_in, score_out)
    total = extract_cost.cost_usd + (score_cost.cost_usd * max(ensemble_n, 1))
    return {
        "extract_model": extract_cost.model,
        "extract_tokens_in": extract_cost.input_tokens,
        "extract_tokens_out": extract_cost.output_tokens,
        "score_model": score_cost.model,
        "score_tokens_in": score_cost.input_tokens,
        "score_tokens_out": score_cost.output_tokens,
        "score_ensemble_n": ensemble_n,
        "cost_usd": round(total, 6),
    }


async def run_against_judge(
    records: list[EvalRecord], *, ensemble_n: int = 3
) -> tuple[ScoreMetrics, list[dict]]:
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
    missing_skill_lists: list[list[str]] = []
    total_cost: float = 0.0

    for r in records:
        req, score, elapsed, role_family = await _run_extract_and_score(r, ensemble_n=ensemble_n)
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
        missing_skill_lists.append(list(score.missing_skills))
        cost = _estimate_record_cost(r.jd_text, profile, req, score, ensemble_n=ensemble_n)
        total_cost += cost["cost_usd"]
        per_record.append(
            {
                "id": r.id,
                "source": r.source,
                "role_family": role_family,
                "judge_score": verdict.expected_score,
                "predicted_score": score.score,
                "score_delta": round(score.score - verdict.expected_score, 2),
                "judge_skills_n": len(verdict.expected_skills),
                "extracted_skills_n": len(extracted_skills),
                "matched_skills_n": len(score.matched_skills),
                "missing_skills_n": len(score.missing_skills),
                "judge_skills_missed": sorted(
                    {s.lower() for s in verdict.expected_skills}
                    - {s.lower() for s in extracted_skills}
                ),
                "judge_reasoning": verdict.reasoning,
                "elapsed_s": round(elapsed, 2),
                **cost,
            }
        )

    metrics = aggregate(
        predicted_scores,
        expected_scores,
        predicted_skill_lists,
        expected_skill_lists,
        matched_skill_lists,
        missing_skill_lists,
    )
    # Stash cost + ranking helpers on the metrics object for the summary.
    # We don't widen ScoreMetrics for these because they're aggregate-only
    # (not per-JD) and don't belong in the JSON snapshot schema.
    metrics._total_cost_usd = total_cost  # type: ignore[attr-defined]
    metrics._top_k_p_at_3 = top_k_precision(predicted_scores, expected_scores, min(3, len(predicted_scores)))  # type: ignore[attr-defined]
    return metrics, per_record


def _format_summary(metrics: ScoreMetrics, mode: str) -> str:
    cost_line = (
        f"  total eval cost (USD):      ${getattr(metrics, '_total_cost_usd', 0):.4f}\n"
        if getattr(metrics, "_total_cost_usd", None) is not None
        else ""
    )
    top_k = getattr(metrics, "_top_k_p_at_3", None)
    top_k_line = f"  top-3 precision:            {top_k:.1%}\n" if top_k is not None else ""
    return (
        f"\n=== Eval results ({mode}) ===\n"
        f"  n records:                  {metrics.n}\n"
        f"  score MAE:                  {metrics.score_mae:.2f}    (0 = perfect; industry bar < 0.40)\n"
        f"  score RMSE:                 {metrics.score_rmse:.2f}\n"
        f"  score bias (signed):        {metrics.score_bias:+.2f}   (+ = over-scores, - = under-scores)\n"
        f"  spearman rank correlation:  {metrics.score_spearman:+.2f}   (+1 = ordering matches judge perfectly)\n"
        f"{top_k_line}"
        f"  extract skill recall:       {metrics.extract_skill_recall:.1%}  (B1 detector: did we see what the JD asks?)\n"
        f"  extract skill precision:    {metrics.extract_skill_precision:.1%}\n"
        f"  skill-universe recall:      {metrics.skill_universe_recall:.1%}  (SYSTEM: matched∪missing covers judge skills)\n"
        f"  skill-universe precision:   {metrics.skill_universe_precision:.1%}\n"
        f"  candidate-match recall:     {metrics.candidate_match_recall:.1%}  (CANDIDATE: matched ∩ judge / judge — coverage signal)\n"
        f"{cost_line}"
    )


async def run_evals(
    *,
    mode: str = "labels",
    limit: int | None = None,
    ensemble_n: int = 3,
    scorer_model: str | None = None,
) -> dict:
    """Programmatic entry point — used by the MCP tool wrapper.

    Returns a dict with `metrics`, `per_record`, and `results_path`.

    `scorer_model`: overrides the SCORE_MODEL env at runtime by monkey-patching
    `compass.config.SCORE_MODEL`. Used by `--scorer-model` for head-to-head
    Pareto comparisons (e.g. flash-scorer vs sonnet-scorer at same n).
    """
    import compass.config as _cfg

    original_model = _cfg.SCORE_MODEL
    if scorer_model is not None:
        _cfg.SCORE_MODEL = scorer_model
        logger.info("eval: overriding SCORE_MODEL %s → %s", original_model, scorer_model)

    try:
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
            metrics, per_record = await run_against_judge(records, ensemble_n=ensemble_n)
        else:
            metrics, per_record = await run_against_labels(records, ensemble_n=ensemble_n)
    finally:
        # Restore the original SCORE_MODEL so back-to-back run_evals calls
        # from the same process (e.g. via the MCP tool) don't inherit the
        # prior override.
        if scorer_model is not None:
            _cfg.SCORE_MODEL = original_model

    # Flush Langfuse buffers so eval traces actually land before the script
    # exits. Without this, the SDK's background batcher can drop traces.
    # Per the Langfuse skill's instrumentation reference.
    try:
        from compass.pipeline.graph import _langfuse_flush as _flush

        _flush()
    except Exception:  # pragma: no cover — observability is best-effort
        pass

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
                    "score_spearman": metrics.score_spearman,
                    "extract_skill_recall": metrics.extract_skill_recall,
                    "extract_skill_precision": metrics.extract_skill_precision,
                    "skill_universe_recall": metrics.skill_universe_recall,
                    "skill_universe_precision": metrics.skill_universe_precision,
                    "candidate_match_recall": metrics.candidate_match_recall,
                    "top_k_p_at_3": getattr(metrics, "_top_k_p_at_3", None),
                    "total_cost_usd": getattr(metrics, "_total_cost_usd", None),
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


def _format_failure_breakdown(per_record: list[dict], mode: str) -> str:
    """Worst-N analysis: surface records with largest |score_delta| + reasoning.

    For an interview-grade portfolio piece, the failure-mode table beats the
    aggregate number. "MAE 0.58" is a number; "the 3 worst records are all
    high-YoE asks where the scorer ignored the years_experience gap" is a
    LESSON. The reader sees what's actually broken and what you'd fix next.
    """
    expected_key = "expected_score" if mode == "labels" else "judge_score"
    scored = [r for r in per_record if "error" not in r and expected_key in r]
    if not scored:
        return ""
    worst = sorted(scored, key=lambda r: abs(r["score_delta"]), reverse=True)[:3]
    lines = ["\n=== Worst-3 records (largest |Δ|) ==="]
    for r in worst:
        rid = r["id"]
        src = r.get("source", "")[:50]
        exp = r[expected_key]
        pred = r["predicted_score"]
        delta = r["score_delta"]
        reason = r.get("judge_reasoning", "(no judge reasoning — labels mode)")[:140]
        lines.append(
            f"  {rid}  {src}\n"
            f"    expected={exp:.2f}  predicted={pred:.2f}  Δ={delta:+.2f}\n"
            f"    reason: {reason}..."
        )
    return "\n".join(lines) + "\n"


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
    parser.add_argument(
        "--ensemble-n",
        type=int,
        default=3,
        help="Number of scorer samples per JD (median + majority-vote). "
        "Default 3. Set 1 to disable self-consistency (faster, noisier).",
    )
    parser.add_argument(
        "--scorer-model",
        type=str,
        default=None,
        help="Override SCORE_MODEL for this run (e.g. anthropic/claude-sonnet-4-6). "
        "Used for Pareto comparisons against the default flash scorer.",
    )
    args = parser.parse_args()

    result = asyncio.run(
        run_evals(
            mode="judge" if args.judge else "labels",
            limit=args.limit,
            ensemble_n=args.ensemble_n,
            scorer_model=args.scorer_model,
        )
    )
    if "error" in result:
        print(result["error"], file=sys.stderr)
        return 1

    metrics = result["metrics"]
    mode = "judge" if args.judge else "labels"
    print(_format_summary(metrics, mode))
    print(_format_failure_breakdown(result["per_record"], mode))
    print(f"Results written to: {result['results_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
