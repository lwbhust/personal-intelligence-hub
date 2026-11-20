"""Fixture wiring for backend integration tests (real processes only)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TEST_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TEST_DIR.parents[1]
for path in (str(BACKEND_DIR), str(TEST_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from support import Sidecar, start_sidecar  # noqa: E402


@pytest.fixture()
def sidecar(tmp_path: Path) -> Sidecar:
    instance = start_sidecar(tmp_path, env_overrides={"PIH_AI_ENABLED": "0"})
    yield instance
    if instance.proc.poll() is None:
        instance.proc.kill()
        instance.proc.wait(timeout=5)
