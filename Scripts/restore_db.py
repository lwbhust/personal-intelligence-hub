#!/usr/bin/env python3
"""List or restore SQLite backups (Phase 1).

Usage:
    Backend/.venv/bin/python Scripts/restore_db.py --list
    Backend/.venv/bin/python Scripts/restore_db.py <backup-filename>

Restore requires the App/Sidecar to be stopped. A safety backup is created
first; a failed restore rolls back to it.
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
    if len(argv) == 2 and argv[1] == "--list":
        print(json.dumps({"ok": True, "items": backup.list_backups()}, ensure_ascii=False, indent=2))
        return 0
    if len(argv) != 2:
        print("usage: restore_db.py --list | <backup-filename>", file=sys.stderr)
        return 64

    try:
        payload = backup.restore_backup(argv[1])
    except backup.BackupError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "message": exc.message}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
