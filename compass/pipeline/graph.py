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
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
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


def _build_checkpoint_serde() -> JsonPlusSerializer:
    """Allow our Pydantic state classes on the msgpack allowlist.

    Must be set at construction — `with_msgpack_allowlist` is a no-op when the
    default `allowed_msgpack_modules=True` (langgraph's non-STRICT default).
    """
    return JsonPlusSerializer(
        allowed_msgpack_modules=[
            ("compass.pipeline.state", "RawJob"),
            ("compass.pipeline.state", "JobRequirements"),
            ("compass.pipeline.state", "JobScore"),
        ]
    )


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
    """Build the set of NORMALIZED URLs already 'seen' by the pipeline — ONCE
    per batch.

    Scopes (all dedup against these):
    - `jobs/`           — current JobNotes
    - `jobs-archive/`   — operator-archived JobNotes; re-surfacing wastes attention
    - `hitl-pending/`   — paused (or already-resolved) approvals; re-pausing the
                          same URL on every run would otherwise create new
                          pending rows with different thread_ids each batch,
                          duplicating the queue.

    Normalization (`compass.vault.url_dedup.normalize_url`) collapses
    case/scheme/trailing-slash/utm-params variants so the same job seen via
    Google and via LinkedIn dedups to one.

    Malformed files are logged, not silently skipped (corrupt note → duplicate
    write next run otherwise).
    """
    import compass.config as cfg
    from compass.vault.url_dedup import normalize_url

    urls: set[str] = set()
    # Job-shaped notes: frontmatter['url'] holds the canonical URL.
    for subdir in ("jobs", "jobs-archive"):
        d = cfg.VAULT_PATH / subdir
        if not d.exists():
            continue
        for path in sorted(d.glob("*.md")):
            try:
                post = frontmatter.load(path)
            except Exception as e:
                logger.warning("dedup: failed to parse %s — %s", path.name, e)
                continue
            url = post.metadata.get("url")
            if isinstance(url, str):
                urls.add(normalize_url(url))
    # HiTL pending notes use frontmatter['job_url'] (different field name).
    hitl_dir = cfg.VAULT_PATH / "hitl-pending"
    if hitl_dir.exists():
        for path in sorted(hitl_dir.glob("*.md")):
            try:
                post = frontmatter.load(path)
            except Exception as e:
                logger.warning("dedup: failed to parse %s — %s", path.name, e)
                continue
            url = post.metadata.get("job_url")
            if isinstance(url, str):
                urls.add(normalize_url(url))
    return urls


def _thread_id_for(job_url: str, batch_started_at: datetime) -> str:
    """Deterministic 16-char SHA-1 of (url, batch start, pid) — same batch + same job = same thread.

    PID is included to disambiguate cross-process collisions (e.g. local CLI
    and Modal cron both starting at the same wall-clock microsecond in 1.B.3).
    """
    import os

    raw = f"{job_url}|{batch_started_at.isoformat()}|{os.getpid()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _initial_state(job: RawJob, thread_id: str | None = None) -> CompassState:
    return {
        "raw_jobs": [],
        "current_job": job,
        "extracted_requirements": None,
        "score_result": None,
        "in_scope": None,
        "role_family": None,
        "agent_signal_count": None,
        "human_approved": None,
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
        "thread_id": thread_id,
        "score_threshold": None,
    }


_langfuse_client_initialized = False


