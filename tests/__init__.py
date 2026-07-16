"""ORION test suite bootstrap for the repository's standard ``src`` layout."""

from __future__ import annotations

import sys
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "src" / "orion"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
