"""LangGraph checkpoint serde — Pydantic state classes on the msgpack allowlist
so checkpoint round-trip neither warns nor blocks under future STRICT mode."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def checkpoint_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "checkpoints.db"
    import compass.config as cfg

    monkeypatch.setattr(cfg, "HITL_CHECKPOINT_DB", db)
    return db


async def test_build_checkpoint_serde_allowlists_state_module():
    """_build_checkpoint_serde must return a serde whose allowlist suppresses
    the 'unregistered type' warning AND preserves Pydantic classes on round-trip."""
    import langgraph.checkpoint.serde.jsonplus as _jp
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    from compass.pipeline.graph import _build_checkpoint_serde

    _jp._warned_unregistered_types.clear()

    serde = _build_checkpoint_serde()
    assert isinstance(serde, JsonPlusSerializer)

    import datetime
    import logging

    from compass.pipeline.state import RawJob

    captured = []

    class _H(logging.Handler):
        def emit(self, r):
            msg = r.getMessage()
            if "unregistered type" in msg or "fingerprint" in msg.lower():
                captured.append(msg)

    h = _H()
    logging.getLogger("langgraph").addHandler(h)
    try:
        rj = RawJob(
            company="C",
            title="T",
            url="u://x",
            source="ashby",
            description="d",
            date_posted=datetime.date(2026, 5, 19),
        )
        ser = serde.dumps_typed(rj)
        restored = serde.loads_typed(ser)
        assert isinstance(restored, RawJob)
    finally:
        logging.getLogger("langgraph").removeHandler(h)
    assert not captured, f"serde still emitted unregistered-type warnings: {captured}"


async def test_run_pipeline_emits_no_unregistered_warnings(checkpoint_db, monkeypatch, temp_vault):
    """End-to-end smoke: run_pipeline mounts AsyncSqliteSaver with our serde.
    No 'unregistered type' warnings during a full graph round-trip."""
    import datetime as _dt
    import logging

    import langgraph.checkpoint.serde.jsonplus as _jp

    from compass.pipeline.state import JobRequirements, JobScore, RawJob

    _jp._warned_unregistered_types.clear()

    captured = []

    class _Handler(logging.Handler):
        def emit(self, record):
            if "unregistered type" in record.getMessage():
                captured.append(record.getMessage())

    handler = _Handler()
    logging.getLogger("langgraph").addHandler(handler)

    async def fake_intake_filter(_):
        return {"in_scope": True, "role_family": "agent-engineer"}

    async def fake_extract(_):
        return {
            "extracted_requirements": JobRequirements(
                required_skills=["MCP"],
                nice_to_have_skills=[],
                seniority="mid",
                remote_policy="remote",
                summary="x",
            )
        }

    async def fake_score(_):
        return {
            "score_result": JobScore(
                score=4.5,
                reasoning="ok",
                matched_skills=["MCP"],
                missing_skills=[],
                tailoring_notes="",
            ),
            "score_threshold": 3.5,
        }

    async def fake_tailor(_):
        return {"tailored_paragraph": "..."}

    async def fake_vault_write(_):
        return {"vault_written": True, "jobs_written": 1}

    monkeypatch.setattr("compass.pipeline.graph.intake_filter_node", fake_intake_filter)
    monkeypatch.setattr("compass.pipeline.graph.extract_node", fake_extract)
    monkeypatch.setattr("compass.pipeline.graph.score_node", fake_score)
    monkeypatch.setattr("compass.pipeline.graph.tailor_node", fake_tailor)
    monkeypatch.setattr("compass.pipeline.graph.vault_write_node", fake_vault_write)
    monkeypatch.setattr(
        "compass.pipeline.nodes.hitl.interrupt", lambda _: {"approved": True, "feedback": None}
    )

    from compass.pipeline.graph import run_pipeline

    await run_pipeline(
        raw_jobs=[
            RawJob(
                company="Sierra",
                title="SWE",
                url="u://x/1",
                source="ashby",
                description="...",
                date_posted=_dt.date(2026, 5, 19),
            )
        ]
    )

    logging.getLogger("langgraph").removeHandler(handler)
    assert not captured, f"Expected no 'unregistered type' warnings, got: {captured}"
