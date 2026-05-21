"""Cost estimation for eval runs.

We don't have direct access to OpenRouter's per-call usage payload in the
extract/score paths (pydantic-ai's Agent wraps it), so we estimate tokens
from string length using the industry-standard ~4-chars-per-token rule.
Within 10-15% of real numbers for English JD/profile text. Good enough for
a portfolio cost/accuracy table; would need real-usage hooks for a billing
dashboard.

Prices are USD per 1M tokens, sourced from OpenRouter list pricing 2026-05.
Update when models change — the table is the source of truth for the eval
results table in the README.
"""

from __future__ import annotations

from dataclasses import dataclass

# (input $/1M, output $/1M)
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "google/gemini-2.5-flash": (0.10, 0.40),
    "google/gemini-2.5-flash-lite": (0.05, 0.20),
    "google/gemini-2.5-pro": (1.25, 5.00),
    "anthropic/claude-sonnet-4": (3.00, 15.00),
    "anthropic/claude-sonnet-4-6": (3.00, 15.00),
    "anthropic/claude-sonnet-4-7": (3.00, 15.00),
    "anthropic/claude-haiku-4-5": (1.00, 5.00),
    "openai/gpt-4o": (2.50, 10.00),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "meta-llama/llama-3.3-70b-instruct": (0.20, 0.60),
}

_DEFAULT_PRICING = (1.00, 3.00)  # fallback for unknown models — flagged as estimate


@dataclass
class CallCost:
    """Token + USD estimate for one LLM call."""

    model: str
    input_chars: int
    output_chars: int
    input_tokens: int  # estimated: chars / 4
    output_tokens: int
    cost_usd: float
    is_estimated_pricing: bool  # True when model isn't in _MODEL_PRICING


def estimate_cost(model: str, input_text: str, output_text: str) -> CallCost:
    """Estimate cost of one LLM call from prompt + output strings.

    Returns CallCost with token counts AND USD. Token counts use the
    4-chars-per-token rule — accurate within ~15% for English. For non-English
    or code-heavy prompts, real tokenization would differ; we accept that
    error for portfolio purposes and flag the model row if unpriced.
    """
    pricing = _MODEL_PRICING.get(model)
    is_est = pricing is None
    in_per_m, out_per_m = pricing or _DEFAULT_PRICING
    in_tok = max(1, len(input_text) // 4)
    out_tok = max(1, len(output_text) // 4)
    cost = (in_tok / 1_000_000) * in_per_m + (out_tok / 1_000_000) * out_per_m
    return CallCost(
        model=model,
        input_chars=len(input_text),
        output_chars=len(output_text),
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
        is_estimated_pricing=is_est,
    )
