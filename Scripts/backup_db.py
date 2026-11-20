#!/usr/bin/env python3
"""Create a verified SQLite backup (Phase 1).

Usage:
    Backend/.venv/bin/python Scripts/backup_db.py [reason]

Prints one JSON object. Does not require the Sidecar to be running.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "Backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from database import backup  # noqa: E402


def main(argv: list[str]) -> int:
    reason = argv[1] if len(argv) > 1 else "manual"
    try:
        payload = backup.create_backup(reason)
    except backup.BackupError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "message": exc.message}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
