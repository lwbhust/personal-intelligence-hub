"""Single source of truth for the Sidecar service identity.

`Docs/API_CONTRACT.md` §1/§4/§6 require the handshake and `/health` to report
the exact same `service` and `version`; both import these constants.

Phase 7.2 aligned the backend version with the macOS app. Phase 7.2.1 injects
build provenance at build time: `PIH_BUILD_COMMIT` / `PIH_BUILD_TIME` env vars
win, otherwise a generated `build_meta.json` next to the backend sources is
read, and only then does the API report `unknown` instead of inventing a value.
A local build with uncommitted changes is reported as `<commit>+dirty`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SERVICE_NAME = "pih-backend"
VERSION = "0.14.0"

# `Backend/core/version.py` -> `Backend/` (the bundle keeps the same layout).
BUILD_META_PATH = Path(__file__).resolve().parents[1] / "build_meta.json"


def _load_build_meta() -> dict[str, object]:
    try:
        payload = json.loads(BUILD_META_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _clean(value: object, limit: int = 64) -> str:
    if not isinstance(value, str) or not value.strip():
        return "unknown"
    return value.strip()[:limit]


_meta = _load_build_meta()

_commit = os.environ.get("PIH_BUILD_COMMIT") or _meta.get("git_commit")
BUILD_COMMIT = _clean(_commit)
if BUILD_COMMIT != "unknown" and bool(_meta.get("dirty")) and not os.environ.get(
    "PIH_BUILD_COMMIT"
):
    BUILD_COMMIT = f"{BUILD_COMMIT}+dirty"[:64]

BUILD_TIME = _clean(os.environ.get("PIH_BUILD_TIME") or _meta.get("build_time"))
BUILD_BRANCH = _clean(_meta.get("git_branch"))
