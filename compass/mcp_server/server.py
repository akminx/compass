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
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from compass.analysis import gap_aggregator, skill_assessor
from compass.config import VAULT_PATH
from compass.vault.learning_bridge import path_to_uri, resolve, scan_evidence
from compass.vault.taxonomy import all_canonicals

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
    """Read a file from _profile/. section is the bare filename (e.g. 'resume', 'skill-inventory')."""
    path = VAULT_PATH / "_profile" / f"{section}.md"
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


if __name__ == "__main__":
    mcp.run()
