"""Run one representative JD through the full LangGraph pipeline to produce
a Langfuse trace. Used to capture the README screenshot.

The JD is the synthetic AgentLab Senior Agent Engineer posting from the eval
dataset — a strong-fit role chosen specifically because the resulting trace
exercises every node in the graph (extract → RAG → 3× scorer ensemble →
role-family cap → reflect → HiTL → tailor → vault_write).

Pre-reqs:
  - Langfuse running on localhost:3000 with API keys in .env
  - SCORE_ENSEMBLE_N=3 in .env (so the trace shows the self-consistency stack)

Run:
  uv run python -m scripts.demo_trace
"""

from __future__ import annotations

import asyncio
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from compass.pipeline.graph import run_pipeline  # noqa: E402
from compass.pipeline.state import RawJob  # noqa: E402

DEMO_JD = """About AgentCo
AgentCo (Series A, 25 people) is building a vertical AI agent for the legal industry.

About the role
Agent Engineer. You will implement new agent capabilities under the guidance of the
founding engineering team — tool integrations, retrieval improvements, evaluation
cases — and own a small portion of the eval suite end to end.

What you'll do
- Build agent capabilities in Python: tool integrations, retrieval pipelines, prompt
  iteration, evaluation cases.
- Triage failure modes from customer-facing logs. Write reproductions, propose fixes.
- Own a small portion of the eval suite end to end. We take eval discipline seriously.
- Pair with the founding engineering team daily.

What we're looking for
- 0–3 years professional engineering experience, or a strong intern portfolio.
- Comfortable writing Python end to end. Async / typed Python a plus.
- Have built at least one non-trivial LLM-powered side project. Show us the repo.
- Curiosity about agent architecture, prompt engineering, evaluation methodology.

Nice to have
- Familiarity with LangGraph, Pydantic AI, DSPy, or another agent framework.
- Built or contributed to an MCP server or client.
- Exposure to vector databases / RAG.

Compensation: $140K–$180K + equity. In-person SF.
""".strip()


async def main() -> int:
    # Force ensemble=3 for the demo so the trace shows the self-consistency stack
    os.environ.setdefault("SCORE_ENSEMBLE_N", "3")
    job = RawJob(
        company="AgentCo",
        title="Agent Engineer",
        url=f"demo://compass-portfolio-trace-{os.urandom(4).hex()}",
        source="manual",
        description=DEMO_JD,
    )
    result = await run_pipeline([job])
    print(f"\nrun complete — processed={result.get('jobs_processed')} "
          f"written={result.get('jobs_written')} errors={result.get('errors')}")
    # `run_pipeline` flushes Langfuse, but call again defensively to make
    # sure interactive Ctrl-C-after-prompt doesn't lose anything.
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:
        pass
    print("Open http://localhost:3000 → Tracing → Traces to see the run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
