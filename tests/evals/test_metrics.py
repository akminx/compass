"""Pure-function metric primitives — no I/O, no network."""

from __future__ import annotations

import pytest

from compass.evals.metrics import (
    aggregate,
    score_bias,
    score_mae,
    score_rmse,
    skill_precision,
    skill_recall,
)


class TestScoreMAE:
    def test_perfect_match(self):
        assert score_mae([4.0, 3.0, 2.0], [4.0, 3.0, 2.0]) == 0.0

    def test_simple_diff(self):
        # |4.0-3.0| + |3.0-3.0| + |2.0-3.0| = 2.0, divided by 3 → 0.667
        assert round(score_mae([4.0, 3.0, 2.0], [3.0, 3.0, 3.0]), 3) == 0.667

    def test_empty_returns_zero(self):
        assert score_mae([], []) == 0.0


class TestScoreRMSE:
    def test_penalizes_big_misses_more_than_mae(self):
        """One large miss + several perfect matches: RMSE > MAE."""
        # MAE: |4.0-0.0| / 4 = 1.0; RMSE: sqrt(16/4) = 2.0
        mae = score_mae([4.0, 3.0, 3.0, 3.0], [0.0, 3.0, 3.0, 3.0])
        rmse = score_rmse([4.0, 3.0, 3.0, 3.0], [0.0, 3.0, 3.0, 3.0])
        assert mae == 1.0
        assert rmse == 2.0


class TestScoreBias:
    def test_positive_means_over_scoring(self):
        # Compass scored 4.5 / 4.5; humans said 3.0 / 3.0 → Compass over by 1.5
        assert score_bias([4.5, 4.5], [3.0, 3.0]) == 1.5

    def test_negative_means_under_scoring(self):
        assert score_bias([2.0, 2.0], [3.5, 3.5]) == -1.5

    def test_zero_when_unbiased(self):
        # Symmetric over/under cancels out
        assert score_bias([4.0, 2.0], [3.0, 3.0]) == 0.0


class TestSkillRecall:
    def test_all_found(self):
        assert skill_recall(["Python", "MCP", "LangGraph"], ["Python", "MCP"]) == 1.0

    def test_half_missed(self):
        assert skill_recall(["Python"], ["Python", "MCP"]) == 0.5

    def test_case_insensitive(self):
        assert skill_recall(["python", "MCP"], ["Python", "mcp"]) == 1.0

    def test_empty_expected_is_vacuous_truth(self):
        """If the JD lists no skills, we trivially found them all."""
        assert skill_recall([], []) == 1.0
        assert skill_recall(["Python"], []) == 1.0

    def test_empty_predicted_with_nonempty_expected(self):
        assert skill_recall([], ["Python", "MCP"]) == 0.0


class TestSkillPrecision:
    def test_no_false_positives(self):
        assert skill_precision(["Python", "MCP"], ["Python", "MCP", "LangGraph"]) == 1.0

    def test_extra_skills_drop_precision(self):
        # Predicted 4, only 2 are in expected → 50% precision
        assert (
            skill_precision(["Python", "MCP", "Java", "Ruby"], ["Python", "MCP", "LangGraph"])
            == 0.5
        )

    def test_empty_predicted_is_vacuous_truth(self):
        """If we predicted no skills, we have zero false positives."""
        assert skill_precision([], ["Python"]) == 1.0


class TestAggregate:
    def test_full_aggregate(self):
        metrics = aggregate(
            predicted_scores=[4.0, 3.0],
            expected_scores=[4.0, 4.0],
            predicted_skill_lists=[["Python", "MCP"], ["Python"]],
            expected_skill_lists=[["Python", "MCP"], ["Python", "LangGraph"]],
            matched_skill_lists=[["Python", "MCP"], ["Python"]],
        )
        assert metrics.n == 2
        assert metrics.score_mae == 0.5  # (0 + 1) / 2
        assert metrics.score_bias == -0.5  # both under by 1 / averaged
        # Record 1: 2/2 recall, 2/2 precision. Record 2: 1/2 recall, 1/1 precision.
        # Average recall: (1.0 + 0.5) / 2 = 0.75
        assert metrics.extract_skill_recall == 0.75
        assert metrics.extract_skill_precision == 1.0

    def test_n_zero(self):
        m = aggregate([], [], [], [])
        assert m.n == 0
        assert m.score_mae == 0.0
        assert m.score_rmse == 0.0

    def test_match_lists_default_to_predicted(self):
        """When matched_skill_lists is None, match_skill_recall === extract_skill_recall."""
        m = aggregate(
            predicted_scores=[4.0],
            expected_scores=[4.0],
            predicted_skill_lists=[["Python"]],
            expected_skill_lists=[["Python"]],
            matched_skill_lists=None,
        )
        assert m.match_skill_recall == 1.0


def test_zip_strict_catches_length_mismatch():
    """Defensive: passing mismatched lists should raise rather than silently
    truncate — strict=True in the impl makes this an immediate ValueError."""
    with pytest.raises(ValueError):
        score_mae([4.0, 3.0], [4.0])
