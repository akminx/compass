"""Cover-letter generator — on-demand, per-application.

Not part of the per-job graph (too expensive to run on every scrape). Invoked
via the MCP tool `generate_cover_letter(job_id)` when the user is about to
apply to a specific role.

Saves output to `compass-vault/cover-letters/{date}-{company}-{title}-{hash}.md`
so the user has a discoverable record per JD without cluttering JobNote
frontmatter.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date
from typing import TYPE_CHECKING

import frontmatter
from pydantic import BaseModel

if TYPE_CHECKING:
    from pathlib import Path

from compass.config import VAULT_PATH
from compass.llm import make_agent
from compass.vault.reader import read_profile_section, read_resume

logger = logging.getLogger(__name__)


class CoverLetterDraft(BaseModel):
    """Structured cover-letter output."""

    opening: str
    body: str  # 2-3 paragraphs body, separated by blank lines
    closing: str


_SYSTEM_PROMPT = """You write cover letters for a 1.5-YoE software engineer
applying to AI / agent / applied-AI roles.

Output a SHORT, SPECIFIC cover letter. Three sections:
- opening: 2-3 sentences. State the role you're applying for and ONE concrete
  reason this candidate is a good fit (not generic enthusiasm). Reference a
  named project or skill from the candidate profile that maps directly to the
  JD's top requirement.
- body: 2-3 paragraphs (3-5 sentences each). Each paragraph anchors on a
  specific project or experience from the candidate profile that maps to the
  JD's required skills. Include concrete numbers when the profile provides
  them. Do NOT invent projects or claims.
- closing: 2-3 sentences. State why this company specifically (use the
  company notes from the targeting context if provided). End with a
  forward-looking next step.

STRICT RULES:
- Never invent projects, employers, numbers, or claims. Only use facts from
  the CANDIDATE PROFILE and ROLE CLARIFICATIONS sections.
- Never use clichés like "I am writing to apply for...", "I am excited to
  apply...", "passionate about", "team player", "results-oriented".
- Plain prose. No emoji, no bullet points, no markdown.
- Total length 250-400 words across all three sections.
- Match the candidate's voice from the resume — direct, technical, specific.
"""


def _build_agent():
    return make_agent("tailor", output_type=CoverLetterDraft, system_prompt=_SYSTEM_PROMPT)


async def _draft(
    company: str,
    title: str,
    jd_summary: str,
    required: list[str],
    nice_to_have: list[str],
    matched: list[str],
    missing: list[str],
    profile_text: str,
    company_notes: str | None,
) -> CoverLetterDraft:
    agent = _build_agent()
    prompt = (
        f"CANDIDATE PROFILE\n{profile_text}\n\n"
        f"# COMPANY\n{company}\n"
        f"# ROLE\n{title}\n"
        f"# JD SUMMARY\n{jd_summary}\n\n"
        f"required: {', '.join(required) or '(none)'}\n"
        f"nice-to-have: {', '.join(nice_to_have) or '(none)'}\n"
        f"already-matched: {', '.join(matched) or '(none)'}\n"
        f"to-shore-up: {', '.join(missing) or '(none)'}\n"
    )
    if company_notes:
        prompt += f"\n# WHY THIS COMPANY (from candidate notes)\n{company_notes}\n"
    result = await agent.run(prompt)
    return result.output


_FILENAME_BAD = re.compile(r"[^\w\-.]+")


def _safe_segment(s: str) -> str:
    return _FILENAME_BAD.sub("_", s).strip("_")


def _cover_letter_path(company: str, title: str, job_url: str) -> Path:
    """Mirror the JobNote filename pattern so cover-letter files line up
    visually with the JobNotes they target."""
    today = date.today().isoformat()
    url_suffix = hashlib.sha1(job_url.encode("utf-8")).hexdigest()[:8]
    return (
        VAULT_PATH
        / "cover-letters"
        / f"{today}-{_safe_segment(company)}-{_safe_segment(title)}-{url_suffix}.md"
    )


async def generate_cover_letter_from_jobnote(job_path: Path) -> tuple[Path, str]:
    """Read a JobNote from disk, draft a cover letter, write it next to the
    JobNote. Returns (output_path, body_text)."""
    from compass.vault.target_companies import get_company_meta

    post = frontmatter.load(job_path)
    md = post.metadata
    company = str(md.get("company") or "(unknown)")
    title = str(md.get("title") or "(unknown)")
    job_url = str(md.get("url") or job_path.name)
    jd_summary = str(md.get("jd_summary") or post.content[:1000])
    required = list(md.get("skills_required") or [])
    nice_to_have = list(md.get("skills_nice_to_have") or [])
    matched = list(md.get("skills_matched") or [])
    missing = list(md.get("skills_missing") or [])

    profile = f"{read_resume()}\n\n{read_profile_section('role-clarifications')}"
    company_meta = get_company_meta(company)
    company_notes = (company_meta.get("notes") if company_meta else None) or None

    draft = await _draft(
        company,
        title,
        jd_summary,
        required,
        nice_to_have,
        matched,
        missing,
        profile,
        company_notes,
    )

    body = f"{draft.opening}\n\n{draft.body}\n\n{draft.closing}\n"
    out_path = _cover_letter_path(company, title, job_url)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    front = {
        "type": "cover-letter",
        "company": company,
        "title": title,
        "job_ref": job_url,
        "drafted_at": date.today().isoformat(),
    }
    out_path.write_text(
        frontmatter.dumps(frontmatter.Post(body, **front)) + "\n",
        encoding="utf-8",
    )
    return out_path, body
