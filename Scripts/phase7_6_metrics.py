#!/usr/bin/env python3
"""Phase 7.6 clustering metrics from a manually labelled stratified sample.

Usage:
    Backend/.venv/bin/python Scripts/phase7_6_metrics.py \
        --sample .tmp_audit_data/validation_sample.json \
        --labels .tmp_audit_data/validation_labels.json

`labels.json` format:
    {"merge": [true, ...], "boundary": [false, ...], "control": [false, ...]}
Each array is aligned with the same array in the sample file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", required=True)
    parser.add_argument("--labels", required=True)
    args = parser.parse_args(argv[1:])

    sample = json.loads(Path(args.sample).read_text(encoding="utf-8"))
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))

    per_stratum: dict[str, dict[str, int]] = {}
    tp = fp = fn = tn = 0
    for stratum in ("merge", "boundary", "control"):
        items = sample.get(stratum, [])
        marks = labels.get(stratum, [])
        if len(items) != len(marks):
            raise SystemExit(f"{stratum}: {len(items)} pairs vs {len(marks)} labels")
        stats = {"total": len(items), "same": 0, "predicted_merge": 0, "tp": 0, "fp": 0, "fn": 0, "tn": 0}
        for item, same in zip(items, marks):
            predicted = item["decision"] == "merge"
            stats["same"] += int(bool(same))
            stats["predicted_merge"] += int(predicted)
            if predicted and same:
                tp += 1
                stats["tp"] += 1
            elif predicted and not same:
                fp += 1
                stats["fp"] += 1
            elif not predicted and same:
                fn += 1
                stats["fn"] += 1
            else:
                tn += 1
                stats["tn"] += 1
        per_stratum[stratum] = stats

    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    result = {
        "algorithm_version": "event-aggregate-v1",
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_merge_rate": round(fp / (tp + fp), 4) if tp + fp else 0.0,
        "miss_merge_rate": round(fn / (tp + fn), 4) if tp + fn else 0.0,
        "per_stratum": per_stratum,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
