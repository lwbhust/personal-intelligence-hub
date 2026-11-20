"""Phase 4 event-intelligence tests: real SQLite, no mocks."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
BACKEND_TESTS = Path(__file__).resolve().parent.parent / "backend"
for path in (str(BACKEND_ROOT), str(BACKEND_TESTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import database  # noqa: E402  (after sys.path fix)


@pytest.fixture()
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "data"
    monkeypatch.setenv("PIH_DATA_DIR", str(target))
    status = database.initialize()
    assert status.status == "ok", status
    return target
