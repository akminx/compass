from datetime import date
from unittest.mock import AsyncMock

from compass.pipeline.state import CompassState, RawJob


def _state(title: str, description: str = "We build LangGraph agents with MCP.") -> CompassState:
    # Default description carries a STRONG agent signal so tests that don't
    # care about body content (most of them) still pass the agent-signal gate.
    # Tests that DO care override the description explicitly.
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

        # `Solutions Architect` is borderline — the keyword classifier returns
        # None (LLM stage decides). MTS used to be borderline but as of the
        # 3-month-pivot title expansion routes directly to agent-engineer, so
        # it no longer exercises the LLM-failure code path.
        out = await mod.intake_filter_node(
            _state("Solutions Architect", "writes Python systems code")
        )
        assert out["in_scope"] is True
        assert out["role_family"] == "other-eng"


class TestRejectRules:
    """preferences.md `reject_if_title_contains` + `reject_if_jd_contains` are
    enforced at intake before any LLM call. Saves ~40-60% LLM cost on a wide
    scrape and keeps senior/staff/principal noise out of the vault."""

    def _write_prefs(self, temp_vault):
        prefs = temp_vault / "_profile" / "preferences.md"
        prefs.write_text(
            "---\ntype: profile\n---\n"
            "## Role filters\n"
            "```yaml\n"
            "reject_if_title_contains:\n"
            "  - Senior\n"
            "  - Sr.\n"
            "  - Staff\n"
            "  - Principal\n"
            "reject_if_jd_contains:\n"
            "  - 5+ years\n"
            "  - PhD required\n"
            "```\n",
            encoding="utf-8",
        )

    async def test_senior_in_title_dropped_before_llm(self, monkeypatch, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod

        self._write_prefs(temp_vault)
        mock_llm = AsyncMock()
        monkeypatch.setattr(mod, "llm_classify", mock_llm)
        out = await mod.intake_filter_node(_state("Senior Software Engineer, Agents"))
        assert out["in_scope"] is False
        assert out["role_family"] == "out-of-scope"
        mock_llm.assert_not_called()
        log = (temp_vault / "_meta" / "filtered-jobs.md").read_text()
        assert "title rejects" in log
        assert "senior" in log.lower()

    async def test_yoe_in_jd_dropped_before_llm(self, monkeypatch, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod

        self._write_prefs(temp_vault)
        mock_llm = AsyncMock()
        monkeypatch.setattr(mod, "llm_classify", mock_llm)
        out = await mod.intake_filter_node(
            _state("Engineer", "Looking for someone with 5+ years of LLM experience.")
        )
        assert out["in_scope"] is False
        assert out["role_family"] == "out-of-scope"
        mock_llm.assert_not_called()
        log = (temp_vault / "_meta" / "filtered-jobs.md").read_text()
        assert "jd rejects" in log

    async def test_reject_rules_dont_affect_clean_jds(self, monkeypatch, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod

        self._write_prefs(temp_vault)
        mock_llm = AsyncMock()
        monkeypatch.setattr(mod, "llm_classify", mock_llm)
        out = await mod.intake_filter_node(
            _state("Agent Engineer", "Build LangGraph agents in Python with MCP.")
        )
        assert out["in_scope"] is True

    async def test_missing_preferences_file_doesnt_crash(self, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod

        # Delete the seed preferences file so load_reject_rules returns empties
        (temp_vault / "_profile" / "preferences.md").unlink()
        out = await mod.intake_filter_node(_state("Agent Engineer"))
        assert out["in_scope"] is True
        assert out["role_family"] == "agent-engineer"


class TestAgentSignalGate:
    """JD-body agent-signal check: AI-oriented title with ZERO agent terms in
    the body is dropped. Other role families pass through unfiltered."""

    async def test_agent_title_with_no_body_signal_dropped(self, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod

        out = await mod.intake_filter_node(
            _state("AI Engineer", "We build dashboards using React and Postgres.")
        )
        assert out["in_scope"] is False
        assert out["role_family"] == "out-of-scope"
        assert out["agent_signal_count"] == 0
        log = (temp_vault / "_meta" / "filtered-jobs.md").read_text()
        assert "no-strong-agent-signal" in log

    async def test_agent_title_with_body_signal_kept(self, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod

        out = await mod.intake_filter_node(
            _state(
                "AI Engineer",
                "Build LangGraph agents with MCP tool calling for production users.",
            )
        )
        assert out["in_scope"] is True
        assert out["agent_signal_count"] >= 3  # langgraph + agents + mcp + tool calling

    async def test_swe_backend_passes_through_without_body_signal(self, temp_vault):
        """Generic SWE titles at AI-native companies sometimes describe agent
        work — don't gate them on body signal. The score node sees it later."""
        from compass.pipeline.nodes import intake_filter as mod

        out = await mod.intake_filter_node(
            _state("Backend Engineer", "Build distributed systems with Postgres.")
        )
        assert out["in_scope"] is True
        assert out["role_family"] == "swe-backend"
        assert out["agent_signal_count"] == 0  # tracked but not gating

    async def test_agent_engineer_title_with_one_signal_kept(self, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod

        out = await mod.intake_filter_node(
            _state("Agent Engineer", "Build and ship multi-agent systems.")
        )
        assert out["in_scope"] is True
        assert out["agent_signal_count"] >= 1


class TestAgentSignalFalsePositives:
    """Regression tests for 2026-05-19 adversarial review: weak-signal words
    ('agent' alone in non-agentic context) must NOT pass the gate."""

    async def test_change_agent_marketing_speak_dropped(self, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod

        out = await mod.intake_filter_node(
            _state(
                "AI Engineer",
                "We're looking for a change agent who can transform our team.",
            )
        )
        assert out["in_scope"] is False, "marketing 'change agent' must not pass the gate"
        assert out["agent_signal_count"] >= 1, "but weak signal count should still reflect the hit"

    async def test_user_agent_http_header_context_dropped(self, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod

        out = await mod.intake_filter_node(
            _state("AI Engineer", "Set the User-Agent header in your requests to the API.")
        )
        assert out["in_scope"] is False
        assert out["agent_signal_count"] >= 1

    async def test_real_strong_signal_passes(self, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod

        out = await mod.intake_filter_node(
            _state("AI Engineer", "Build LangGraph multi-agent systems with MCP.")
        )
        assert out["in_scope"] is True
        assert out["agent_signal_count"] >= 3  # langgraph + multi-agent + mcp

    async def test_strong_signal_alone_passes_even_without_agent_word(self, temp_vault):
        """A JD that mentions only LangGraph + tool-calling should pass — those
        are unambiguous agent-eng terms even without the word 'agent'."""
        from compass.pipeline.nodes import intake_filter as mod

        out = await mod.intake_filter_node(
            _state("AI Engineer", "Implement function-calling with LangGraph for our platform.")
        )
        assert out["in_scope"] is True


class TestAgentSignalCountConsistency:
    """Regression: every dropped JD should set agent_signal_count to a number,
    not None. Downstream readers should never have to handle None for that key."""

    async def test_title_reject_sets_signal_count_zero(self, monkeypatch, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod

        TestRejectRules()._write_prefs(temp_vault)
        out = await mod.intake_filter_node(_state("Senior Software Engineer"))
        assert out["in_scope"] is False
        assert out["agent_signal_count"] == 0

    async def test_jd_reject_sets_signal_count_zero(self, monkeypatch, temp_vault):
        from compass.pipeline.nodes import intake_filter as mod

        TestRejectRules()._write_prefs(temp_vault)
        out = await mod.intake_filter_node(
            _state("AI Engineer", "Looking for 5+ years experience with agents.")
        )
        assert out["in_scope"] is False
        assert out["agent_signal_count"] == 0


def test_agent_signal_count_helper():
    """Counts distinct term hits, case-insensitive, word-boundary safe."""
    from compass.pipeline.nodes.intake_filter import _agent_signal_count

    assert _agent_signal_count("") == 0
    assert _agent_signal_count("This role is about React and dashboards.") == 0
    assert _agent_signal_count("Build LangGraph agents.") == 2  # langgraph + agents
    # repeated terms count once
    assert _agent_signal_count("agents agents agents") == 1
    # word-boundary: "agenda" should not match "agent"
    assert _agent_signal_count("Your daily agenda includes meetings.") == 0
    # "agentic" matches its own pattern, not "agent"
    # "agentic AI" is a STRONG term (matches r"\bagentic\s+ai\b"); "agentic"
    # alone is also a WEAK term — both fire, distinct hits.
    assert _agent_signal_count("We are an agentic AI company.") == 2
