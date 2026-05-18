"""
Compass LangGraph pipeline — main graph definition.

Entry point: run with `uv run python -m compass.pipeline.graph`

Graph flow:
    START → intake → extract → score → [reflect if borderline] → hitl → tailor → vault_write → END

Nodes live in compass/pipeline/nodes/.
State schema is in compass/pipeline/state.py.
All LLM calls are traced via Langfuse — set LANGFUSE_* env vars.
"""

from langfuse.callback import CallbackHandler
from langgraph.graph import END, START, StateGraph

from compass.config import SCORE_THRESHOLD
from compass.pipeline.nodes.extract import extract_node
from compass.pipeline.nodes.hitl import hitl_node
from compass.pipeline.nodes.intake import intake_node
from compass.pipeline.nodes.reflect import reflect_node
from compass.pipeline.nodes.score import score_node
from compass.pipeline.nodes.tailor import tailor_node
from compass.pipeline.nodes.vault_write import vault_write_node
from compass.pipeline.state import CompassState


def should_reflect(state: CompassState) -> str:
    """Route to reflection node for borderline scores, HiTL for high scores, vault for low."""
    score = state.get("score_result")
    if score is None:
        return "vault_write"
    s = score.score
    if s < SCORE_THRESHOLD - 0.5:
        return "vault_write"
    elif s < SCORE_THRESHOLD:
        return "reflect"
    else:
        return "hitl"


def should_proceed_after_reflect(state: CompassState) -> str:
    """After reflection, route to HiTL if revised score qualifies, otherwise vault."""
    score = state.get("score_result")
    if score and score.score >= SCORE_THRESHOLD:
        return "hitl"
    return "vault_write"


def should_tailor(state: CompassState) -> str:
    """After HiTL interrupt, route to tailor if approved, vault_write if not."""
    if state.get("human_approved"):
        return "tailor"
    return "vault_write"


def build_graph() -> StateGraph:
    """Build and compile the Compass pipeline graph."""
    builder = StateGraph(CompassState)

    builder.add_node("intake", intake_node)
    builder.add_node("extract", extract_node)
    builder.add_node("score", score_node)
    builder.add_node("reflect", reflect_node)
    builder.add_node("hitl", hitl_node)
    builder.add_node("tailor", tailor_node)
    builder.add_node("vault_write", vault_write_node)

    builder.add_edge(START, "intake")
    builder.add_edge("intake", "extract")
    builder.add_edge("extract", "score")
    builder.add_conditional_edges(
        "score",
        should_reflect,
        {
            "reflect": "reflect",
            "hitl": "hitl",
            "vault_write": "vault_write",
        },
    )
    builder.add_conditional_edges(
        "reflect",
        should_proceed_after_reflect,
        {
            "hitl": "hitl",
            "vault_write": "vault_write",
        },
    )
    builder.add_conditional_edges(
        "hitl",
        should_tailor,
        {
            "tailor": "tailor",
            "vault_write": "vault_write",
        },
    )
    builder.add_edge("tailor", "vault_write")
    builder.add_edge("vault_write", END)

    return builder.compile()


graph = build_graph()


async def run_pipeline(raw_jobs=None) -> CompassState:
    """Run the full pipeline. If raw_jobs is None, scrapes fresh from all ATS sources."""
    import asyncio

    from compass.config import ASHBY_BOARDS, GREENHOUSE_BOARDS, LEVER_COMPANIES
    from compass.scrapers.ashby import scrape_ashby_many
    from compass.scrapers.greenhouse import scrape_greenhouse_many
    from compass.scrapers.lever import scrape_lever_many

    if raw_jobs is None:
        gh, lv, ash = await asyncio.gather(
            scrape_greenhouse_many(GREENHOUSE_BOARDS),
            scrape_lever_many(LEVER_COMPANIES),
            scrape_ashby_many(ASHBY_BOARDS),
        )
        raw_jobs = gh + lv + ash

    langfuse_handler = CallbackHandler()
    initial_state: CompassState = {
        "raw_jobs": raw_jobs,
        "current_job": None,
        "extracted_requirements": None,
        "score_result": None,
        "human_approved": None,
        "human_feedback": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
    }

    result = await graph.ainvoke(
        initial_state,
        config={"callbacks": [langfuse_handler]},
    )
    return result


if __name__ == "__main__":
    import asyncio

    result = asyncio.run(run_pipeline())
    print(
        f"Processed: {result['jobs_processed']} | Written: {result['jobs_written']} | Errors: {len(result['errors'])}"
    )
