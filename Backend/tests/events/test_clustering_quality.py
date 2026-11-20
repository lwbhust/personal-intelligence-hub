"""Clustering quality metrics over the gold-labelled fixture set.

Metrics are pairwise: every unordered article pair is labelled same/different
by the gold `groups` and by the produced event partition. Review cases count as
"not merged" (safety preference: never falsely merge).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import database

from event_support import list_events, run_clustering, seed_article, stamp
from test_clustering import FIXTURE, load_cases, partition


def _metrics(results: list[tuple[list[int], list[str]]]) -> dict[str, float]:
    tp = fp = fn = 0
    for groups, assignment in results:
        for left in range(len(groups)):
            for right in range(left + 1, len(groups)):
                gold_same = groups[left] == groups[right]
                predicted_same = assignment[left] == assignment[right]
                if gold_same and predicted_same:
                    tp += 1
                elif not gold_same and predicted_same:
                    fp += 1
                elif gold_same and not predicted_same:
                    fn += 1
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_merge_rate": round(fp / (tp + fp), 4) if tp + fp else 0.0,
        "miss_merge_rate": round(fn / (tp + fn), 4) if tp + fn else 0.0,
    }


def test_clustering_quality_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases = load_cases()
    results: list[tuple[list[int], list[str]]] = []
    review_decisions: list[str] = []

    for index, case in enumerate(cases):
        data_dir = tmp_path / f"case-{index}"
        monkeypatch.setenv("PIH_DATA_DIR", str(data_dir))
        assert database.initialize().status == "ok"

        seeded = [
            seed_article(
                title=str(item["title"]),
                category=str(item["category"]),
                summary=str(item["summary"]),
                keywords=list(item["keywords"]),
                entities=[tuple(pair) for pair in item["entities"]],
                source_name=str(item["source"]),
                published_at=stamp(float(item.get("days_ago", 0.0))),
                content_hash=item.get("content_hash"),
            )
            for item in case["articles"]
        ]
        run = run_clustering(scope="incremental")
        assert run.status == "succeeded", case["id"]

        article_ids = [item.article_id for item in seeded]
        assignment_map = partition(article_ids)
        assignment = [assignment_map[article_id] for article_id in article_ids]
        results.append(([int(group) for group in case["groups"]], assignment))

        with database.read_session() as conn:
            rows = conn.execute(
                "SELECT decision FROM event_candidate_decisions"
            ).fetchall()
        review_decisions.extend(str(row[0]) for row in rows)

    metrics = _metrics(results)
    review_cases = sum(1 for case in cases if case["expect"] == "review")
    ambiguous = sum(1 for decision in review_decisions if decision == "ambiguous")
    human_review_ratio = (
        round(ambiguous / len(review_decisions), 4) if review_decisions else 0.0
    )

    assert metrics["false_merge_rate"] == 0.0, metrics
    assert metrics["precision"] >= 0.95, metrics
    assert metrics["recall"] >= 0.80, metrics
    assert metrics["f1"] >= 0.85, metrics
    assert ambiguous >= review_cases, metrics
    assert human_review_ratio <= 0.35, metrics

    # Keep the metrics visible in test output for the acceptance report.
    summary = {**metrics, "cases": len(cases), "ambiguous_decisions": ambiguous,
               "human_review_ratio": human_review_ratio}
    print("CLUSTERING_METRICS=" + json.dumps(summary, ensure_ascii=False))
