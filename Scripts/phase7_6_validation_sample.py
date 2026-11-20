#!/usr/bin/env python3
"""Phase 7.6 clustering validation sample (read-only, real database copy).

Builds a stratified pair sample for manual review:
- `merge`     : every pair the algorithm would merge (cap 60)
- `boundary`  : review / near-threshold separate pairs (cap 30)
- `control`   : random cross-source pairs in the same window (cap 30)

The printed JSON is meant to be labelled by a human (same event / different
event); `Scripts/phase7_6_metrics.py` turns labels into precision/recall/F1.

Usage:
    Backend/.venv/bin/python Scripts/phase7_6_validation_sample.py \
        --data-dir .tmp_audit_data --days 7 --out .tmp_audit_data/validation_sample.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "Backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv[1:])

    data_dir = Path(args.data_dir).expanduser().resolve()
    os.environ["PIH_DATA_DIR"] = str(data_dir)
    os.environ.setdefault("PIH_SCHEDULER_ENABLED", "0")
    os.environ.setdefault("PIH_AI_ENABLED", "0")

    import database  # noqa: E402
    from services.event_aggregation_service import (  # noqa: E402
        _article_as_event,
        _load_article_signals,
        _prefilter_article_pair,
    )
    from event_intelligence.aggregation import score_article_event  # noqa: E402
    from services.event_aggregation_service import _cutoff  # noqa: E402

    status = database.initialize()
    if status.status != "ok":
        print(json.dumps({"ok": False, "status": status.status}, ensure_ascii=False))
        return 2

    cutoff = _cutoff(args.days)
    with database.read_session() as conn:
        articles = _load_article_signals(conn, cutoff=cutoff, limit=800)

    merge: list[dict[str, object]] = []
    boundary: list[dict[str, object]] = []
    control: list[dict[str, object]] = []
    for index, left in enumerate(articles):
        for right in articles[index + 1 :]:
            if not _prefilter_article_pair(left, right):
                continue
            forward = score_article_event(left, _article_as_event(right))
            backward = score_article_event(right, _article_as_event(left))
            score = forward if forward.total >= backward.total else backward
            item = {
                "id": f"{left.id}:{right.id}",
                "left": {
                    "article_id": left.id,
                    "title": left.title,
                    "source": left.source_name,
                    "published_at": left.published_at,
                },
                "right": {
                    "article_id": right.id,
                    "title": right.title,
                    "source": right.source_name,
                    "published_at": right.published_at,
                },
                "decision": score.decision,
                "score": score.total,
                "reasons": list(score.reasons),
                "guards": list(score.guards),
            }
            if score.decision == "merge":
                merge.append(item)
            elif score.total >= 0.50:
                boundary.append(item)
            elif right.id != left.id:
                control.append(item)

    random.Random(args.seed).shuffle(control)
    sample = {
        "generated_on": "real-database-copy",
        "window_days": args.days,
        "articles": len(articles),
        "merge": merge[:60],
        "boundary": boundary[:30],
        "control": control[:30],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "out": str(out),
                "merge": len(sample["merge"]),
                "boundary": len(sample["boundary"]),
                "control": len(sample["control"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
