#!/usr/bin/env python3
"""Phase 7.6 guarded Apply of high-confidence aggregation candidates.

Runs a fresh Dry Run, then applies only `merge` candidates with a minimum pair
score. Creates one verified backup before the first batch. Never deletes
articles, never touches manual events, never applies `review` candidates.

Usage (after the app/Sidecar has been stopped):
    Backend/.venv/bin/python Scripts/phase7_6_apply.py \
        --data-dir "$HOME/Library/Application Support/PersonalIntelligenceHub" \
        --min-score 0.90 --confirm
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
    parser.add_argument("--article-limit", type=int, default=800)
    parser.add_argument("--min-score", type=float, default=0.90)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args(argv[1:])

    data_dir = Path(args.data_dir).expanduser().resolve()
    os.environ["PIH_DATA_DIR"] = str(data_dir)
    os.environ.setdefault("PIH_SCHEDULER_ENABLED", "0")
    os.environ.setdefault("PIH_AI_ENABLED", "0")

    import database  # noqa: E402
    from services.event_aggregation_service import (  # noqa: E402
        MAX_APPLY_PAIRS,
        get_event_aggregation_service,
    )

    status = database.initialize()
    if status.status != "ok":
        print(json.dumps({"ok": False, "status": status.status}, ensure_ascii=False))
        return 2

    service = get_event_aggregation_service()
    dry = service.dry_run(days=args.days, article_limit=args.article_limit)
    pairs: list[dict[str, object]] = []
    for candidate in dry["event_candidates"]:
        if candidate["decision"] == "merge":
            pairs.append(
                {
                    "kind": "event_merge",
                    "source_event_id": candidate["source_event"]["id"],
                    "target_event_id": candidate["target_event"]["id"],
                }
            )
    for candidate in dry["article_candidates"]:
        if candidate["decision"] == "merge":
            pairs.append(
                {
                    "kind": "article_attach",
                    "article_id": candidate["article"]["id"],
                    "event_id": candidate["target_event"]["id"],
                }
            )
    for group in dry["article_groups"]:
        scores = [float(item["score"]) for item in group["pairs"]]
        if scores and min(scores) >= args.min_score:
            pairs.append(
                {"kind": "article_group", "article_ids": group["article_ids"]}
            )

    plan = {
        "ok": True,
        "data_dir": str(data_dir),
        "schema_version": status.schema_version,
        "dry_run_summary": dry["summary"],
        "selected_pairs": len(pairs),
        "min_score": args.min_score,
        "confirmed": args.confirm,
    }
    if not args.confirm:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    batches = [
        pairs[index : index + MAX_APPLY_PAIRS]
        for index in range(0, len(pairs), MAX_APPLY_PAIRS)
    ]
    results = []
    for index, batch in enumerate(batches):
        result = service.apply(
            batch, confirm=True, create_backup=index == 0
        )
        results.append(
            {
                "batch": index + 1,
                "applied": result["applied_count"],
                "rejected": result["rejected_count"],
                "backup": result["backup"],
                "rejections": result["rejected"][:10],
            }
        )
        print(
            json.dumps(
                {
                    "batch": index + 1,
                    "applied": result["applied_count"],
                    "rejected": result["rejected_count"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    payload = {**plan, "batches": results}
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "selected": len(pairs), "batches": len(batches)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