def _langfuse_config() -> dict:
    """Return a LangGraph config dict with the Langfuse callback if usable.

    Langfuse 4.x split credentials away from `CallbackHandler.__init__` — the
    callback now reads from a process-global `Langfuse(...)` singleton (or
    LANGFUSE_* env vars). Earlier code passed `host=`/`secret_key=` directly
    to `CallbackHandler`, which raises TypeError on 4.x and silently disabled
    all tracing.

    Pattern:
      1. Initialize the Langfuse client once (idempotent — singleton).
      2. Construct a CallbackHandler that picks up the singleton's config.

    Returns {} when Langfuse env is unset or langfuse fails to import — the
    pipeline never blocks on observability.
    """
    global _langfuse_client_initialized
    from compass.config import LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

    if not (LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY):
        return {}
    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler

        if not _langfuse_client_initialized:
            Langfuse(
                host=LANGFUSE_HOST,
                public_key=LANGFUSE_PUBLIC_KEY,
                secret_key=LANGFUSE_SECRET_KEY,
            )
            _langfuse_client_initialized = True
        handler = CallbackHandler()
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
            # Mirror to the vault so the user can see paused jobs in Obsidian.
            # Best-effort: vault-write failure never blocks the HiTL flow.
            try:
                from compass.hitl import vault_view

                row = await state_store.get_pending(thread_id)
                if row is not None:
                    vault_view.write_pending_note(row)
            except Exception:
                logger.exception(
                    "pipeline: failed to mirror pending note to vault for %s", thread_id
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

    from compass.vault.url_dedup import normalize_url as _norm_url

    seen_urls = _vault_url_set()
    fresh = [j for j in raw_jobs if _norm_url(j.url) not in seen_urls]
    dropped = len(raw_jobs) - len(fresh)
    if dropped:
        logger.info("pipeline: dropping %d/%d jobs already in vault", dropped, len(raw_jobs))

    HITL_CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(HITL_CHECKPOINT_DB)) as checkpointer:
        checkpointer.serde = _build_checkpoint_serde()
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
        "score_threshold": None,
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
    expected_header = "| Timestamp | Processed | Written | Paused | Errors | Duration |"
    expected_separator = "|---|---|---|---|---|---|"

    if not log_path.exists():
        log_path.write_text(
            f"# Pipeline Run Log\n\n{expected_header}\n{expected_separator}\n",
            encoding="utf-8",
        )
    else:
        # One-time migration: pre-1.B.1 logs are 5-column. Insert a Paused=0
        # column into existing rows so Dataview parses the table correctly.
        text = log_path.read_text(encoding="utf-8")
        if expected_header not in text:
            _migrate_run_log(log_path, text, expected_header, expected_separator)

    ts = datetime.now().isoformat(timespec="seconds")
    paused = state.get("jobs_paused", 0)  # type: ignore[typeddict-item]
    row = (
        f"| {ts} | {state['jobs_processed']} | {state['jobs_written']} | "
        f"{paused} | {len(state['errors'])} | {duration_s:.1f}s |\n"
    )
    with log_path.open("a", encoding="utf-8") as f:
        f.write(row)


def _migrate_run_log(log_path, text: str, expected_header: str, expected_separator: str) -> None:
    """One-time migration: insert Paused=0 column into existing 5-col rows.

    Pre-1.B.1 rows: | ts | processed | written | errors | duration |
    Post-1.B.1 rows: | ts | processed | written | paused | errors | duration |
    """
    new_lines = []
    in_table = False
    migrated_header = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("| Timestamp"):
            new_lines.append(expected_header)
            in_table = True
            migrated_header = True
            continue
        if in_table and stripped.startswith("|---"):
            new_lines.append(expected_separator)
            continue
        if in_table and stripped.startswith("|") and not stripped.startswith("| Timestamp"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) == 5:
                ts, processed, written, errors, duration = cells
                new_lines.append(f"| {ts} | {processed} | {written} | 0 | {errors} | {duration} |")
                continue
            elif len(cells) == 6:
                new_lines.append(line)
                continue
        new_lines.append(line)
    if migrated_header:
        log_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


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


MAX_POSTING_AGE_DAYS = 30  # Drop JDs older than this — postings >30d are usually filled or stale.


