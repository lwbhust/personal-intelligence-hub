"""Make the flat `Backend/` layout importable for data-layer tests.

The backend uses a top-level `database` package (no `Backend/__init__.py`),
so repo-root execution must add `Backend/` to `sys.path`.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
