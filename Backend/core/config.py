"""Environment parsing and validation for the Sidecar.

Contract: `Docs/API_CONTRACT.md` §2.3 and `Docs/ARCHITECTURE.md` §8.3.
Invalid configuration raises `ConfigError`; `main.py` turns it into
`startup_failed` on stderr plus exit code 2 (no handshake).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

TOKEN_ENV = "PIH_SIDECAR_TOKEN"
PORT_ENV = "PIH_PORT"
DATA_DIR_ENV = "PIH_DATA_DIR"

DEFAULT_PORT = 0
TOKEN_LENGTH = 43

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_PORT_RE = re.compile(r"^[0-9]{1,5}$")

# `Backend/core/config.py` -> `Backend/core` -> `Backend` -> repository root.
SOURCE_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(Exception):
    """Invalid environment configuration carrying a stable log code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class SidecarConfig:
    token: str
    port: int
    data_dir: Path | None


def _validate_token(raw: str | None) -> str:
    if not raw or not _TOKEN_RE.fullmatch(raw):
        raise ConfigError(
            "invalid_token",
            "PIH_SIDECAR_TOKEN must be a 43-character base64url string",
        )
    return raw


def _validate_port(raw: str | None) -> int:
    if raw is None:
        return DEFAULT_PORT
    if not _PORT_RE.fullmatch(raw):
        raise ConfigError("invalid_port", "PIH_PORT must be an integer in 0-65535")
    port = int(raw)
    if port > 65535:
        raise ConfigError("invalid_port", "PIH_PORT must be an integer in 0-65535")
    return port


def _validate_data_dir(raw: str | None) -> Path | None:
    """Return a resolved absolute data dir, or None when the default applies."""

    if raw is None:
        return None
    if not raw:
        raise ConfigError("invalid_data_dir", "PIH_DATA_DIR must be an absolute path")

    candidate = Path(raw)
    if not candidate.is_absolute():
        raise ConfigError("invalid_data_dir", "PIH_DATA_DIR must be an absolute path")

    resolved = Path(os.path.realpath(candidate))
    if any(part.endswith(".app") for part in resolved.parts):
        raise ConfigError(
            "invalid_data_dir",
            "PIH_DATA_DIR must not point inside an app bundle",
        )
    if resolved == SOURCE_ROOT or SOURCE_ROOT in resolved.parents:
        raise ConfigError(
            "invalid_data_dir",
            "PIH_DATA_DIR must not point inside the source tree",
        )
    return resolved


def load_config(environ: Mapping[str, str] | None = None) -> SidecarConfig:
    """Parse and validate the Sidecar environment."""

    source: Mapping[str, str] = os.environ if environ is None else environ
    return SidecarConfig(
        token=_validate_token(source.get(TOKEN_ENV)),
        port=_validate_port(source.get(PORT_ENV)),
        data_dir=_validate_data_dir(source.get(DATA_DIR_ENV)),
    )
