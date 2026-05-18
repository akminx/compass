"""
Model resolver + Agent factory for Compass pipeline nodes.

Routes per-node model selection through OpenRouter. Env vars are read at
call time (not import or cache) so tests can swap models per-test and
production hot-reloads pick up `.env` changes after a restart only.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

if TYPE_CHECKING:
    from pydantic import BaseModel

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_NODE_ENV: dict[str, str] = {
    "extract": "EXTRACT_MODEL",
    "score": "SCORE_MODEL",
    "reflect": "REFLECT_MODEL",
    "tailor": "TAILOR_MODEL",
    "assessor": "ASSESSOR_MODEL",
}


def get_model_id(node: str) -> str:
    """Return the OpenRouter model id for a node, reading env at call time."""
    env_name = _NODE_ENV.get(node)
    if env_name is None:
        raise ValueError(f"unknown node {node!r}; expected one of {sorted(_NODE_ENV)}")
    model_id = os.environ.get(env_name)
    if not model_id:
        raise ValueError(f"no model configured for node {node!r} (env {env_name} unset)")
    return model_id


def _get_model(node: str) -> OpenAIChatModel:
    """Build a pydantic-ai OpenAIChatModel pointed at OpenRouter for this node."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is not set")
    provider = OpenAIProvider(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    return OpenAIChatModel(get_model_id(node), provider=provider)


def make_agent(
    node: str,
    *,
    output_type: type[BaseModel],
    system_prompt: str,
) -> Agent:
    """Construct a pydantic-ai Agent for a node with the routed model + provider.

    Explicit keyword-only args (no **kwargs) so call sites are self-documenting
    and typos surface at type-check time, not at runtime.
    """
    return Agent(_get_model(node), output_type=output_type, system_prompt=system_prompt)
