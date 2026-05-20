"""Regression: a React Native job at an LLM-native startup whose JD body
mentions LangGraph + multi-agent in passing used to get upgraded from
swe-mobile to agent-engineer (and same for swe-frontend). Mobile and
frontend specialists aren't who Akash is — they're not promotion-eligible
anymore. 2026-05-19 adversarial review (wave 2)."""

from __future__ import annotations

from compass.pipeline.role_family import GENERIC_FAMILIES, upgrade_family


def test_swe_mobile_not_promotion_eligible():
    assert "swe-mobile" not in GENERIC_FAMILIES


def test_swe_frontend_not_promotion_eligible():
    assert "swe-frontend" not in GENERIC_FAMILIES


def test_swe_mobile_stays_mobile_even_with_strong_agent_body():
    """A mobile job whose JD mentions LangGraph + multi-agent should still
    be classified as swe-mobile — Akash isn't a mobile dev."""
    body = (
        "Build React Native iOS apps. Backend team uses LangGraph for "
        "multi-agent orchestration but you'll integrate via REST API."
    )
    result = upgrade_family("swe-mobile", body)
    assert result == "swe-mobile"


def test_swe_frontend_stays_frontend_even_with_strong_agent_body():
    body = "React frontend for an LangGraph multi-agent platform. TypeScript."
    result = upgrade_family("swe-frontend", body)
    assert result == "swe-frontend"


def test_swe_backend_still_promotion_eligible():
    """Backend SWE titles at agent-native companies (Sierra 'Software Engineer,
    Product') ARE legitimately agent-eng IC roles. Keep them eligible."""
    body = (
        "Build LangGraph agents. Tool calling, multi-agent orchestration, "
        "MCP integration. Python/FastAPI backend."
    )
    result = upgrade_family("swe-backend", body)
    assert result == "agent-engineer"
