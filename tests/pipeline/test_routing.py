"""Tests for reflect_node + hitl_node — control-flow nodes (no LLM in 0.B)."""

from datetime import date

from compass.config import SCORE_THRESHOLD
from compass.pipeline.state import CompassState, JobScore, RawJob


def _state(score_value: float) -> CompassState:
    return {
        "raw_jobs": [],
        "current_job": RawJob(
            company="x",
            title="y",
            url="https://example.com/z",
            source="greenhouse",
            description="...",
            date_posted=date.today(),
        ),
        "extracted_requirements": None,
        "score_result": JobScore(
            score=score_value,
            reasoning="",
            matched_skills=[],
            missing_skills=[],
            tailoring_notes="",
        ),
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
    }


async def test_reflect_node_is_passthrough():
    from compass.pipeline.nodes.reflect import reflect_node

    state = _state(3.2)
    result = await reflect_node(state)
    assert result == {}


async def test_hitl_node_approves_when_score_meets_threshold():
    from compass.pipeline.nodes.hitl import hitl_node

    result = await hitl_node(_state(SCORE_THRESHOLD))
    assert result["human_approved"] is True


async def test_hitl_node_rejects_when_score_below_threshold():
    from compass.pipeline.nodes.hitl import hitl_node

    result = await hitl_node(_state(SCORE_THRESHOLD - 0.5))
    assert result["human_approved"] is False


async def test_hitl_node_handles_missing_score():
    from compass.pipeline.nodes.hitl import hitl_node

    state = _state(0.0)
    state["score_result"] = None
    result = await hitl_node(state)
    assert result["human_approved"] is False


class TestIntakeFilterRouting:
    def test_out_of_scope_yields_in_scope_false_and_no_write(self, temp_vault):
        """An out-of-scope job must short-circuit to END without invoking
        extract/score/tailor/vault_write."""
        import asyncio

        from compass.pipeline import graph as g
        from compass.pipeline.state import RawJob

        job = RawJob(
            company="Acme",
            title="Account Executive",
            url="https://x/ae",
            source="manual",
            description="Sell things.",
            date_posted=date.today(),
        )
        graph = g.build_graph()
        out = asyncio.run(graph.ainvoke(g._initial_state(job)))
        assert out["in_scope"] is False
        assert out["vault_written"] is False
        assert out.get("extracted_requirements") is None
        assert out.get("score_result") is None

    def test_route_after_filter_in_scope_returns_extract(self):
        """Unit test: predicate returns 'extract' when in_scope is True."""
        from compass.pipeline.graph import _route_after_filter

        assert _route_after_filter({"in_scope": True}) == "extract"

    def test_route_after_filter_out_of_scope_returns_end(self):
        """Unit test: predicate returns 'end' for in_scope False or None."""
        from compass.pipeline.graph import _route_after_filter

        assert _route_after_filter({"in_scope": False}) == "end"
        assert _route_after_filter({"in_scope": None}) == "end"
        assert _route_after_filter({}) == "end"
