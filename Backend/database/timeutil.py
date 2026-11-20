"""UTC timestamp helpers. All persisted timestamps are `...Z` ISO 8601."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> str:
    """Return the current UTC time as `YYYY-MM-DDTHH:MM:SSZ`."""

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
