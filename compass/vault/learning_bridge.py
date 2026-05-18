"""
Learning-vault bridge.

Resolves `learning-vault://` URIs into file content + metadata so the
skill_assessor can read evidence and the MCP server can expose it as a tool.

URI format:
    learning-vault://<relative/path/to/file.md>[#<heading-anchor>]
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path  # noqa: TC003 — dataclass field needs runtime type for introspection

from compass.config import LEARNING_VAULT_PATH

URI_PREFIX = "learning-vault://"


@dataclass
class EvidenceArtifact:
    uri: str
    path: Path
    anchor: str | None
    snippet: str
    last_modified: datetime
    kind: str  # decision-note | debug-log | course-note | postmortem | leetcode | star | system-design | unknown


def _parse_uri(uri: str) -> tuple[Path, str | None]:
    if not uri.startswith(URI_PREFIX):
        raise ValueError(f"not a learning-vault URI: {uri}")
    rest = uri[len(URI_PREFIX) :]
    anchor: str | None = None
    if "#" in rest:
        rest, anchor = rest.split("#", 1)
    return LEARNING_VAULT_PATH / rest, anchor


def _kind_for(path: Path) -> str:
    p = str(path).lower()
    if "/projects/" in p and "decisions" in p:
        return "decision-note"
    if "/projects/" in p and ("debug-log" in p or "failure-modes" in p):
        return "debug-log"
    if "/projects/" in p and "postmortem" in p:
        return "postmortem"
    if "/courses/" in p:
        return "course-note"
    if "/leetcode/" in p:
        return "leetcode"
    if "/star-stories/" in p:
        return "star"
    if "/system-design/" in p:
        return "system-design"
    return "unknown"


def _extract_section(text: str, anchor: str) -> str:
    """Pull lines under a heading matching the anchor; stop at the next heading of equal or higher level."""
    target = anchor.lower().replace("-", " ")
    lines = text.splitlines()
    out: list[str] = []
    capture = False
    capture_level = 0
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if m:
            level = len(m.group(1))
            heading_norm = re.sub(r"[^a-z0-9]+", " ", m.group(2).lower()).strip()
            if not capture and target in heading_norm:
                capture = True
                capture_level = level
                continue
            if capture and level <= capture_level:
                break
        if capture:
            out.append(line)
    return "\n".join(out).strip()


def resolve(uri: str, snippet_chars: int = 1200) -> EvidenceArtifact | None:
    """Read a learning-vault URI. Returns None if the file is missing."""
    try:
        path, anchor = _parse_uri(uri)
    except ValueError:
        return None
    if not path.exists() or not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if anchor:
        section = _extract_section(text, anchor)
        snippet = section[:snippet_chars] if section else text[:snippet_chars]
    else:
        snippet = text[:snippet_chars]
    return EvidenceArtifact(
        uri=uri,
        path=path,
        anchor=anchor,
        snippet=snippet,
        last_modified=datetime.fromtimestamp(path.stat().st_mtime),
        kind=_kind_for(path),
    )


def resolve_many(uris: list[str]) -> list[EvidenceArtifact]:
    out: list[EvidenceArtifact] = []
    for uri in uris:
        if uri.startswith(URI_PREFIX):
            artifact = resolve(uri)
            if artifact:
                out.append(artifact)
    return out


def scan_evidence(skill_canonical: str, search_terms: list[str] | None = None) -> list[Path]:
    """Optional helper: surface candidate evidence files for a skill by keyword search.

    Used by the MCP `suggest_evidence` tool — surfaces files the user might want to
    cite as evidence but hasn't linked yet.
    """
    terms = [t.lower() for t in (search_terms or [skill_canonical])]
    hits: list[Path] = []
    for path in LEARNING_VAULT_PATH.rglob("*.md"):
        if any(part.startswith(".") for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        if any(t in text for t in terms):
            hits.append(path)
    return hits


def path_to_uri(path: Path, anchor: str | None = None) -> str:
    rel = path.resolve().relative_to(LEARNING_VAULT_PATH.resolve())
    uri = f"{URI_PREFIX}{rel.as_posix()}"
    if anchor:
        uri = f"{uri}#{anchor}"
    return uri
