from compass.pipeline.role_family import keyword_classify


class TestKeywordClassify:
    def test_obvious_in_scope_agent_engineer(self):
        in_scope, family = keyword_classify("Agent Engineer, APX")
        assert in_scope is True
        assert family == "agent-engineer"

    def test_obvious_in_scope_applied_ai(self):
        in_scope, family = keyword_classify("Applied AI Engineer")
        assert in_scope is True
        assert family == "applied-ai"

    def test_obvious_in_scope_backend(self):
        in_scope, family = keyword_classify("Software Engineer, Backend")
        assert in_scope is True
        assert family == "swe-backend"

    def test_obvious_in_scope_founding(self):
        in_scope, family = keyword_classify("Founding Engineer")
        assert in_scope is True
        assert family == "swe-founding"

    def test_obvious_out_scope_sales(self):
        assert keyword_classify("Account Executive, Enterprise") == (False, "out-of-scope")

    def test_obvious_out_scope_pm(self):
        assert keyword_classify("Product Manager, Agent Platform") == (False, "out-of-scope")

    def test_obvious_out_scope_designer(self):
        assert keyword_classify("Conversational Designer") == (False, "out-of-scope")

    def test_obvious_out_scope_recruiter(self):
        assert keyword_classify("Senior Technical Recruiter") == (False, "out-of-scope")

    def test_borderline_solutions_architect_is_none(self):
        assert keyword_classify("Solutions Architect")[0] is None

    def test_borderline_fde_is_none(self):
        assert keyword_classify("Forward Deployed Engineer")[0] is None

    def test_master_boolean_agent_titles_route_to_agent_engineer(self):
        """Titles named in _profile/target-roles.md::JD-master-boolean should
        all classify as in-scope agent-engineer without hitting the LLM."""
        for title in [
            "AI Agent Engineer",
            "Agentic AI Engineer",
            "Software Engineer, Agents",
            "Software Engineer - Agentic",
            "AI Native Engineer",
        ]:
            in_scope, family = keyword_classify(title)
            assert in_scope is True, f"{title!r} should be IN"
            assert family == "agent-engineer", f"{title!r} → {family!r}"

    def test_master_boolean_applied_ai_titles_route_to_applied_ai(self):
        for title in [
            "GenAI Engineer",
            "AI Enablement Engineer",
            "AI/ML Engineer",
        ]:
            in_scope, family = keyword_classify(title)
            assert in_scope is True, f"{title!r} should be IN"
            assert family == "applied-ai", f"{title!r} → {family!r}"

    def test_member_of_technical_staff_routes_to_agent_engineer(self):
        """MTS is a frontier-startup flat-hierarchy signal — Sierra / Decagon /
        Cognition / Cursor / xAI / Mistral all use it for agent-eng ICs.
        Per _profile/target-roles.md it's in-range, so the keyword classifier
        routes it to agent-engineer; the body-signal upgrader can move it
        elsewhere if the JD is research-flavored."""
        in_scope, family = keyword_classify("Member of Technical Staff")
        assert in_scope is True
        assert family == "agent-engineer"

    def test_out_keyword_beats_in_keyword(self):
        in_scope, family = keyword_classify("Sales Engineer")
        assert in_scope is False
        assert family == "out-of-scope"

    def test_case_insensitive(self):
        assert keyword_classify("ACCOUNT EXECUTIVE")[0] is False
        assert keyword_classify("agent engineer")[0] is True

    def test_sdr_in_parens_still_out(self):
        # Regression: "SDR (Sales Development Rep)" — sdr is followed by '(', not ' '
        assert keyword_classify("SDR (Sales Development Representative)") == (False, "out-of-scope")

    def test_auxiliary_ux_not_false_positive(self):
        # Regression: "auxiliary ux" must NOT trigger OUT via the " ux " substring trick.
        # "Software Engineer, Auxiliary Systems" has no IN keyword match (no backend/frontend/etc.),
        # so it is borderline (None), NOT out-of-scope (False).
        in_scope, _family = keyword_classify("Software Engineer, Auxiliary Systems")
        assert in_scope is not False  # must not be wrongly classified OUT

    def test_standalone_ux_still_out(self):
        assert keyword_classify("Senior UX Designer") == (False, "out-of-scope")


