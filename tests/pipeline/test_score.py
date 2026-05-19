"""Tests for compass.pipeline.nodes.score."""

from datetime import date

from compass.pipeline.state import JobRequirements, JobScore, RawJob


def _state(req):
    return {
        "raw_jobs": [],
        "current_job": RawJob(
            company="sample",
            title="Engineer",
            url="https://example.com/x",
            source="greenhouse",
            description="...",
            date_posted=date.today(),
        ),
        "extracted_requirements": req,
        "score_result": None,
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
    }


async def test_score_node_returns_jobscore(monkeypatch, temp_vault):
    from compass.pipeline.nodes import score

    async def fake_score(req, profile_text: str) -> JobScore:
        return JobScore(
            score=4.2,
            reasoning="Strong MCP match",
            matched_skills=["MCP"],
            missing_skills=["LangGraph"],
            tailoring_notes="Lead with Cisco MCP work.",
        )

    monkeypatch.setattr(score, "_score", fake_score)
    req = JobRequirements(
        required_skills=["MCP", "LangGraph"],
        nice_to_have_skills=[],
        years_experience=2,
        seniority="mid",
        remote_policy="remote",
        summary="...",
    )
    result = await score.score_node(_state(req))
    assert result["score_result"].score == 4.2
    assert "MCP" in result["score_result"].matched_skills


async def test_score_node_missing_requirements_errors(monkeypatch, temp_vault):
    from compass.pipeline.nodes import score

    state = _state(None)
    result = await score.score_node(state)
    assert result["score_result"] is None
    assert any("requirements" in e for e in result.get("errors", []))


async def test_score_node_passes_profile_to_llm(monkeypatch, temp_vault):
    """The profile_text passed to _score includes resume + RAG-retrieved skill chunks."""
    from compass.pipeline.nodes import score
    from compass.rag.retriever import RetrievedChunk

    captured = {}

    async def fake_score(req, profile_text: str) -> JobScore:
        captured["profile_text"] = profile_text
        return JobScore(
            score=3.0, reasoning="", matched_skills=[], missing_skills=[], tailoring_notes=""
        )

    async def fake_retrieve(query, k=8):
        return [RetrievedChunk(skill="Python", document="## Python\nLevel 3.", score=0.9)]

    monkeypatch.setattr(score, "_score", fake_score)
    monkeypatch.setattr(score, "rag_retrieve", fake_retrieve)
    req = JobRequirements(
        required_skills=["Python"],
        nice_to_have_skills=[],
        years_experience=None,
        seniority="mid",
        remote_policy="unknown",
        summary="",
    )
    await score.score_node(_state(req))
    assert "Fake resume body" in captured["profile_text"]
    assert "## Python\nLevel 3." in captured["profile_text"]


async def test_score_node_drops_skills_outside_jd_universe(monkeypatch, temp_vault):
    """Defense in depth: even if the LLM ignores the prompt constraint and lists
    skills outside the JD's required+nice_to_have, the code post-filter strips
    them so gap_aggregator never sees JD-irrelevant skills."""
    from compass.pipeline.nodes import score

    async def hallucinating_score(req, profile_text):
        # Simulate the live-run bug: LLM listed every profile skill as "matched"
        # ignoring the empty required_skills.
        return JobScore(
            score=3.5,
            reasoning="...",
            matched_skills=["Python", "MCP", "LangChain", "AWS"],  # NOT in JD
            missing_skills=["LangGraph", "RAG", "Vector search"],  # NOT in JD
            tailoring_notes="",
        )

    monkeypatch.setattr(score, "_score", hallucinating_score)
    req = JobRequirements(
        required_skills=[],
        nice_to_have_skills=[],
        years_experience=None,
        seniority="mid",
        remote_policy="unknown",
        summary="",
    )
    result = await score.score_node(_state(req))
    assert result["score_result"].matched_skills == []
    assert result["score_result"].missing_skills == []


