"""Data directory and database file resolution.

Contract source: `Docs/API_CONTRACT.md` §2.3/§6.5 and
`Docs/DATABASE_BASELINE.md` §2.1.

Rules:
- `PIH_DATA_DIR` wins when present, but must be an absolute path.
- `~` is not expanded and relative paths are rejected.
- Symlinks are resolved before use.
"""

from __future__ import annotations

import os
from pathlib import Path

from .errors import DATABASE_UNAVAILABLE, DatabaseError

ENV_DATA_DIR = "PIH_DATA_DIR"
APP_DIR_NAME = "PersonalIntelligenceHub"
DB_FILENAME = "pih.sqlite3"

PATH_KIND_APPLICATION_SUPPORT = "application_support"
PATH_KIND_CUSTOM = "custom"

# Set by pytest for the duration of every test. It is deliberately the only
# signal used here: the production Sidecar never sets it.
ENV_PYTEST_CURRENT_TEST = "PYTEST_CURRENT_TEST"


def _default_data_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / APP_DIR_NAME


def _guard_against_test_production_access(resolved: Path) -> None:
    """Refuse to let the test suite resolve the production data directory.

    Phase 7.2.1: a Debug XCTest run once launched the development Sidecar with
    the default environment, which migrated the real user database. Any test
    that forgets to set `PIH_DATA_DIR` now fails loudly instead of writing to
    the user's production data.
    """

    if ENV_PYTEST_CURRENT_TEST not in os.environ:
        return
    production = Path(os.path.realpath(_default_data_dir()))
    if Path(os.path.realpath(resolved)) == production:
        raise DatabaseError(
            DATABASE_UNAVAILABLE,
            "tests must not use the production data directory; "
            "set PIH_DATA_DIR to a temporary path",
        )


def resolve_data_dir() -> Path:
    """Return the resolved data directory.

    Raises `DatabaseError("database_unavailable")` when `PIH_DATA_DIR` is set
    but not an absolute path; the API config layer is expected to turn a bad
    environment value into exit code 2 before this happens.
    """

    raw = os.environ.get(ENV_DATA_DIR)
    if raw is None:
        resolved = _default_data_dir()
    else:
        candidate = Path(raw)
        if not candidate.is_absolute():
            raise DatabaseError(
                DATABASE_UNAVAILABLE,
                "PIH_DATA_DIR must be an absolute path",
            )
        # Baseline §2.1: symlinks must be resolved to their real path.
        resolved = Path(os.path.realpath(candidate))
    _guard_against_test_production_access(resolved)
    return resolved


def database_path() -> Path:
    """Return the authoritative SQLite file path."""

    return resolve_data_dir() / DB_FILENAME


def path_kind() -> str:
    """Return `custom` when `PIH_DATA_DIR` is present, else default kind."""

    return PATH_KIND_CUSTOM if ENV_DATA_DIR in os.environ else PATH_KIND_APPLICATION_SUPPORT
