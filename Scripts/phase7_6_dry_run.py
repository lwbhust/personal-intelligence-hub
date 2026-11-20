#!/usr/bin/env python3
"""Phase 7.6 Dry Run: cross-source event aggregation candidates.

Read-only. Point it at a *copy* of the production database (or any data dir)
and it prints/writes the candidate merges with scores and reasons.

Usage:
    Backend/.venv/bin/python Scripts/phase7_6_dry_run.py \
        --data-dir .tmp_audit --days 30 --out .tmp_audit/aggregation_dry_run.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "Backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--event-limit", type=int, default=200)
    parser.add_argument("--article-limit", type=int, default=500)
    parser.add_argument("--out")
    args = parser.parse_args(argv[1:])

    data_dir = Path(args.data_dir).expanduser().resolve()
    os.environ["PIH_DATA_DIR"] = str(data_dir)
    os.environ.setdefault("PIH_SCHEDULER_ENABLED", "0")
    os.environ.setdefault("PIH_AI_ENABLED", "0")

    import database  # noqa: E402
    from services.event_aggregation_service import (  # noqa: E402
        get_event_aggregation_service,
    )

    status = database.initialize()
    if status.status != "ok":
        print(json.dumps({"ok": False, "status": status.status}, ensure_ascii=False))
        return 2

    result = get_event_aggregation_service().dry_run(
        days=args.days,
        event_limit=args.event_limit,
        article_limit=args.article_limit,
    )
    payload = {
        "ok": True,
        "data_dir": str(data_dir),
        "summary": result["summary"],
        "algorithm_version": result["algorithm_version"],
        "generated_at": result["generated_at"],
        "event_candidates": result["event_candidates"],
        "article_candidates": result["article_candidates"],
        "article_pairs": result["article_pairs"],
        "groups": result["groups"],
        "article_groups": result["article_groups"],
    }
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"ok": True, "out": str(out), **result["summary"]}, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