async def _scrape_all() -> list[RawJob]:
    """Scrape all configured sources concurrently, drop stale postings, sort
    each board by recency, then interleave round-robin and cap.

    Targeting source of truth: `_profile/target-companies.yaml`. The YAML
    drives which boards get hit — the legacy static `ASHBY_BOARDS` /
    `GREENHOUSE_BOARDS` / `LEVER_COMPANIES` config lists are used only when
    the YAML is missing or empty (fallback for tests + safety net).

    Order matters:
    1. Drop postings with `date_posted` older than MAX_POSTING_AGE_DAYS — stale
       roles aren't worth LLM cost or vault clutter.
    2. Sort each board's results by date_posted DESC (None last) so when the
       interleave-cap below fires, each board contributes its FRESHEST jobs.
    3. Round-robin interleave so a single high-volume board doesn't exhaust
       MAX_JOBS_PER_RUN before quieter boards get a chance.
    4. Cap to MAX_JOBS_PER_RUN.
    """
    from compass.config import ASHBY_BOARDS, GREENHOUSE_BOARDS, LEVER_COMPANIES, MAX_JOBS_PER_RUN
    from compass.scrapers.ashby import scrape_ashby_many
    from compass.scrapers.greenhouse import scrape_greenhouse_many
    from compass.scrapers.lever import scrape_lever_many
    from compass.scrapers.workday import scrape_workday_many

    yaml_slugs = _yaml_scraper_slugs()
    gh_slugs = yaml_slugs.get("greenhouse") or list(GREENHOUSE_BOARDS)
    lv_slugs = yaml_slugs.get("lever") or list(LEVER_COMPANIES)
    ash_slugs = yaml_slugs.get("ashby") or list(ASHBY_BOARDS)
    wd_slugs = yaml_slugs.get("workday") or []

    if yaml_slugs:
        logger.info(
            "scrape: YAML-driven targeting — greenhouse=%d lever=%d ashby=%d workday=%d boards",
            len(gh_slugs),
            len(lv_slugs),
            len(ash_slugs),
            len(wd_slugs),
        )

    gh, lv, ash, wd = await asyncio.gather(
        scrape_greenhouse_many(gh_slugs),
        scrape_lever_many(lv_slugs),
        scrape_ashby_many(ash_slugs),
        scrape_workday_many(wd_slugs),
    )

    gh = _drop_stale_postings(gh)
    lv = _drop_stale_postings(lv)
    ash = _drop_stale_postings(ash)
    wd = _drop_stale_postings(wd)

    interleaved: list[RawJob] = []
    iters = [iter(gh), iter(lv), iter(ash), iter(wd)]
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


def _drop_stale_postings(jobs: list[RawJob]) -> list[RawJob]:
    """Drop >MAX_POSTING_AGE_DAYS-old postings (when date_posted is known);
    preserve input order.

    NOTE: pre-fix this function ALSO sorted by date_posted DESC, which
    un-interleaved the per-board round-robin done inside each `scrape_*_many`.
    That let any high-volume board starve quieter boards out of the global
    cap. The per-board recency sort now happens inside
    `round_robin_by_board` BEFORE the interleave — re-sorting here would
    defeat that.

    Postings without `date_posted` are kept — many ATSes don't expose it
    consistently and we can't tell stale from undated.
    """
    from datetime import date, timedelta

    cutoff = date.today() - timedelta(days=MAX_POSTING_AGE_DAYS)
    return [j for j in jobs if j.date_posted is None or j.date_posted >= cutoff]


# Backward-compat alias: external callers / tests still reference the old name.
_filter_and_sort_by_recency = _drop_stale_postings


def _yaml_scraper_slugs() -> dict[str, list[str]]:
    """Read `_profile/target-companies.yaml` and group eligible boards by ATS
    provider. Returns {} when the YAML is missing — caller falls back to the
    static config lists.

    Default tier scope is `apply-now` only — the immediate-target cluster.
    Other tiers (e.g. `opportunistic`) can be opted in via the
    `COMPASS_SCRAPE_TIERS` env var (comma-separated tier names) when the
    operator wants broader coverage.

    Tiers further down the funnel (`backend-prep`, `stretch`) are never
    scraped.
    """
    import os

    from compass.vault.target_companies import list_yaml_companies, refresh_yaml

    refresh_yaml()
    by_provider: dict[str, list[str]] = {
        "greenhouse": [],
        "lever": [],
        "ashby": [],
        "workday": [],
    }
    # Default: apply-now only. Override via `COMPASS_SCRAPE_TIERS=apply-now,opportunistic`.
    tier_env = os.getenv("COMPASS_SCRAPE_TIERS", "apply-now").strip()
    tiers = tuple(t.strip() for t in tier_env.split(",") if t.strip()) or ("apply-now",)
    for tier in tiers:
        for entry in list_yaml_companies(tier_filter=tier):
            ats = entry.get("ats") or {}
            provider = (ats.get("provider") or "").lower()
            slug = ats.get("slug")
            if provider not in by_provider or not slug:
                continue
            if slug not in by_provider[provider]:
                by_provider[provider].append(slug)
    return {k: v for k, v in by_provider.items() if v}


def _date_to_ordinal(d: object) -> int:
    """date.toordinal() wrapper that treats None as 0 — only used for sort key."""
    from datetime import date

    if isinstance(d, date):
        return d.toordinal()
    return 0


if __name__ == "__main__":
    result = asyncio.run(run_pipeline())
    print(
        f"Processed: {result['jobs_processed']} | "
        f"Written: {result['jobs_written']} | "
        f"Paused: {result.get('jobs_paused', 0)} | "
        f"Errors: {len(result['errors'])}"
    )
