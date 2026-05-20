"""hitl_node calls interrupt() above threshold; auto-rejects below threshold."""

from __future__ import annotations

import datetime as _dt

import pytest

from compass.pipeline.nodes.hitl import hitl_node
from compass.pipeline.state import CompassState, JobScore, RawJob


def _state(score: float | None) -> CompassState:
    job = RawJob(
        company="Sierra",
        title="SWE, Agent",
        url="https://jobs.example.com/sierra-1",
        source="ashby",
        description="...",
        date_posted=_dt.date(2026, 5, 18),
    )
    sr = (
        None
        if score is None
        else JobScore(
            score=score,
            reasoning="ok",
            matched_skills=["MCP"],
            missing_skills=["LangGraph"],
            tailoring_notes="",
        )
    )
    return {
        "raw_jobs": [],
        "current_job": job,
        "extracted_requirements": None,
        "score_result": sr,
        "in_scope": True,
        "role_family": "agent-engineer",
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
        "thread_id": "tid-test",
    }


async def test_below_threshold_auto_rejects_without_interrupt(monkeypatch):
    """Below SCORE_THRESHOLD short-circuits — interrupt MUST NOT fire (no human prompt cost)."""
    called = {"interrupt": 0}

    def boom(_payload):
        called["interrupt"] += 1
        raise AssertionError("interrupt should not have been called")

    monkeypatch.setattr("compass.pipeline.nodes.hitl.interrupt", boom)
    result = await hitl_node(_state(score=2.0))
    assert result == {"human_approved": False}
    assert called["interrupt"] == 0


async def test_missing_score_auto_rejects():
    result = await hitl_node(_state(score=None))
    assert result == {"human_approved": False}


async def test_above_threshold_calls_interrupt_with_payload(monkeypatch):
    captured = {}

    def fake_interrupt(payload):
        captured.update(payload)
        # Simulate resume value (this is what Command(resume=...) sends back)
        return {"approved": True, "feedback": "Strong fit"}

    monkeypatch.setattr("compass.pipeline.nodes.hitl.interrupt", fake_interrupt)
    result = await hitl_node(_state(score=4.2))
    assert captured["kind"] == "approval_request"
    assert captured["company"] == "Sierra"
    assert captured["score"] == pytest.approx(4.2)
    assert captured["matched_skills"] == ["MCP"]
    assert result == {"human_approved": True, "human_feedback": "Strong fit"}


async def test_resume_rejection_propagates(monkeypatch):
    monkeypatch.setattr(
        "compass.pipeline.nodes.hitl.interrupt",
        lambda _p: {"approved": False, "feedback": "Not a fit"},
    )
    result = await hitl_node(_state(score=4.2))
    assert result == {"human_approved": False, "human_feedback": "Not a fit"}


async def test_malformed_resume_value_defaults_to_rejected(monkeypatch):
    """If Command(resume=...) somehow sends a non-dict, treat as reject not crash."""
    monkeypatch.setattr("compass.pipeline.nodes.hitl.interrupt", lambda _p: "bogus")
    result = await hitl_node(_state(score=4.2))
    assert result == {"human_approved": False}


async def test_below_threshold_uses_state_score_threshold_when_present(monkeypatch):
    """If state['score_threshold'] is set (captured at score time), hitl uses
    it — not the live config value. Prevents resume-time SCORE_THRESHOLD
    edits from silently auto-rejecting a pre-approved thread."""
    captured = {}

    def fake_interrupt(_p):
        captured["called"] = True
        return {"approved": True}

    monkeypatch.setattr("compass.pipeline.nodes.hitl.interrupt", fake_interrupt)

    state = _state(score=3.0)
    state["score_threshold"] = 2.0  # captured at score time; less than 3.0
    # Live config: SCORE_THRESHOLD=3.5 (default)
    import compass.pipeline.nodes.hitl as hitl_mod

    monkeypatch.setattr(hitl_mod, "SCORE_THRESHOLD", 3.5)

    result = await hitl_node(state)
    assert captured.get("called") is True  # interrupt fired despite config threshold > score
    assert result["human_approved"] is True


async def test_below_threshold_falls_back_to_config_when_state_threshold_missing(monkeypatch):
    """Backward-compat: paused threads from before this fix have no
    state['score_threshold']; hitl falls back to config."""
    monkeypatch.setattr(
        "compass.pipeline.nodes.hitl.interrupt",
        lambda p: pytest.fail("interrupt should not fire when score < config threshold"),
    )

    state = _state(score=2.0)
    # state['score_threshold'] not set — defaults to None via .get()
    import compass.pipeline.nodes.hitl as hitl_mod

    monkeypatch.setattr(hitl_mod, "SCORE_THRESHOLD", 3.5)

    result = await hitl_node(state)
    assert result == {"human_approved": False}
