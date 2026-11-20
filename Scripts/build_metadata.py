#!/usr/bin/env python3
"""Generate `Backend/build_meta.json` for build-time provenance (Phase 7.2.1).

The file is written next to the backend sources and copied into the App bundle
by `Scripts/package_sidecar.sh`, so the packaged Sidecar never needs a git
repository at runtime. Explicit `PIH_BUILD_COMMIT` / `PIH_BUILD_TIME` values win
over git detection.

Usage:
    python3 Scripts/build_metadata.py [output_path]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "Backend" / "build_meta.json"


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def collect() -> dict[str, object]:
    commit = os.environ.get("PIH_BUILD_COMMIT") or _git("rev-parse", "--short=12", "HEAD")
    branch = os.environ.get("PIH_BUILD_BRANCH") or _git("rev-parse", "--abbrev-ref", "HEAD")
    status = _git("status", "--porcelain")
    dirty = bool(status)
    build_time = os.environ.get("PIH_BUILD_TIME") or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return {
        "git_commit": commit or "unknown",
        "git_branch": branch or "unknown",
        "dirty": dirty,
        "build_time": build_time,
        "source": "env" if os.environ.get("PIH_BUILD_COMMIT") else "git",
    }


def main(argv: list[str]) -> int:
    output = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUTPUT
    payload = collect()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "path": str(output), **payload}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
