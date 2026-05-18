from datetime import date
from unittest.mock import AsyncMock

from compass.pipeline.state import CompassState, RawJob


def _state(title: str, description: str = "We build agents.") -> CompassState:
    job = RawJob(
        company="Acme",
        title=title,
        url=f"https://x/{title}",
        source="manual",
        description=description,
        date_posted=date.today(),
    )
    return {
        "raw_jobs": [],
        "current_job": job,
        "extracted_requirements": None,
        "score_result": None,
        "in_scope": None,
        "role_family": None,
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
    }


class TestIntakeFilter:
    async def test_obvious_in_skips_llm(self, monkeypatch, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod

        mock_llm = AsyncMock()
        monkeypatch.setattr(mod, "llm_classify", mock_llm)
        out = await mod.intake_filter_node(_state("Agent Engineer"))
        assert out["in_scope"] is True
        assert out["role_family"] == "agent-engineer"
        mock_llm.assert_not_called()

    async def test_obvious_out_skips_llm_and_logs(self, monkeypatch, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod

        mock_llm = AsyncMock()
        monkeypatch.setattr(mod, "llm_classify", mock_llm)
        out = await mod.intake_filter_node(_state("Account Executive"))
        assert out["in_scope"] is False
        assert out["role_family"] == "out-of-scope"
        mock_llm.assert_not_called()

        # filtered-jobs.md was appended
        log = temp_vault / "_meta" / "filtered-jobs.md"
        assert log.exists()
        assert "Account Executive" in log.read_text()

    async def test_borderline_invokes_llm(self, monkeypatch, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod
        from compass.pipeline.role_family import RoleFamilyClassification

        async def fake_llm(title, body):
            return RoleFamilyClassification(in_scope=True, role_family="fde-eng", reason="real eng")

        monkeypatch.setattr(mod, "llm_classify", fake_llm)

        out = await mod.intake_filter_node(_state("Forward Deployed Engineer"))
        assert out["in_scope"] is True
        assert out["role_family"] == "fde-eng"

    async def test_generic_swe_promoted_by_body_signal(self, monkeypatch, temp_vault):
        """Title is swe-backend but body screams agent engineering — should promote."""
        from compass.pipeline.nodes import intake_filter as mod

        body = (
            "Build agentic workflows in LangGraph. Tool calling, MCP servers, "
            "agent reliability. Strong agentic AI experience required."
        )
        mock_llm = AsyncMock()
        monkeypatch.setattr(mod, "llm_classify", mock_llm)

        out = await mod.intake_filter_node(_state("Software Engineer, Backend", body))
        assert out["in_scope"] is True
        assert out["role_family"] == "agent-engineer"
        mock_llm.assert_not_called()

    async def test_generic_swe_stays_when_no_ai_signal(self, monkeypatch, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod

        body = "Build REST APIs. Postgres. Kafka. On-call rotations."
        out = await mod.intake_filter_node(_state("Backend Engineer", body))
        assert out["role_family"] == "swe-backend"
        assert out["in_scope"] is True

    async def test_llm_in_scope_also_runs_upgrade(self, monkeypatch, temp_vault):
        """LLM returned generic family but body has strong agent signal — upgrade."""
        from compass.pipeline.nodes import intake_filter as mod
        from compass.pipeline.role_family import RoleFamilyClassification

        async def fake_llm(title, body):
            return RoleFamilyClassification(
                in_scope=True, role_family="other-eng", reason="generic"
            )

        monkeypatch.setattr(mod, "llm_classify", fake_llm)

        body = "agentic AI workflows, agent reliability, tool calling everywhere"
        out = await mod.intake_filter_node(_state("Member of Technical Staff", body))
        assert out["role_family"] == "agent-engineer"

    async def test_borderline_out_logs(self, monkeypatch, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod
        from compass.pipeline.role_family import RoleFamilyClassification

        async def fake_llm(title, body):
            return RoleFamilyClassification(
                in_scope=False, role_family="out-of-scope", reason="JD is presales"
            )

        monkeypatch.setattr(mod, "llm_classify", fake_llm)

        out = await mod.intake_filter_node(_state("Solutions Architect"))
        assert out["in_scope"] is False
        assert "Solutions Architect" in (temp_vault / "_meta" / "filtered-jobs.md").read_text()

    async def test_missing_current_job_errors(self, temp_vault):
        from compass.pipeline.nodes.intake_filter import intake_filter_node

        s = _state("X")
        s["current_job"] = None
        out = await intake_filter_node(s)
        assert out["in_scope"] is False
        assert "current_job is None" in out["errors"][-1]

    async def test_llm_failure_defaults_to_in(self, monkeypatch, temp_vault):
        """If the LLM call raises, default to IN with role_family=other-eng (post-upgrade).
        This is intentional bias toward inclusion — better to spend $0.003 extra on an
        out-of-scope JD than to silently drop a real-eng role."""
        from compass.pipeline.nodes import intake_filter as mod

        async def fake_llm(title, body):
            raise RuntimeError("network down")

        monkeypatch.setattr(mod, "llm_classify", fake_llm)

        out = await mod.intake_filter_node(
            _state("Member of Technical Staff", "writes Python systems code")
        )
        assert out["in_scope"] is True
        assert out["role_family"] == "other-eng"
