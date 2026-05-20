"""Eval metric primitives — pure functions, no I/O, no LLM calls.

Used by both the human-label runner (compares to EvalRecord.expected_*) and
the LLM-as-judge runner (compares to a judge model's expected_*).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScoreMetrics:
    """Aggregate metrics across N JDs."""

    n: int
    score_mae: float  # mean absolute error of Compass score vs expected
    score_rmse: float  # sqrt of mean squared error — penalizes big misses
    score_bias: float  # mean signed error — positive = Compass over-scores
    extract_skill_recall: float  # fraction of expected_skills that extract_node found
    extract_skill_precision: float  # fraction of extracted skills that match expected
    match_skill_recall: (
        float  # fraction of expected_skills that score_node attributed as matched_skills
    )


def score_mae(predicted: list[float], expected: list[float]) -> float:
    """Mean absolute error. Returns 0.0 for empty input — runner handles n=0."""
    if not predicted:
        return 0.0
    pairs = list(zip(predicted, expected, strict=True))
    return sum(abs(p - e) for p, e in pairs) / len(pairs)


def score_rmse(predicted: list[float], expected: list[float]) -> float:
    """Root mean squared error. Same length contract as `score_mae`."""
    if not predicted:
        return 0.0
    pairs = list(zip(predicted, expected, strict=True))
    return (sum((p - e) ** 2 for p, e in pairs) / len(pairs)) ** 0.5


def score_bias(predicted: list[float], expected: list[float]) -> float:
    """Mean signed error. Positive = Compass scores HIGHER than the human;
    negative = Compass scores LOWER. Signed bias is more useful than MAE
    when deciding which direction to tune the prompt."""
    if not predicted:
        return 0.0
    pairs = list(zip(predicted, expected, strict=True))
    return sum(p - e for p, e in pairs) / len(pairs)


def skill_recall(predicted_skills: list[str], expected_skills: list[str]) -> float:
    """Of the expected skills, what fraction did the predictor find?

    Case-insensitive set match — the canonical taxonomy enforces casing
    elsewhere, but humans labeling examples may type "Langgraph" or
    "langGraph" inconsistently.

    Returns 1.0 when `expected_skills` is empty (vacuous truth — no skills
    to find means we found all of them). Returns 0.0 when expected is
    non-empty but predicted is empty.
    """
    if not expected_skills:
        return 1.0
    exp = {s.lower() for s in expected_skills}
    pred = {s.lower() for s in predicted_skills}
    return len(exp & pred) / len(exp)


def skill_precision(predicted_skills: list[str], expected_skills: list[str]) -> float:
    """Of the predicted skills, what fraction were correct?

    Returns 1.0 when `predicted_skills` is empty (vacuous — no false
    positives possible)."""
    if not predicted_skills:
        return 1.0
    exp = {s.lower() for s in expected_skills}
    pred = {s.lower() for s in predicted_skills}
    return len(exp & pred) / len(pred)


def aggregate(
    predicted_scores: list[float],
    expected_scores: list[float],
    predicted_skill_lists: list[list[str]],
    expected_skill_lists: list[list[str]],
    matched_skill_lists: list[list[str]] | None = None,
) -> ScoreMetrics:
    """Aggregate per-JD metrics across the whole dataset.

    `matched_skill_lists` is the `score_result.matched_skills` for each JD —
    used to compute `match_skill_recall` separately from extract recall.
    Passing None makes match_skill_recall fall back to extract_skill_recall.
    """
    n = len(predicted_scores)
    if n == 0:
        return ScoreMetrics(
            n=0,
            score_mae=0.0,
            score_rmse=0.0,
            score_bias=0.0,
            extract_skill_recall=0.0,
            extract_skill_precision=0.0,
            match_skill_recall=0.0,
        )

    matched_lists = (
        matched_skill_lists if matched_skill_lists is not None else predicted_skill_lists
    )

    extract_recalls = [
        skill_recall(pred, exp)
        for pred, exp in zip(predicted_skill_lists, expected_skill_lists, strict=True)
    ]
    extract_precisions = [
        skill_precision(pred, exp)
        for pred, exp in zip(predicted_skill_lists, expected_skill_lists, strict=True)
    ]
    match_recalls = [
        skill_recall(matched, exp)
        for matched, exp in zip(matched_lists, expected_skill_lists, strict=True)
    ]

    return ScoreMetrics(
        n=n,
        score_mae=score_mae(predicted_scores, expected_scores),
        score_rmse=score_rmse(predicted_scores, expected_scores),
        score_bias=score_bias(predicted_scores, expected_scores),
        extract_skill_recall=sum(extract_recalls) / n,
        extract_skill_precision=sum(extract_precisions) / n,
        match_skill_recall=sum(match_recalls) / n,
    )