async def test_score_node_keeps_only_jd_skills(monkeypatch, temp_vault):
    """When LLM mixes JD skills with hallucinated ones, only JD skills survive."""
    from compass.pipeline.nodes import score

    async def mixed_score(req, profile_text):
        return JobScore(
            score=4.0,
            reasoning="...",
            matched_skills=["MCP", "Python", "AWS"],  # MCP and Python are in JD; AWS is not
            missing_skills=["LangGraph", "RAG"],  # LangGraph is in JD; RAG is not
            tailoring_notes="lead with MCP",
        )

    monkeypatch.setattr(score, "_score", mixed_score)
    req = JobRequirements(
        required_skills=["MCP", "Python", "LangGraph"],
        nice_to_have_skills=[],
        years_experience=2,
        seniority="mid",
        remote_policy="remote",
        summary="...",
    )
    result = await score.score_node(_state(req))
    assert set(result["score_result"].matched_skills) == {"MCP", "Python"}
    assert set(result["score_result"].missing_skills) == {"LangGraph"}


async def test_score_node_resolves_matched_missing_overlap(monkeypatch, temp_vault):
    """Regression: when the LLM puts the same skill in both matched and missing
    (Gemini Flash does this on borderline skills), the constraint filter should
    keep it in matched and drop it from missing — otherwise gap_aggregator
    would count a matched skill as a gap."""
    from compass.pipeline.nodes import score

    async def overlapping_score(req, profile_text):
        return JobScore(
            score=4.0,
            reasoning="...",
            matched_skills=["MCP", "Python"],
            missing_skills=["Python", "LangGraph"],  # Python is in BOTH
            tailoring_notes="",
        )

    monkeypatch.setattr(score, "_score", overlapping_score)
    req = JobRequirements(
        required_skills=["MCP", "Python", "LangGraph"],
        nice_to_have_skills=[],
        years_experience=2,
        seniority="mid",
        remote_policy="remote",
        summary="...",
    )
    result = await score.score_node(_state(req))
    assert set(result["score_result"].matched_skills) == {"MCP", "Python"}
    assert set(result["score_result"].missing_skills) == {"LangGraph"}
    # Python must NOT be in both lists:
    overlap = set(result["score_result"].matched_skills) & set(
        result["score_result"].missing_skills
    )
    assert overlap == set()


async def test_score_node_retries_on_truncated_reasoning(monkeypatch, temp_vault):
    """Regression: Gemini Flash occasionally streams a truncated reasoning string
    (e.g. ending mid-clause at 'entirely outside the candidate'). The first call
    returns junk, _score_with_retry catches it and runs once more."""
    from compass.pipeline.nodes import score

    call_count = {"n": 0}

    async def flaky_score(req, profile_text):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return JobScore(
                score=0.0,
                reasoning="entirely outside the candidate",  # no trailing punctuation
                matched_skills=[],
                missing_skills=[],
                tailoring_notes="",
            )
        return JobScore(
            score=0.0,
            reasoning="This role is entirely outside the candidate's domain.",
            matched_skills=[],
            missing_skills=[],
            tailoring_notes="",
        )

    monkeypatch.setattr(score, "_score", flaky_score)
    req = JobRequirements(
        required_skills=[],
        nice_to_have_skills=[],
        years_experience=None,
        seniority="unknown",
        remote_policy="unknown",
        summary="Accounting role.",
    )
    result = await score.score_node(_state(req))
    assert call_count["n"] == 2
    assert result["score_result"].reasoning.endswith(".")


async def test_score_node_no_retry_on_complete_reasoning(monkeypatch, temp_vault):
    """Don't burn a second LLM call when the first response is well-formed."""
    from compass.pipeline.nodes import score

    call_count = {"n": 0}

    async def good_score(req, profile_text):
        call_count["n"] += 1
        return JobScore(
            score=4.0,
            reasoning="Strong overlap on Python and LangGraph evidence.",
            matched_skills=["Python"],
            missing_skills=[],
            tailoring_notes="",
        )

    monkeypatch.setattr(score, "_score", good_score)
    req = JobRequirements(
        required_skills=["Python"],
        nice_to_have_skills=[],
        years_experience=2,
        seniority="mid",
        remote_policy="remote",
        summary="...",
    )
    await score.score_node(_state(req))
    assert call_count["n"] == 1
