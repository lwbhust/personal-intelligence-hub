"""Phase 7.2 pipeline tests: real SQLite, no mocks, temporary data dir."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_TESTS = Path(__file__).resolve().parent
for path in (str(BACKEND_ROOT), str(PIPELINE_TESTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import database  # noqa: E402


@pytest.fixture()
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PIH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PIH_SCHEDULER_ENABLED", "0")
    status = database.initialize()
    assert status.status == "ok", status
    yield tmp_path
    # Drop singletons so a later test never reuses a worker from this data dir.
    import services.ai_analysis_service as ai_module
    import services.collection_service as collection_module
    import services.event_clustering_service as clustering_module
    import services.intelligence_service as intelligence_module
    import services.pipeline_orchestrator as pipeline_module

    ai_module._ai_service = None
    collection_module._collection_service = None
    clustering_module._clustering_service = None
    intelligence_module._intelligence_service = None
    pipeline_module._orchestrator = None
