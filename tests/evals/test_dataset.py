"""Eval dataset round-trip + EvalRecord validation."""

from __future__ import annotations

import pytest

from compass.evals.dataset import EvalRecord, add_example, load_dataset, save_dataset


def test_evalrecord_validates_score_range():
    """Score must be 0.0-5.0 per the rubric. Out-of-range = ValidationError."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EvalRecord(id="x", jd_text="t", expected_score=5.5)
    with pytest.raises(ValidationError):
        EvalRecord(id="x", jd_text="t", expected_score=-0.1)


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "dataset.json"
    records = [
        EvalRecord(
            id="eval-001",
            jd_text="Build agents.",
            expected_score=4.0,
            expected_skills=["Python", "MCP", "LangGraph"],
            notes="Strong match",
        ),
        EvalRecord(
            id="eval-002",
            jd_text="Sr. engineer needed.",
            expected_score=1.0,
            expected_skills=["Python", "Kubernetes", "Go"],
        ),
    ]
    save_dataset(records, p)
    assert p.exists()

    loaded = load_dataset(p)
    assert len(loaded) == 2
    assert loaded[0].id == "eval-001"
    assert loaded[0].expected_skills == ["Python", "MCP", "LangGraph"]
    assert loaded[1].expected_score == 1.0


def test_load_missing_file_returns_empty(tmp_path):
    """First-time setup: dataset doesn't exist yet → return [] not raise."""
    assert load_dataset(tmp_path / "nope.json") == []


def test_add_example_auto_id_increments(tmp_path):
    p = tmp_path / "dataset.json"
    add_example("jd1", 3.0, ["Python"], path=p)
    add_example("jd2", 4.0, ["MCP"], path=p)
    recs = load_dataset(p)
    assert [r.id for r in recs] == ["eval-001", "eval-002"]
