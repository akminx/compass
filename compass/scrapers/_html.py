"""Shared HTML→text utility for scrapers + add_url + vault writer.

Each ATS returns JD bodies as HTML; before extraction we strip tags so the
LLM sees readable plain text. The same routine was duplicated across five
modules — consolidated here to keep one bug fix in one place.
"""

from __future__ import annotations

import html
import re

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def strip_html(raw: str) -> str:
    """HTML-to-text. Strips `<script>` / `<style>` blocks BEFORE tag removal
    so their content doesn't leak into the JD description; collapses whitespace
    so the LLM doesn't pay tokens on consecutive blanks.
    """
    text = _SCRIPT_STYLE_RE.sub(" ", raw)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return _WHITESPACE_RE.sub(" ", text).strip()


_HTML_HINT_RE = re.compile(r"<(p|br|li|ul|ol|div|span|h[1-6])\b", re.IGNORECASE)


def looks_like_html(raw: str) -> bool:
    """Heuristic — do we have HTML to strip, or is this already plain text?"""
    return bool(_HTML_HINT_RE.search(raw or ""))
