"""Phase 7.1 intelligence tests: real SQLite in a temp data dir."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database  # noqa: E402


@pytest.fixture()
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "data"
    monkeypatch.setenv("PIH_DATA_DIR", str(target))
    status = database.initialize()
    assert status.status == "ok", status
    return target
