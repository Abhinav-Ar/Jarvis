#!/usr/bin/env python3
"""Preferred compatibility launcher for ORION."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


SOURCE = Path(__file__).resolve().parent / "src" / "orion"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

runpy.run_path(str(SOURCE / "orion.py"), run_name="__main__")
