"""UTC timestamps and monotonic uptime helpers.

Contract: `Docs/API_CONTRACT.md` §6.5/§10.2 require `ts`/`timestamp` in UTC
RFC3339 ending with `Z`, and `uptime_seconds` from a monotonic clock.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

# Imported as early as possible by `main.py`; the process starts a few
# milliseconds later, which is immaterial for a Phase 0 uptime counter.
PROCESS_START_MONOTONIC = time.monotonic()


def utc_timestamp() -> str:
    """Return current UTC time as RFC3339 with millisecond precision and `Z`."""

    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def uptime_seconds() -> float:
    """Seconds since process start, measured on the monotonic clock."""

    return max(0.0, time.monotonic() - PROCESS_START_MONOTONIC)
