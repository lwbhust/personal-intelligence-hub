"""Phase 7.2.1 regression: tests must never resolve the production database.

The Debug XCTest run once launched a development Sidecar with the default
environment and migrated the real user database. The data layer now refuses to
resolve the production data directory while pytest is running.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from database import DatabaseError, resolve_data_dir
from database.paths import ENV_DATA_DIR, ENV_PYTEST_CURRENT_TEST


def test_default_data_dir_is_rejected_under_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_DATA_DIR, raising=False)
    monkeypatch.setenv(ENV_PYTEST_CURRENT_TEST, "tests/data/test_test_isolation.py::x")

    with pytest.raises(DatabaseError) as excinfo:
        resolve_data_dir()

    assert excinfo.value.code == "database_unavailable"
    assert "production data directory" in str(excinfo.value)


def test_explicit_production_dir_is_rejected_under_pytest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = Path.home() / "Library" / "Application Support" / "PersonalIntelligenceHub"
    monkeypatch.setenv(ENV_DATA_DIR, str(production))
    monkeypatch.setenv(ENV_PYTEST_CURRENT_TEST, "tests/data/test_test_isolation.py::y")

    with pytest.raises(DatabaseError) as excinfo:
        resolve_data_dir()

    assert excinfo.value.code == "database_unavailable"


def test_temporary_dir_is_allowed_under_pytest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path / "data"))
    monkeypatch.setenv(ENV_PYTEST_CURRENT_TEST, "tests/data/test_test_isolation.py::z")

    assert resolve_data_dir() == tmp_path / "data"
    assert os.environ[ENV_DATA_DIR] == str(tmp_path / "data")
