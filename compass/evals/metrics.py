"""Eval metric primitives — pure functions, no I/O, no LLM calls.

Used by both the human-label runner (compares to EvalRecord.expected_*) and
the LLM-as-judge runner (compares to a judge model's expected_*).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScoreMetrics:
    """Aggregate metrics across N JDs.

    Score-side metrics (mae/rmse/bias) measure score_node's numeric output
    against the expected score. Skill-side metrics are split into:

    - extract_*: did extract_node see the skills the JD asks for? (independent
      of the candidate). This is the B1 detector — pure JD-reading capability.

    - skill_universe_recall: did score_node's matched+missing cover the same
      skill universe the judge identified? This is the system-attribution
      metric — the right read of "is the scorer working" because matched∪missing
      = JD universe by prompt design, independent of what the candidate has.

    - candidate_match_recall: of judge-identified JD skills, how many is the
      candidate credited with possessing? This is NOT a system-accuracy metric
      — a perfect score would require the candidate to have every skill in
      every JD. Reported because it's the headline number for skill-coverage
      gap analysis (and gap_aggregator uses the same signal).

    Splitting these is non-cosmetic — a single `match_skill_recall` that
    conflates them silently turns a candidate-coverage signal into what readers
    misinterpret as a system-correctness signal. Industry-standard eval
    reporting separates them.
    """

    n: int
    score_mae: float  # mean absolute error of Compass score vs expected
    score_rmse: float  # sqrt of mean squared error — penalizes big misses
    score_bias: float  # mean signed error — positive = Compass over-scores
    score_spearman: float  # rank correlation: does our ordering match the judge's?
    extract_skill_recall: float  # fraction of expected_skills that extract_node found
    extract_skill_precision: float  # fraction of extracted skills that match expected
    skill_universe_recall: float  # (matched∪missing) ∩ judge / judge — SYSTEM accuracy
    skill_universe_precision: float  # (matched∪missing) ∩ judge / (matched∪missing)
    candidate_match_recall: float  # matched ∩ judge / judge — CANDIDATE coverage


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


def spearman_rho(predicted: list[float], expected: list[float]) -> float:
    """Spearman rank correlation. Tells you whether the scorer's ORDERING
    matches the judge's ordering — even if absolute numbers drift.

    For a job-ranking system this is arguably more important than MAE: a
    user clicks down a sorted list, so getting the ORDER right matters
    even when individual scores are off by 0.5.

    Returns 0.0 when n<2 (correlation undefined). Hand-rolled (no scipy)
    because the rest of the metrics module is dependency-free.
    """
    n = len(predicted)
    if n < 2:
        return 0.0

    def _rank(xs: list[float]) -> list[float]:
        # Average-rank tie-breaking — equivalent to scipy.stats.rankdata default.
        order = sorted(range(n), key=lambda i: xs[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1  # 1-indexed average
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks

    rp = _rank(predicted)
    re = _rank(expected)
    mean_rp = sum(rp) / n
    mean_re = sum(re) / n
    num = sum((rp[i] - mean_rp) * (re[i] - mean_re) for i in range(n))
    den_p = sum((rp[i] - mean_rp) ** 2 for i in range(n)) ** 0.5
    den_e = sum((re[i] - mean_re) ** 2 for i in range(n)) ** 0.5
    if den_p == 0 or den_e == 0:
        # Constant rank on one side — correlation undefined; return 0 not NaN.
        return 0.0
    return num / (den_p * den_e)


def top_k_precision(predicted: list[float], expected: list[float], k: int) -> float:
    """Of the K highest-predicted records, what fraction are in the K highest
    by judge score? Measures "would a user looking at the top K see the
    right jobs?" — directly answers the product question.

    Returns 0.0 for k<=0 or k>n.
    """
    n = len(predicted)
    if k <= 0 or k > n:
        return 0.0
    top_pred = set(sorted(range(n), key=lambda i: -predicted[i])[:k])
    top_exp = set(sorted(range(n), key=lambda i: -expected[i])[:k])
    return len(top_pred & top_exp) / k


def aggregate(
    predicted_scores: list[float],
    expected_scores: list[float],
    predicted_skill_lists: list[list[str]],
    expected_skill_lists: list[list[str]],
    matched_skill_lists: list[list[str]] | None = None,
    missing_skill_lists: list[list[str]] | None = None,
) -> ScoreMetrics:
    """Aggregate per-JD metrics across the whole dataset.

    `matched_skill_lists` and `missing_skill_lists` are the score_result fields
    for each JD. Together they form the JD-universe-as-the-scorer-saw-it; the
    union is used for skill_universe_recall/precision, and matched alone for
    candidate_match_recall. When `missing_skill_lists` is None, universe falls
    back to matched only (back-compat for callers pre-split).
    """
    n = len(predicted_scores)
    if n == 0:
        return ScoreMetrics(
            n=0,
            score_mae=0.0,
            score_rmse=0.0,
            score_bias=0.0,
            score_spearman=0.0,
            extract_skill_recall=0.0,
            extract_skill_precision=0.0,
            skill_universe_recall=0.0,
            skill_universe_precision=0.0,
            candidate_match_recall=0.0,
        )

    matched_lists = (
        matched_skill_lists if matched_skill_lists is not None else predicted_skill_lists
    )
    missing_lists = (
        missing_skill_lists if missing_skill_lists is not None else [[] for _ in matched_lists]
    )
    universe_lists = [list({*m, *mi}) for m, mi in zip(matched_lists, missing_lists, strict=True)]

    extract_recalls = [
        skill_recall(pred, exp)
        for pred, exp in zip(predicted_skill_lists, expected_skill_lists, strict=True)
    ]
    extract_precisions = [
        skill_precision(pred, exp)
        for pred, exp in zip(predicted_skill_lists, expected_skill_lists, strict=True)
    ]
    universe_recalls = [
        skill_recall(uni, exp)
        for uni, exp in zip(universe_lists, expected_skill_lists, strict=True)
    ]
    universe_precisions = [
        skill_precision(uni, exp)
        for uni, exp in zip(universe_lists, expected_skill_lists, strict=True)
    ]
    candidate_match_recalls = [
        skill_recall(matched, exp)
        for matched, exp in zip(matched_lists, expected_skill_lists, strict=True)
    ]

    return ScoreMetrics(
        n=n,
        score_mae=score_mae(predicted_scores, expected_scores),
        score_rmse=score_rmse(predicted_scores, expected_scores),
        score_bias=score_bias(predicted_scores, expected_scores),
        score_spearman=spearman_rho(predicted_scores, expected_scores),
        extract_skill_recall=sum(extract_recalls) / n,
        extract_skill_precision=sum(extract_precisions) / n,
        skill_universe_recall=sum(universe_recalls) / n,
        skill_universe_precision=sum(universe_precisions) / n,
        candidate_match_recall=sum(candidate_match_recalls) / n,
    )
