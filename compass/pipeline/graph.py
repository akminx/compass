"""
Compass LangGraph pipeline — main graph + orchestration.

Single-job graph: each invocation processes one RawJob via current_job. The
orchestrator `run_pipeline()` does scraping, batch-level URL dedup, parallel
graph invocations bounded by MAX_CONCURRENT_JOBS, post-batch gap-plan
regeneration, and a per-run forensic log row.

Graph flow (per job):
    START -> intake -> intake_filter ->
        (out-of-scope) -> END   (logged to _meta/filtered-jobs.md by intake_filter_node)
        (in-scope)     -> extract -> score -> reflect -> hitl ->
            (approved) -> tailor -> vault_write -> END
            (rejected) -> vault_write -> END   (low-score jobs still written for analysis)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime

import frontmatter
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from compass.analysis import gap_aggregator
from compass.config import MAX_CONCURRENT_JOBS, VAULT_PATH
from compass.hitl import state_store
from compass.pipeline.nodes.extract import extract_node
from compass.pipeline.nodes.hitl import hitl_node
from compass.pipeline.nodes.intake import intake_node
from compass.pipeline.nodes.intake_filter import intake_filter_node
from compass.pipeline.nodes.reflect import reflect_node
from compass.pipeline.nodes.score import score_node
from compass.pipeline.nodes.tailor import tailor_node
from compass.pipeline.nodes.vault_write import vault_write_node
from compass.pipeline.state import CompassState, RawJob
from compass.vault.reader import list_job_notes

logger = logging.getLogger(__name__)


def _route_after_filter(state: CompassState) -> str:
    """Out-of-scope JDs short-circuit to END; in-scope continue to extract."""
    return "extract" if state.get("in_scope") is True else "end"


def _route_after_hitl(state: CompassState) -> str:
    """Route based on the explicit `human_approved` value.

    Three-way check so Phase 1.B's real `interrupt()` flow can distinguish:
      True  -> approved, run tailor
      False -> explicit reject, skip tailor
      None  -> hitl never ran / interrupted-and-cancelled, skip tailor

    Today None and False both skip tailor, but the explicit comparison means
    a future "cancelled" branch can be added without restructuring the edge.
    """
    if state.get("human_approved") is True:
        return "tailor"
    return "vault_write"


def build_graph(checkpointer=None):
    builder = StateGraph(CompassState)
    builder.add_node("intake", intake_node)
    builder.add_node("intake_filter", intake_filter_node)
    builder.add_node("extract", extract_node)
    builder.add_node("score", score_node)
    builder.add_node("reflect", reflect_node)
    builder.add_node("hitl", hitl_node)
    builder.add_node("tailor", tailor_node)
    builder.add_node("vault_write", vault_write_node)

    builder.add_edge(START, "intake")
    builder.add_edge("intake", "intake_filter")
    builder.add_conditional_edges(
        "intake_filter",
        _route_after_filter,
        {"extract": "extract", "end": END},
    )
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

    return builder.compile(checkpointer=checkpointer)


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


def _thread_id_for(job_url: str, batch_started_at: datetime) -> str:
    """Deterministic 16-char SHA-1 of (url, batch start) — same batch + same job = same thread."""
    raw = f"{job_url}|{batch_started_at.isoformat()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _initial_state(job: RawJob, thread_id: str | None = None) -> CompassState:
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
        "thread_id": thread_id,
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


async def _process_one(
    graph,
    job: RawJob,
    sem: asyncio.Semaphore,
    thread_id: str,
) -> tuple[CompassState, bool]:
    """Invoke the graph for one job. Returns (final_state, was_paused)."""
    config = {
        "configurable": {"thread_id": thread_id},
        **_langfuse_config(),
    }
    async with sem:
        try:
            result = await graph.ainvoke(_initial_state(job, thread_id=thread_id), config=config)
        except Exception as e:
            logger.exception("pipeline: graph crashed on %s", job.url)
            return (
                {
                    **_initial_state(job, thread_id=thread_id),
                    "errors": [f"graph: {type(e).__name__}: {e}"],
                },
                False,
            )

    # When interrupt() fires, ainvoke returns with state containing the
    # __interrupt__ marker AND without progressing past the hitl node.
    # vault_written stays False, jobs_written stays 0 — that's our signal.
    interrupts = result.get("__interrupt__")
    if interrupts:
        payload = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]
        if isinstance(payload, dict) and payload.get("kind") == "approval_request":
            await state_store.add_pending(
                thread_id=thread_id,
                job_url=payload["job_url"],
                company=payload["company"],
                title=payload["title"],
                score=float(payload["score"]),
                score_reasoning=payload["score_reasoning"],
                matched_skills=list(payload["matched_skills"]),
                missing_skills=list(payload["missing_skills"]),
            )
            logger.info(
                "pipeline: paused %s for approval (thread_id=%s, score=%.2f)",
                job.url,
                thread_id,
                payload["score"],
            )
            return (result, True)
        # Unknown interrupt shape — DO NOT silently swallow. Phase 0 bug pattern:
        # a future interrupt() added elsewhere in the graph would otherwise
        # disappear into a "succeeded with jobs_paused=0" black hole. Log loudly
        # and still count as paused so the caller's bookkeeping reflects reality.
        logger.error(
            "pipeline: graph paused at UNKNOWN interrupt kind for %s — payload=%r",
            job.url,
            payload,
        )
        return (result, True)
    return (result, False)


async def run_pipeline(raw_jobs: list[RawJob] | None = None) -> CompassState:
    """Scrape (or accept) jobs, dedup, run per-job graph under a single
    AsyncSqliteSaver, regenerate gap plan."""
    from compass.config import HITL_CHECKPOINT_DB

    start_monotonic = time.monotonic()
    start_wall = datetime.now()  # captured alongside monotonic; immune to NTP/DST mid-run
    if raw_jobs is None:
        raw_jobs = await _scrape_all()

    seen_urls = _vault_url_set()
    fresh = [j for j in raw_jobs if j.url not in seen_urls]
    dropped = len(raw_jobs) - len(fresh)
    if dropped:
        logger.info("pipeline: dropping %d/%d jobs already in vault", dropped, len(raw_jobs))

    HITL_CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(HITL_CHECKPOINT_DB)) as checkpointer:
        # Enable WAL on the checkpoint DB once per process. Cheap if already set.
        # See state_store._connect for the rationale.
        try:
            await checkpointer.conn.execute("PRAGMA journal_mode=WAL")
            await checkpointer.conn.execute("PRAGMA busy_timeout=5000")
        except Exception:
            logger.debug("checkpoint: WAL pragma set already or unsupported; continuing")
        graph = build_graph(checkpointer=checkpointer)
        sem = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
        coros = [
            _process_one(graph, j, sem, thread_id=_thread_id_for(j.url, start_wall)) for j in fresh
        ]
        results = await asyncio.gather(*coros)

    paused_count = sum(int(p) for _, p in results)
    final_states = [s for s, _ in results]

    aggregate: CompassState = {
        "raw_jobs": raw_jobs,
        "current_job": None,
        "extracted_requirements": None,
        "score_result": None,
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": any(r.get("vault_written") for r in final_states),
        "jobs_processed": len(fresh),
        "jobs_written": sum(int(bool(r.get("vault_written"))) for r in final_states),
        "errors": [e for r in final_states for e in r.get("errors", [])],
        "in_scope": None,
        "role_family": None,
        "thread_id": None,
    }
    # `jobs_paused` is informational only — not in CompassState TypedDict.
    aggregate["jobs_paused"] = paused_count  # type: ignore[typeddict-unknown-key]

    if aggregate["jobs_written"] > 0:
        gap_aggregator.regenerate(write=True)

    duration_s = time.monotonic() - start_monotonic
    _append_run_log(aggregate, duration_s)
    unknown_count = _count_unknown_skills_seen_this_run(start_wall)
    logger.info(
        "pipeline: processed=%d written=%d paused=%d errors=%d unknown_skills_seen=%d duration=%.1fs",
        aggregate["jobs_processed"],
        aggregate["jobs_written"],
        paused_count,
        len(aggregate["errors"]),
        unknown_count,
        duration_s,
    )
    return aggregate


def _append_run_log(state: CompassState, duration_s: float) -> None:
    """Append one row per run to `_meta/pipeline-runs.md` for debugging cron failures."""
    log_path = VAULT_PATH / "_meta" / "pipeline-runs.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path.exists():
        log_path.write_text(
            "# Pipeline Run Log\n\n"
            "| Timestamp | Processed | Written | Paused | Errors | Duration |\n"
            "|---|---|---|---|---|---|\n",
            encoding="utf-8",
        )
    ts = datetime.now().isoformat(timespec="seconds")
    paused = state.get("jobs_paused", 0)  # type: ignore[typeddict-item]
    row = (
        f"| {ts} | {state['jobs_processed']} | {state['jobs_written']} | "
        f"{paused} | {len(state['errors'])} | {duration_s:.1f}s |\n"
    )
    with log_path.open("a", encoding="utf-8") as f:
        f.write(row)


def _count_unknown_skills_seen_this_run(start_wall: datetime) -> int:
    """Count rows appended to the unknown-skills log since `start_wall`.

    Takes wall-clock start directly (captured at run_pipeline entry) instead
    of converting monotonic-to-wall — that conversion drifts on NTP/DST steps
    mid-run.
    """
    log_path = VAULT_PATH / "_meta" / "unknown-skills-log.md"
    if not log_path.exists():
        return 0
    cutoff = start_wall.isoformat(timespec="seconds")
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
        f"Paused: {result.get('jobs_paused', 0)} | "
        f"Errors: {len(result['errors'])}"
    )
