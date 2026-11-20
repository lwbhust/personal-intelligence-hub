"""Article retention: soft-delete stale articles without losing evidence.

Policy
------
* Only articles older than the retention window are candidates.
* Favourites, later-read items, and articles attached to an event are never
  removed: they are user marks or evidence for event intelligence.
* Removal is a soft delete (`articles.deleted_at`), so rows stay traceable and
  the operation is reversible. The SQLite file does not shrink; run `VACUUM`
  separately if disk space must be reclaimed.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import database
from core.timeutil import utc_timestamp

DEFAULT_RETENTION_DAYS = 30
RETENTION_DAYS_ENV = "PIH_ARTICLE_RETENTION_DAYS"
RETENTION_ENABLED_ENV = "PIH_ARTICLE_RETENTION_ENABLED"
UPDATE_BATCH = 500

_CANDIDATE_SQL = """
SELECT a.id
FROM articles AS a
WHERE a.deleted_at IS NULL
  AND a.published_at IS NOT NULL
  AND a.published_at < ?
  AND a.is_favorite = 0
  AND a.reading_status <> 'later'
  AND NOT EXISTS (
      SELECT 1
      FROM event_articles AS ea
      WHERE ea.article_id = a.id
  )
"""


def retention_enabled() -> bool:
    return os.environ.get(RETENTION_ENABLED_ENV, "1") != "0"


def retention_days() -> int:
    raw = os.environ.get(RETENTION_DAYS_ENV)
    if raw is None:
        return DEFAULT_RETENTION_DAYS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_RETENTION_DAYS
    return value if value >= 1 else DEFAULT_RETENTION_DAYS


def _cutoff(days: int) -> str:
    moment = datetime.now(timezone.utc) - timedelta(days=days)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def prune_articles(
    *,
    days: int | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    """Soft-delete articles outside the retention window.

    Returns a small report so callers can log or surface the outcome.
    """

    window = retention_days() if days is None else max(1, int(days))
    cutoff = _cutoff(window)
    now = utc_timestamp()

    with database.session() as conn:
        rows = conn.execute(_CANDIDATE_SQL, (cutoff,)).fetchall()
        ids = [str(row[0]) for row in rows]
        if not dry_run:
            for start in range(0, len(ids), UPDATE_BATCH):
                chunk = ids[start : start + UPDATE_BATCH]
                placeholders = ", ".join("?" for _ in chunk)
                conn.execute(
                    f"UPDATE articles SET deleted_at = ?, updated_at = ? "
                    f"WHERE id IN ({placeholders}) AND deleted_at IS NULL",
                    (now, now, *chunk),
                )

    return {
        "days": window,
        "cutoff": cutoff,
        "candidates": len(ids),
        "deleted": 0 if dry_run else len(ids),
        "dry_run": dry_run,
    }