class TestLLMClassify:
    async def test_llm_classify_in_scope(self, monkeypatch):
        from unittest.mock import AsyncMock

        from compass.pipeline import role_family

        fake = AsyncMock()
        fake.run = AsyncMock(
            return_value=type(
                "R",
                (),
                {
                    "output": role_family.RoleFamilyClassification(
                        in_scope=True, role_family="agent-engineer", reason="real eng work in body"
                    )
                },
            )()
        )
        monkeypatch.setattr(role_family, "make_agent", lambda *a, **kw: fake)

        out = await role_family.llm_classify(
            "Solutions Architect", "Build agent pipelines, write Python..."
        )
        assert out.in_scope is True
        assert out.role_family == "agent-engineer"

    async def test_llm_unknown_family_coerced_in_scope(self, monkeypatch):
        from unittest.mock import AsyncMock

        from compass.pipeline import role_family

        fake = AsyncMock()
        fake.run = AsyncMock(
            return_value=type(
                "R",
                (),
                {
                    "output": role_family.RoleFamilyClassification(
                        in_scope=True, role_family="bogus-family", reason="x"
                    )
                },
            )()
        )
        monkeypatch.setattr(role_family, "make_agent", lambda *a, **kw: fake)

        out = await role_family.llm_classify("MTS", "writes systems code...")
        assert out.role_family == "other-eng"


class TestUpgradeFamily:
    def test_specialized_family_unchanged(self):
        from compass.pipeline.role_family import upgrade_family

        assert upgrade_family("agent-engineer", "we sell hammers") == "agent-engineer"
        assert upgrade_family("applied-ai", "non-AI body") == "applied-ai"
        assert upgrade_family("fde-eng", "any body") == "fde-eng"

    def test_swe_backend_no_signal_stays_swe_backend(self):
        from compass.pipeline.role_family import upgrade_family

        body = "Build REST APIs in Go. Postgres. Kafka. SLOs. On-call."
        assert upgrade_family("swe-backend", body) == "swe-backend"

    def test_swe_backend_weak_signal_stays(self):
        from compass.pipeline.role_family import upgrade_family

        body = "We also have an LLM team but you'll work on payments infra."
        assert upgrade_family("swe-backend", body) == "swe-backend"

    def test_swe_backend_strong_agent_signal_promoted(self):
        from compass.pipeline.role_family import upgrade_family

        body = (
            "You'll build agent workflows in LangGraph with tool calling and "
            "MCP servers. Strong agentic AI background required."
        )
        assert upgrade_family("swe-backend", body) == "agent-engineer"

    def test_swe_fullstack_strong_llm_signal_promoted(self):
        from compass.pipeline.role_family import upgrade_family

        body = (
            "Build features powered by Claude and GPT-4. RAG pipeline with "
            "embedding retrieval. Prompt engineering for the assistant UX."
        )
        assert upgrade_family("swe-fullstack", body) == "applied-ai"

    def test_other_eng_strong_ml_signal_promoted(self):
        from compass.pipeline.role_family import upgrade_family

        body = "Train deep learning models in PyTorch. HuggingFace, neural networks."
        assert upgrade_family("other-eng", body) == "applied-ai"

    def test_empty_body_no_promotion(self):
        from compass.pipeline.role_family import upgrade_family

        assert upgrade_family("swe-backend", "") == "swe-backend"
        assert upgrade_family("swe-backend", None) == "swe-backend"

    def test_single_agentic_ai_mention_does_not_promote(self):
        """Regression for substring-overlap bug: 'agentic AI' is ONE phrase, not
        three separate hits via 'agent' ⊂ 'agentic' ⊂ 'agentic ai'."""
        from compass.pipeline.role_family import upgrade_family

        body = "Build backend infra in Go. We use agentic AI internally."
        assert upgrade_family("swe-backend", body) == "swe-backend"

    def test_two_distinct_agent_concepts_promotes(self):
        """Two DIFFERENT agent concepts (e.g. 'agentic ai' + 'mcp') still promote."""
        from compass.pipeline.role_family import upgrade_family

        body = "Build MCP-based servers. Strong agentic AI background required."
        assert upgrade_family("swe-backend", body) == "agent-engineer"

    def test_mcp_matches_without_trailing_space(self):
        """Regression for old keyword 'mcp ' (trailing space). With \\b boundaries,
        'MCP-based' and 'MCP.' now match where the literal-space version missed."""
        from compass.pipeline.role_family import upgrade_family

        # Two distinct AGENT phrases required. Use 'mcp' + 'langgraph' so we
        # isolate the MCP-matching behavior from the agentic-ai phrase.
        body = "Build MCP-based servers using LangGraph for orchestration."
        assert upgrade_family("swe-backend", body) == "agent-engineer"

    def test_agentic_ai_mentioned_twice_still_one_distinct_hit(self):
        """Duplicate mentions of the same phrase count as 1 distinct hit, not 2."""
        from compass.pipeline.role_family import upgrade_family

        body = "agentic AI here. agentic AI there. agentic AI everywhere."
        # Only one distinct AGENT phrase ("agentic ai") — below threshold of 2.
        assert upgrade_family("swe-backend", body) == "swe-backend"
