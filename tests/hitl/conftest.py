"""Shared fixtures for HiTL tests.

`temp_hitl_db` lives in the top-level tests/conftest.py so pipeline tests can
reuse it without duplication.
"""

from __future__ import annotations

import datetime as _dt

import pytest


@pytest.fixture
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> _dt.datetime:
    """Freeze the wall clock the state store uses."""
    fixed = _dt.datetime(2026, 5, 19, 12, 0, 0, tzinfo=_dt.UTC)

    import compass.hitl.state_store as ss

    monkeypatch.setattr(ss, "_now", lambda: fixed)
    return fixed
