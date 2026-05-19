"""Shared fixtures for HiTL tests."""

from __future__ import annotations

import datetime as _dt
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def temp_hitl_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HITL_STATE_DB at a fresh per-test SQLite file.

    The store reads `compass.config.HITL_STATE_DB` inside function bodies (per
    the module-level discipline rule), so monkeypatching the attribute is
    sufficient — no module reimport needed.
    """
    db = tmp_path / "pending.db"
    import compass.config as cfg

    monkeypatch.setattr(cfg, "HITL_STATE_DB", db)
    return db


@pytest.fixture
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> _dt.datetime:
    """Freeze the wall clock the state store uses."""
    fixed = _dt.datetime(2026, 5, 19, 12, 0, 0, tzinfo=_dt.UTC)

    import compass.hitl.state_store as ss

    monkeypatch.setattr(ss, "_now", lambda: fixed)
    return fixed
