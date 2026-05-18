"""
Compass LangGraph pipeline — main graph + orchestration.

Single-job graph: each invocation processes one RawJob via current_job. The
orchestrator `run_pipeline()` does scraping, batch-level URL dedup, parallel
graph invocations bounded by MAX_CONCURRENT_JOBS, post-batch gap-plan
regeneration, and a per-run forensic log row.

Graph flow (per job):
    START -> intake -> extract -> score -> reflect -> hitl ->
        (approved) -> tailor -> vault_write -> END
        (rejected) -> vault_write -> END   (low-score jobs still written for analysis)
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta

import frontmatter
from langgraph.graph import END, START, StateGraph

from compass.analysis import gap_aggregator
from compass.config import MAX_CONCURRENT_JOBS, VAULT_PATH
from compass.pipeline.nodes.extract import extract_node
from compass.pipeline.nodes.hitl import hitl_node
from compass.pipeline.nodes.intake import intake_node
from compass.pipeline.nodes.reflect import reflect_node
from compass.pipeline.nodes.score import score_node
from compass.pipeline.nodes.tailor import tailor_node
from compass.pipeline.nodes.vault_write import vault_write_node
from compass.pipeline.state import CompassState, RawJob
from compass.vault.reader import list_job_notes

logger = logging.getLogger(__name__)


def _route_after_hitl(state: CompassState) -> str:
    """If approved, run tailor; otherwise skip directly to vault_write."""
    return "tailor" if state.get("human_approved") else "vault_write"


def build_graph():
    """Build and compile the single-job Compass graph."""
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
    builder.add_edge("score", "reflect")
    builder.add_edge("reflect", "hitl")
    builder.add_conditional_edges(
        "hitl",
        _route_after_hitl,
        {
            "tailor": "tailor",
            "vault_write": "vault_write",
        },
    )
    builder.add_edge("tailor", "vault_write")
    builder.add_edge("vault_write", END)

    return builder.compile()


def _vault_url_set() -> set[str]:
    """Build the set of URLs already in the vault — ONCE per batch.

    A malformed frontmatter file is logged (NOT silently dropped from the set).
    Without the log, a corrupt note silently causes a duplicate write next run.
    """
    urls: set[str] = set()
    for path in list_job_notes():
        try:
            post = frontmatter.load(path)
        except Exception as e:
            logger.warning("dedup: failed to parse %s — %s", path.name, e)
            continue
        url = post.metadata.get("url")
        if isinstance(url, str):
            urls.add(url)
    return urls


def _initial_state(job: RawJob) -> CompassState:
    return {
        "raw_jobs": [],
        "current_job": job,
        "extracted_requirements": None,
        "score_result": None,
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
    }


def _langfuse_config() -> dict:
    """Return a LangGraph config dict with the Langfuse callback if usable.

    Returns {} when Langfuse env is unset or langfuse fails to import — the
    pipeline never blocks on observability. This wires traces from Phase 0.B
    onward so by 2.B (public-trace polish) we have history to show.
    """
    from compass.config import LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

    if not (LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY):
        return {}
    try:
        from langfuse.langchain import CallbackHandler

        handler = CallbackHandler(
            host=LANGFUSE_HOST,
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
        )
        return {"callbacks": [handler]}
    except Exception as e:
        logger.warning("langfuse: failed to init callback, continuing without traces — %s", e)
        return {}


async def _process_one(graph, job: RawJob, sem: asyncio.Semaphore) -> CompassState:
    async with sem:
        try:
            return await graph.ainvoke(_initial_state(job), config=_langfuse_config())
        except Exception as e:
            # logger.exception preserves the traceback to stderr; the string version
            # below is still aggregated into state for the run summary.
            logger.exception("pipeline: graph crashed on %s", job.url)
            return {**_initial_state(job), "errors": [f"graph: {type(e).__name__}: {e}"]}


async def run_pipeline(raw_jobs: list[RawJob] | None = None) -> CompassState:
    """Scrape (or accept) jobs, dedup, run per-job graph, regenerate gap plan."""
    start = time.monotonic()
    if raw_jobs is None:
        raw_jobs = await _scrape_all()

    seen_urls = _vault_url_set()
    fresh = [j for j in raw_jobs if j.url not in seen_urls]
    dropped = len(raw_jobs) - len(fresh)
    if dropped:
        logger.info("pipeline: dropping %d/%d jobs already in vault", dropped, len(raw_jobs))

    graph = build_graph()
    sem = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
    results = await asyncio.gather(*[_process_one(graph, j, sem) for j in fresh])

    aggregate: CompassState = {
        "raw_jobs": raw_jobs,
        "current_job": None,
        "extracted_requirements": None,
        "score_result": None,
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": any(r.get("vault_written") for r in results),
        "jobs_processed": len(fresh),
        "jobs_written": sum(int(bool(r.get("vault_written"))) for r in results),
        "errors": [e for r in results for e in r.get("errors", [])],
    }

    if aggregate["jobs_written"] > 0:
        gap_aggregator.regenerate(write=True)

    duration_s = time.monotonic() - start
    _append_run_log(aggregate, duration_s)
    unknown_count = _count_unknown_skills_seen_this_run(start)
    logger.info(
        "pipeline: processed=%d written=%d errors=%d unknown_skills_seen=%d duration=%.1fs",
        aggregate["jobs_processed"],
        aggregate["jobs_written"],
        len(aggregate["errors"]),
        unknown_count,
        duration_s,
    )
    return aggregate


def _append_run_log(state: CompassState, duration_s: float) -> None:
    """Append one row per run to `_meta/pipeline-runs.md` — forensic trail + portfolio artifact."""
    log_path = VAULT_PATH / "_meta" / "pipeline-runs.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path.exists():
        log_path.write_text(
            "# Pipeline Run Log\n\n"
            "| Timestamp | Processed | Written | Errors | Duration |\n"
            "|---|---|---|---|---|\n",
            encoding="utf-8",
        )
    ts = datetime.now().isoformat(timespec="seconds")
    row = (
        f"| {ts} | {state['jobs_processed']} | {state['jobs_written']} | "
        f"{len(state['errors'])} | {duration_s:.1f}s |\n"
    )
    with log_path.open("a", encoding="utf-8") as f:
        f.write(row)


def _count_unknown_skills_seen_this_run(start_monotonic: float) -> int:
    """Count rows appended to the unknown-skills log since `start_monotonic`."""
    log_path = VAULT_PATH / "_meta" / "unknown-skills-log.md"
    if not log_path.exists():
        return 0
    approx_wall = datetime.now() - timedelta(seconds=time.monotonic() - start_monotonic)
    cutoff = approx_wall.isoformat(timespec="seconds")
    return sum(
        1
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("[") and line[1:20] >= cutoff[:19]
    )


async def _scrape_all() -> list[RawJob]:
    """Scrape all configured sources concurrently, interleave round-robin, cap.

    Interleaving prevents a single high-volume source from exhausting
    MAX_JOBS_PER_RUN before quieter sources get a chance.
    """
    from compass.config import ASHBY_BOARDS, GREENHOUSE_BOARDS, LEVER_COMPANIES, MAX_JOBS_PER_RUN
    from compass.scrapers.ashby import scrape_ashby_many
    from compass.scrapers.greenhouse import scrape_greenhouse_many
    from compass.scrapers.lever import scrape_lever_many

    gh, lv, ash = await asyncio.gather(
        scrape_greenhouse_many(GREENHOUSE_BOARDS),
        scrape_lever_many(LEVER_COMPANIES),
        scrape_ashby_many(ASHBY_BOARDS),
    )
    interleaved: list[RawJob] = []
    iters = [iter(gh), iter(lv), iter(ash)]
    while iters:
        next_iters = []
        for it in iters:
            try:
                interleaved.append(next(it))
                next_iters.append(it)
            except StopIteration:
                pass
        iters = next_iters
    return interleaved[:MAX_JOBS_PER_RUN]


if __name__ == "__main__":
    result = asyncio.run(run_pipeline())
    print(
        f"Processed: {result['jobs_processed']} | "
        f"Written: {result['jobs_written']} | "
        f"Errors: {len(result['errors'])}"
    )
