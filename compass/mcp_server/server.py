"""
Compass MCP server — exposes vault, pipeline, assessor, and gap aggregator as tools.

Run: uv run python -m compass.mcp_server.server

Add to Claude Code MCP config:
{
  "mcpServers": {
    "compass": {
      "command": "uv",
      "args": ["run", "python", "-m", "compass.mcp_server.server"],
      "cwd": "/path/to/compass"
    }
  }
}

Tools exposed:
  Pipeline:
    score_jd(jd_text)                       -> JobScore for a pasted JD

  Vault:
    search_jobs(query, limit)               -> matching job notes
    get_skill_gaps(job_id)                  -> missing skills for a job
    get_profile(section)                    -> read a _profile/ section
    read_learning_artifact(uri)             -> resolve learning-vault:// URI

  Analysis:
    assess_skills(scope=None)               -> regrade evidence-backed skills
    regenerate_gap_plan()                   -> rebuild master-gap-plan.md
    get_master_gap_plan()                   -> read top gaps now

  Evidence helpers:
    suggest_evidence(skill, search_terms)   -> candidate learning-vault files
    list_canonical_skills()                 -> all skills from taxonomy

  Application lifecycle:
    add_application(job_id)                 -> create ApplicationNote, mark job applied
    update_application_status(app_id, ...)  -> transition status with optional next-action fields
    list_pending_actions(through_date)      -> ApplicationNotes with due next_action_date
    tailor_resume(job_id)                   -> tailoring suggestions from JobNote frontmatter
    archive_marked_jobs()                   -> bulk-move JobNotes tagged manual_action:archive

  HiTL approvals:
    pending_approvals()                     -> paused threads awaiting approval (oldest first)
    approve(thread_id, approved, feedback)  -> resume a paused thread; runs tailor on approve
    sync_pending_decisions()                -> bulk-apply Obsidian-edited statuses
    regenerate_pending_notes()              -> rewrite hitl-pending/*.md from state_store DB
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from compass.analysis import gap_aggregator, skill_assessor
from compass.config import VAULT_PATH
from compass.hitl import state_store as _state_store
from compass.hitl.resume import resume_pending as _resume_pending
from compass.vault.learning_bridge import path_to_uri, resolve, scan_evidence
from compass.vault.taxonomy import all_canonicals

logger = logging.getLogger(__name__)

mcp = FastMCP("compass")


# ── Pipeline-side ────────────────────────────────────────────────────────────


@mcp.tool()
async def score_jd(jd_text: str) -> dict:
    """Score a pasted JD against the candidate profile. Does NOT write to the vault.

    Runs only extract + score — bypasses tailor (Sonnet, ~$0.05/call) and
    vault_write so this is cheap (~$0.003) and side-effect-free. Returns the
    extracted requirements alongside the score so the caller sees what the
    LLM thought the JD was asking for.
    """
    from datetime import date

    from compass.pipeline.nodes.extract import extract_node
    from compass.pipeline.nodes.score import score_node
    from compass.pipeline.state import CompassState, RawJob

    job = RawJob(
        company="(adhoc)",
        title="(adhoc)",
        url="adhoc://" + str(hash(jd_text)),
        source="manual",
        description=jd_text,
        date_posted=date.today(),
    )
    state: CompassState = {
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
        "thread_id": None,
        "score_threshold": None,
    }
    extract_result = await extract_node(state)
    if extract_result.get("errors"):
        return {"error": extract_result["errors"][-1]}
    state = {**state, **extract_result}
    score_result = await score_node(state)
    if score_result.get("errors"):
        return {"error": score_result["errors"][-1]}
    state = {**state, **score_result}
    score = state.get("score_result")
    req = state.get("extracted_requirements")
    if score is None:
        return {"error": "no score produced"}
    return {
        "score": score.model_dump(),
        "requirements": req.model_dump() if req else None,
    }


@mcp.tool()
async def add_job_from_url(
    url: str,
    company: str | None = None,
    title: str | None = None,
) -> dict:
    """Fetch a JD by URL, run the full Compass pipeline, write a JobNote.

    Unlocks every site Compass's auto-scrapers can't reach: JPM Oracle
    Cloud, Capital One, iCIMS, LinkedIn, custom careers pages. The user
    finds the role manually and pastes the URL — Compass scores it.

    Strategy:
      1. If the URL matches a known ATS pattern (greenhouse/lever/ashby/
         workday public JSON), use the structured scraper for clean data.
      2. Otherwise, static-fetch the page + strip HTML. Many corporate
         careers pages (Oracle Cloud, LinkedIn) are JS-rendered and will
         return a near-empty body — in that case the caller should use
         `add_job_from_text` and paste the JD body explicitly.

    Returns {"path": str, "score": float, "title": str, "company": str} on
    success, {"error": str} on failure. Does NOT call tailor (skip Sonnet
    cost on this codepath — caller can re-invoke tailor explicitly later).
    """
    from compass.pipeline.add_url import fetch_rawjob_from_url

    try:
        job = await fetch_rawjob_from_url(url, company=company, title=title)
    except Exception as e:
        return {"error": f"fetch failed: {type(e).__name__}: {e}"}
    if job is None:
        return {"error": "could not extract JD from URL — try add_job_from_text"}
    return await _run_partial_pipeline_and_write(job)


@mcp.tool()
async def add_job_from_text(
    company: str,
    title: str,
    url: str,
    jd_text: str,
) -> dict:
    """Run the Compass pipeline on a pasted JD (for sites we can't fetch).

    Use when `add_job_from_url` returns "could not extract" — typical for
    JPM Oracle Cloud, LinkedIn JS-rendered pages, Workday tenants not in
    the YAML. Paste the JD body from the browser; Compass scores it and
    writes a JobNote with the original URL.

    Returns {"path": str, "score": float, ...} on success.
    """
    from datetime import date
    from urllib.parse import urlparse

    from compass.pipeline.state import RawJob

    # Same scheme allowlist as add_job_from_url — block file:/ftp:/javascript:
    # /data: URLs from being persisted as JobNote.url. Without this, a typo or
    # malicious paste could write a bogus URL into the vault.
    scheme = (urlparse(url).scheme or "").lower()
    if scheme not in {"http", "https"}:
        return {"error": f"only http/https URLs allowed, got scheme={scheme!r}"}
    if not company or not company.strip():
        return {"error": "company must be a non-empty string"}
    if not title or not title.strip():
        return {"error": "title must be a non-empty string"}

    job = RawJob(
        company=company,
        title=title,
        url=url,
        source="manual",
        description=jd_text,
        date_posted=date.today(),
    )
    return await _run_partial_pipeline_and_write(job)


async def _run_partial_pipeline_and_write(job) -> dict:
    """Shared helper: intake_filter → extract → score → vault_write.

    Skips tailor (Sonnet cost) and HiTL (the user already chose to add this
    JD by URL — they've implicitly approved). gap_aggregator NOT run inline;
    the next batch run picks up the new JobNote.
    """
    from compass.pipeline.nodes.extract import extract_node
    from compass.pipeline.nodes.intake_filter import intake_filter_node
    from compass.pipeline.nodes.score import score_node
    from compass.pipeline.nodes.vault_write import vault_write_node
    from compass.pipeline.state import CompassState  # noqa: TC001

    state: CompassState = {
        "raw_jobs": [],
        "current_job": job,
        "extracted_requirements": None,
        "score_result": None,
        "in_scope": None,
        "role_family": None,
        "agent_signal_count": None,
        "human_approved": True,  # implicit approval by adding via URL
        "human_feedback": None,
        "tailored_paragraph": None,
        "vault_written": False,
        "jobs_processed": 0,
        "jobs_written": 0,
        "errors": [],
        "thread_id": None,
        "score_threshold": None,
    }
    for node in (intake_filter_node, extract_node, score_node, vault_write_node):
        update = await node(state)
        state = {**state, **update}  # type: ignore[typeddict-item]
        if state.get("errors"):
            return {"error": state["errors"][-1]}
        if state.get("in_scope") is False:
            return {
                "error": "intake_filter dropped the JD — see _meta/filtered-jobs.md",
                "role_family": state.get("role_family"),
            }
    score = state.get("score_result")
    if score is None:
        return {"error": "score node returned None"}
    return {
        "path": "vault/jobs/" + (job.company + "-" + job.title),
        "company": job.company,
        "title": job.title,
        "score": score.score,
        "score_reasoning": score.reasoning,
        "matched_skills": score.matched_skills,
        "missing_skills": score.missing_skills,
        "role_family": state.get("role_family"),
        "agent_signal_count": state.get("agent_signal_count"),
    }


@mcp.tool()
async def run_evals(mode: str = "labels", limit: int | None = None) -> dict:
    """Run the Compass eval harness — measures extract + score accuracy.

    `mode`:
      "labels" (default) — compare against EvalRecord.expected_* hand-labels
                            in compass/evals/labeled_dataset.json.
      "judge"            — LLM-as-judge mode, no hand labels needed. Use for
                            first-pass sanity checks.

    `limit`: optionally sample N records instead of the full dataset.

    Returns metrics summary + path to per-record results JSON.
    """
    from compass.evals.runner import run_evals as _run

    result = await _run(mode=mode, limit=limit)
    if "error" in result:
        return {"error": result["error"]}
    m = result["metrics"]
    return {
        "mode": mode,
        "n_records": m.n,
        "score_mae": round(m.score_mae, 3),
        "score_rmse": round(m.score_rmse, 3),
        "score_bias": round(m.score_bias, 3),
        "extract_skill_recall": round(m.extract_skill_recall, 3),
        "extract_skill_precision": round(m.extract_skill_precision, 3),
        "match_skill_recall": round(m.match_skill_recall, 3),
        "results_path": result["results_path"],
    }


@mcp.tool()
async def generate_cover_letter(job_filename: str) -> dict:
    """Draft a cover letter for a JobNote in the vault.

    `job_filename` is the base name of a file in `compass-vault/jobs/`
    (e.g. `2026-05-19-databricks-AI_Engineer-abcdef12.md`). The tool reads
    the JobNote's frontmatter (company / title / skills / JD summary),
    pulls the company's targeting notes from YAML if available, and writes
    a structured 250-400 word cover letter to
    `compass-vault/cover-letters/`.

    Use this AFTER you decide to apply to a role — it's a Sonnet call so
    don't burn it on the whole vault.

    Returns {"path": str, "preview": str (first 300 chars)} on success.
    """
    from compass.config import VAULT_PATH
    from compass.pipeline.cover_letter import generate_cover_letter_from_jobnote

    # Path-traversal guard: `job_filename` is user-supplied; reject anything
    # that resolves outside compass-vault/jobs/. Without this, a string like
    # "../_profile/resume.md" would load + cover-letter-ize the resume file.
    jobs_dir = (VAULT_PATH / "jobs").resolve()
    job_path = (VAULT_PATH / "jobs" / job_filename).resolve()
    try:
        job_path.relative_to(jobs_dir)
    except ValueError:
        return {"error": f"job_filename must be inside jobs/: {job_filename!r}"}
    if not job_path.exists():
        return {"error": f"JobNote not found: {job_filename}"}
    try:
        out_path, body = await generate_cover_letter_from_jobnote(job_path)
    except Exception as e:
        logger.exception("generate_cover_letter: failed")
        return {"error": f"{type(e).__name__}: {e}"}
    return {
        "path": str(out_path.relative_to(VAULT_PATH)),
        "preview": body[:300] + ("…" if len(body) > 300 else ""),
    }


# ── Vault read ───────────────────────────────────────────────────────────────


@mcp.tool()
def search_jobs(query: str, limit: int = 10) -> list[dict]:
    """Substring/keyword search over vault job notes. Returns frontmatter dicts."""
    from compass.analysis.gap_aggregator import _parse_frontmatter

    hits = []
    for f in (VAULT_PATH / "jobs").glob("*.md"):
        fm = _parse_frontmatter(f)
        text = f.read_text(encoding="utf-8").lower()
        if query.lower() in text:
            hits.append({"file": str(f.name), **fm})
    hits.sort(key=lambda h: h.get("match_score", 0), reverse=True)
    return hits[:limit]


@mcp.tool()
def get_skill_gaps(job_id: str) -> dict:
    """For a given job (filename substring), return matched + missing skills.

    Case-insensitive match — scraper board_tokens are usually lowercase but
    users naturally capitalize. See `find_jobnote` in compass.applications.
    """
    from compass.analysis.gap_aggregator import _parse_frontmatter

    job_id_lower = job_id.lower()
    for f in (VAULT_PATH / "jobs").glob("*.md"):
        if job_id_lower in f.name.lower():
            fm = _parse_frontmatter(f)
            return {
                "job": f.name,
                "skills_required": fm.get("skills_required", []),
                "skills_matched": fm.get("skills_matched", []),
                "skills_missing": fm.get("skills_missing", []),
            }
    return {"error": f"no job matched '{job_id}'"}


@mcp.tool()
def get_profile(section: str) -> str:
    """Read a file from _profile/. section is the bare filename (e.g. 'resume', 'skill-inventory').

    SECURITY: validates that the resolved path stays inside `_profile/`. Pre-fix,
    a section like `../.env` resolved to the vault root and could leak the
    user's API keys. The same path-containment pattern is used in
    `generate_cover_letter` and `_load_jobnote` for the same threat class.

    Late-binds VAULT_PATH via `cfg.VAULT_PATH` so the temp_vault test fixture's
    monkeypatch works — see CLAUDE.md lesson #2.
    """
    import compass.config as cfg

    profile_dir = (cfg.VAULT_PATH / "_profile").resolve()
    path = (cfg.VAULT_PATH / "_profile" / f"{section}.md").resolve()
    try:
        path.relative_to(profile_dir)
    except ValueError:
        return f"(invalid section name — must be inside _profile/: {section!r})"
    if not path.exists():
        return f"(no such profile section: {section})"
    return path.read_text(encoding="utf-8")


@mcp.tool()
def read_learning_artifact(uri: str) -> dict:
    """Resolve a learning-vault:// URI and return the snippet + metadata."""
    artifact = resolve(uri, snippet_chars=4000)
    if artifact is None:
        return {"error": f"could not resolve {uri}"}
    return {
        "uri": artifact.uri,
        "kind": artifact.kind,
        "last_modified": artifact.last_modified.isoformat(),
        "snippet": artifact.snippet,
    }


# ── Analysis ─────────────────────────────────────────────────────────────────


@mcp.tool()
async def assess_skills(scope: list[str] | None = None) -> list[dict]:
    """Regrade evidence-backed skills against the rubric. Pass scope=None for all."""
    results = await skill_assessor.assess_many(scope)
    return [a.model_dump() for a in results]


@mcp.tool()
def regenerate_gap_plan() -> dict:
    """Recompute the master gap plan from current jobs + skill levels + tier weights."""
    entries, _ = gap_aggregator.regenerate(write=True)
    return {
        "skills_tracked": len(entries),
        "top_gaps": [e.model_dump() for e in entries[:10]],
    }


@mcp.tool()
def get_master_gap_plan() -> str:
    """Return the current master-gap-plan.md contents."""
    from compass.config import MASTER_GAP_PLAN_PATH

    if not MASTER_GAP_PLAN_PATH.exists():
        return "(no master-gap-plan yet — run regenerate_gap_plan first)"
    return MASTER_GAP_PLAN_PATH.read_text(encoding="utf-8")


# ── Evidence helpers ─────────────────────────────────────────────────────────


@mcp.tool()
def suggest_evidence(skill: str, search_terms: list[str] | None = None) -> list[str]:
    """Surface learning-vault files that might be evidence for a skill (you decide whether to cite)."""
    paths = scan_evidence(skill, search_terms)
    return [path_to_uri(p) for p in paths]


@mcp.tool()
def list_canonical_skills() -> list[str]:
    """Return every canonical skill name from _meta/skill-taxonomy.md."""
    return all_canonicals()


# ── Tailoring / application ──────────────────────────────────────────────────


@mcp.tool()
def add_application(
    job_id: str,
    resume_variant: str = "resume.md",
    referral: bool = False,
    force: bool = False,
) -> dict:
    """Create an ApplicationNote linked to a JobNote. Marks the JobNote as applied.

    job_id: substring of the JobNote filename (e.g. 'Sierra-Agent_Engineer') or
            the JobNote's url field. Returns an error dict if zero or >1 match.

    force: pass True to overwrite an existing ApplicationNote (use for reposted
           jobs). Default False refuses overwrite to protect status-transition
           history on in-flight applications.
    """
    from compass.applications.lifecycle import add_application as _add

    try:
        note = _add(job_id, resume_variant=resume_variant, referral=referral, force=force)
    except (LookupError, FileExistsError) as e:
        return {"error": str(e)}
    return note.model_dump(mode="json")


@mcp.tool()
def update_application_status(
    app_id: str,
    status: str,
    next_action: str | None = None,
    next_action_date: str | None = None,
    clear_next_action: bool = False,
    clear_next_action_date: bool = False,
    force: bool = False,
) -> dict:
    """Transition an application's status. Refuses invalid transitions unless force=True.

    Next-action fields use explicit clear flags because MCP can't transmit a
    Python sentinel. To CLEAR an existing next_action or next_action_date,
    pass clear_next_action=True or clear_next_action_date=True. Passing the
    bare arg with no value (None) preserves the existing field.
    """
    from datetime import date as _date

    from compass.applications.lifecycle import _UNSET
    from compass.applications.lifecycle import update_application_status as _upd

    if clear_next_action:
        na: object = None
    elif next_action is not None:
        na = next_action
    else:
        na = _UNSET

    if clear_next_action_date:
        nad: object = None
    elif next_action_date is not None:
        try:
            nad = _date.fromisoformat(next_action_date)
        except ValueError as e:
            return {"error": f"invalid next_action_date: {e}"}
    else:
        nad = _UNSET

    try:
        note = _upd(app_id, status, next_action=na, next_action_date=nad, force=force)
    except (LookupError, ValueError) as e:
        return {"error": str(e)}
    return note.model_dump(mode="json")


@mcp.tool()
def list_pending_actions(through_date: str | None = None) -> list[dict]:
    """Return ApplicationNotes whose next_action_date <= through_date (default: today)."""
    from datetime import date as _date

    from compass.applications.lifecycle import list_pending_actions as _pending

    cutoff = _date.fromisoformat(through_date) if through_date else None
    return _pending(cutoff)


@mcp.tool()
async def tailor_resume(job_id: str) -> dict:
    """Return tailoring suggestions for a specific JobNote. Reads existing
    tailored_paragraph if present, otherwise indicates the job hasn't been tailored.

    This is a read-only tool — re-running the tailor LLM on demand is deferred
    to a later phase (force-tailor MCP tool)."""
    import frontmatter

    from compass.applications.lifecycle import find_jobnote

    try:
        path = find_jobnote(job_id)
    except LookupError as e:
        return {"error": str(e)}
    md = frontmatter.load(path).metadata
    return {
        "company": md["company"],
        "title": md["title"],
        "tailored_paragraph": md.get("tailored_paragraph")
        or "(not yet tailored — re-run pipeline with score >= threshold)",
        "skills_matched": md.get("skills_matched", []),
        "skills_missing": md.get("skills_missing", []),
    }


# ── HiTL approvals ───────────────────────────────────────────────────────────


@mcp.tool()
async def pending_approvals() -> list[dict]:
    """List jobs paused at hitl awaiting human approval. Oldest first.

    Returned rows include: thread_id, job_url, company, title, score,
    score_reasoning, matched_skills, missing_skills, created_at (ISO8601 UTC),
    status, resolved_at, feedback. All values are JSON-safe primitives.
    """
    rows = await _state_store.list_pending()
    # rows are already plain dicts of JSON-safe primitives + list[str]
    return rows


@mcp.tool()
def archive_marked_jobs() -> dict:
    """Move every JobNote with `manual_action: archive` to `jobs-archive/`.

    Workflow: open a JobNote in Obsidian, add `manual_action: archive` to its
    frontmatter (property pane is fastest), save. Run this. Files move out
    of `jobs/` so dashboard Dataview queries stop showing them. Audit-safe:
    files are moved, not deleted, and stamped with `archived_at`.

    Returns:
        {archived: [filenames], errors: [...]}
    """
    from compass.applications.bulk_archive import archive_marked_jobs as _archive

    return _archive()


@mcp.tool()
async def sync_pending_decisions() -> dict:
    """Apply user-edited approve/reject decisions from `hitl-pending/*.md`.

    Workflow: open a pending note in Obsidian, change frontmatter `status:`
    from `pending` to `approved` or `rejected` (optionally add `feedback:`),
    save, then call this. Every edited note is resumed in one batch.

    Returns:
        {processed: [...], skipped: [...], errors: [...]} — counts + per-row detail.
        `processed` rows include {thread_id, company, title, action, vault_written}.
    """
    from compass.hitl.sync_decisions import sync_decisions

    return await sync_decisions()


@mcp.tool()
async def regenerate_pending_notes() -> dict:
    """Rewrite every `hitl-pending/*.md` note from the current state_store DB.

    Use after editing the DB by hand, on first-time setup, or to recover after
    accidentally deleting a note in Obsidian. Idempotent — overwrites in
    place. Returns {"written": int}.
    """
    from compass.hitl import vault_view

    n = await vault_view.regenerate_all_pending_notes()
    return {"written": n}


@mcp.tool()
async def approve(thread_id: str, approved: bool, feedback: str | None = None) -> dict:
    """Resume a paused thread. approved=True runs tailor + vault_write;
    approved=False skips tailor and writes the rejected JobNote.

    Returns {"vault_written": bool, "human_approved": bool, "human_feedback": str | None}
    on success, or {"error": "..."} if the thread is unknown or already resolved.
    """
    try:
        final = await _resume_pending(
            thread_id,
            decision={"approved": approved, "feedback": feedback},
        )
    except (LookupError, ValueError) as e:
        return {"error": str(e)}
    # Strip non-JSON-safe state from the return (current_job is a Pydantic model,
    # extracted_requirements / score_result are Pydantic). Phase 1.A bug #11
    # pattern: FastMCP cannot serialize Pydantic instances or datetime objects.
    return {
        "vault_written": bool(final.get("vault_written")),
        "human_approved": bool(final.get("human_approved")),
        "human_feedback": final.get("human_feedback"),
    }


if __name__ == "__main__":
    mcp.run()
