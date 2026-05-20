"""Eval dataset — labeled JDs the harness compares Compass output against.

Storage: `compass/evals/labeled_dataset.json` (NOT in the vault — the dataset
is repo-tracked code artifact, not a vault note).

Schema per record:
  id               unique stable string (eval-001, eval-002, …)
  jd_text          raw JD body (post-HTML-strip)
  source           where the JD came from — usually a JobNote filename
  expected_score   float 0-5, what a human reviewer says the fit is
  expected_skills  list[str], all skills a human reviewer says the JD asks for
                   (the union — both "required" and "nice-to-have")
  notes            free-text human-justification for the labels

Hand-labeled at first; later we can also add an LLM-judge column for cheap
sanity checking on un-labeled JDs (see compass/evals/judge.py).

Start with 20 examples covering the full tier spread — bank rotational entry,
mid-SaaS, frontier startup, Tier 1.5 data-infra, applied-AI at Anthropic.
Enough variance to surface tier-specific extract/score biases.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

DATASET_PATH = Path(__file__).parent / "labeled_dataset.json"


class EvalRecord(BaseModel):
    """One labeled JD in the eval dataset."""

    id: str
    jd_text: str
    source: str = ""  # e.g. JobNote filename — provenance for hand-labels
    expected_score: float = Field(ge=0.0, le=5.0)
    expected_skills: list[str] = Field(default_factory=list)
    notes: str = ""


def load_dataset(path: Path | None = None) -> list[EvalRecord]:
    """Load the labeled evaluation dataset. Returns [] when the file is missing
    (first-time setup) so the runner can still execute against the LLM-judge
    path without requiring hand labels."""
    p = path or DATASET_PATH
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    return [EvalRecord.model_validate(r) for r in raw]


def save_dataset(records: list[EvalRecord], path: Path | None = None) -> Path:
    """Save the dataset to JSON. Pretty-printed so git diffs are readable
    when a human adds a new example.

    ATOMIC: writes to a `.tmp` sibling first then `os.replace`. A SIGKILL or
    disk-full mid-write previously truncated the JSON, making the entire
    labeled dataset un-parseable on next load. With the atomic swap, the
    previous good file stays in place on any failure.
    """
    import os as _os

    p = path or DATASET_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = p.with_suffix(p.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(
            [r.model_dump() for r in records],
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    _os.replace(tmp_path, p)
    return p


def add_example(
    jd_text: str,
    expected_score: float,
    expected_skills: list[str],
    *,
    source: str = "",
    notes: str = "",
    path: Path | None = None,
) -> EvalRecord:
    """Append one labeled example. Auto-generates a stable ID based on the
    current dataset size — `eval-001`, `eval-002`, …. Caller is responsible
    for not duplicating jd_text (no dedup enforced; intentional flexibility)."""
    records = load_dataset(path)
    new_id = f"eval-{len(records) + 1:03d}"
    record = EvalRecord(
        id=new_id,
        jd_text=jd_text,
        source=source,
        expected_score=expected_score,
        expected_skills=list(expected_skills),
        notes=notes,
    )
    records.append(record)
    save_dataset(records, path)
    return record


def add_from_jobnote(
    jobnote_path: Path, expected_score: float, expected_skills: list[str], notes: str = ""
) -> EvalRecord:
    """Convenience: read JD body + summary from a JobNote in the vault,
    add as a labeled record. Used during the "label 10 JobNotes from the
    first refresh" Day-7 sprint task.
    """
    import frontmatter

    post = frontmatter.load(jobnote_path)
    company = post.metadata.get("company", "")
    title = post.metadata.get("title", "")
    # The JD body is everything in `## Full JD` section, falling back to the
    # whole post content if the section isn't present (older JobNotes).
    text = post.content
    if "## Full JD" in text:
        text = text.split("## Full JD", 1)[1].strip()
    source = f"{jobnote_path.name} ({company} — {title})"
    return add_example(
        jd_text=text,
        expected_score=expected_score,
        expected_skills=expected_skills,
        source=source,
        notes=notes,
    )
