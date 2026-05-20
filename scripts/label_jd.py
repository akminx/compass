"""Interactive CLI for labeling JDs into the eval dataset.

Two modes:
  uv run python -m scripts.label_jd <JobNote filename>
      → reads compass-vault/jobs/<JobNote>, shows the body + summary, runs
        Compass's current extract on it, displays the agent's output, prompts
        for your expected_score + expected_skills + notes. Appends to dataset.

  uv run python -m scripts.label_jd
      → interactive mode without a JobNote: paste a JD, supply score/skills,
        save. Useful for labeling JDs you found manually outside the vault.

Mirrors the spec's `scripts/label_jd.py` requirement (Phase 2.A). Designed
to make hand-labeling 20 JDs over an hour feel fast — defaults, completion-
hints, and one-keystroke "use the agent's extract as ground truth" path.
"""

from __future__ import annotations

import argparse
import sys

import frontmatter

# IMPORTANT: read VAULT_PATH at call time via `cfg.VAULT_PATH`, not via
# `from compass.config import VAULT_PATH`. The latter freezes the import-time
# value and silently breaks the `temp_vault` test fixture (which monkeypatches
# cfg.VAULT_PATH). See CLAUDE.md lesson #2.
import compass.config as cfg
from compass.evals.dataset import add_example, load_dataset


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    raw = input(f"{label}{suffix}: ").strip()
    return raw or default


def _prompt_float(label: str, *, lo: float, hi: float, default: float | None = None) -> float:
    while True:
        raw = _prompt(label, default=("" if default is None else str(default)))
        try:
            val = float(raw)
        except ValueError:
            print(f"  ! not a number — enter a value in [{lo}, {hi}]")
            continue
        if val < lo or val > hi:
            print(f"  ! out of range — enter a value in [{lo}, {hi}]")
            continue
        return val


def _prompt_skills(label: str, default: list[str] | None = None) -> list[str]:
    default_str = ", ".join(default or [])
    raw = _prompt(label, default=default_str)
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def _load_jobnote(filename: str) -> tuple[str, str, str, str]:
    """Return (jd_text, company, title, source_label) from a JobNote on disk."""
    jobs_dir = (cfg.VAULT_PATH / "jobs").resolve()
    path = (cfg.VAULT_PATH / "jobs" / filename).resolve()
    try:
        path.relative_to(jobs_dir)
    except ValueError as e:
        raise SystemExit(f"job_filename must be inside {jobs_dir}: {filename!r}") from e
    if not path.exists():
        raise SystemExit(f"JobNote not found: {filename}")
    post = frontmatter.load(path)
    company = str(post.metadata.get("company") or "(unknown)")
    title = str(post.metadata.get("title") or "(unknown)")
    text = post.content
    if "## Full JD" in text:
        text = text.split("## Full JD", 1)[1].strip()
    return text, company, title, f"{path.name} ({company} — {title})"


async def _show_agent_extract(jd_text: str) -> tuple[float | None, list[str]]:
    """Run Compass's extract on the JD and print the agent's reading so the
    human can quickly validate or override. Returns (None, agent_skills) —
    score isn't shown because there's no profile-anchored fit until the
    score node runs, and we don't want to anchor the labeler on a number."""
    from compass.pipeline.nodes.extract import (
        _extract,
        _normalize_skill_list,
        _seniority_with_title_fallback,
    )

    print("\n→ running Compass extract (this is one LLM call, ~$0.001)…")
    try:
        raw = await _extract(jd_text)
    except Exception as e:
        print(f"  extract failed: {e}")
        return None, []
    # Normalize the same way the production pipeline does so the labeler
    # sees the canonical skill names.
    unknown: list[str] = []
    required = _normalize_skill_list(raw.required_skills, jd_text, unknown)
    nice = _normalize_skill_list(raw.nice_to_have_skills, jd_text, unknown)
    print(f"  required:    {', '.join(required) or '(none)'}")
    print(f"  nice-to-have: {', '.join(nice) or '(none)'}")
    print(f"  seniority:   {_seniority_with_title_fallback(raw.seniority, '')}")
    if unknown:
        print(f"  ! unknown to taxonomy (dropped): {', '.join(unknown)}")
    return None, list(dict.fromkeys(required + nice))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "jobnote",
        nargs="?",
        help="JobNote filename (e.g. 2026-05-19-sierra-Engineer-abc.md). "
        "Omit for interactive paste mode.",
    )
    parser.add_argument(
        "--score",
        type=float,
        help="Skip the score prompt and use this value (0-5).",
    )
    parser.add_argument(
        "--skills",
        help="Comma-separated expected skills (skips the skills prompt).",
    )
    parser.add_argument(
        "--no-agent-extract",
        action="store_true",
        help="Don't run Compass's extract — useful when you want a totally "
        "blind label (no anchoring on the agent's output).",
    )
    args = parser.parse_args()

    if args.jobnote:
        jd_text, company, title, source = _load_jobnote(args.jobnote)
        print(f"\nLoaded JobNote: {company} — {title}")
        print(f"JD length: {len(jd_text)} chars\n")
        print("--- JD body (first 800 chars) ---")
        print(jd_text[:800] + ("…" if len(jd_text) > 800 else ""))
        print("---\n")
    else:
        print("Paste the JD body, then end with Ctrl-D on a blank line:")
        jd_text = sys.stdin.read().strip()
        if not jd_text:
            print("Empty input — exiting.")
            return 1
        company = _prompt("company")
        title = _prompt("title")
        source = f"manual: {company} — {title}"

    agent_skills: list[str] = []
    if not args.no_agent_extract:
        import asyncio

        _, agent_skills = asyncio.run(_show_agent_extract(jd_text))

    print()
    score = (
        args.score
        if args.score is not None
        else _prompt_float(
            "expected_score (0-5)",
            lo=0.0,
            hi=5.0,
        )
    )
    if args.skills is not None:
        expected_skills = [s.strip() for s in args.skills.split(",") if s.strip()]
    else:
        expected_skills = _prompt_skills(
            "expected_skills (comma-sep, [Enter] accepts agent's list)",
            default=agent_skills,
        )
    notes = _prompt("notes (optional)")

    print("\nLabeled record preview:")
    print(f"  source:          {source}")
    print(f"  expected_score:  {score}")
    print(f"  expected_skills: {expected_skills}")
    print(f"  notes:           {notes!r}")
    confirm = _prompt("save? [Y/n]", default="Y").lower()
    if confirm not in ("y", "yes", ""):
        print("Aborted.")
        return 1

    record = add_example(
        jd_text=jd_text,
        expected_score=score,
        expected_skills=expected_skills,
        source=source,
        notes=notes,
    )
    n_total = len(load_dataset())
    print(f"\n✓ Saved {record.id}. Dataset now has {n_total} labeled JD(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
