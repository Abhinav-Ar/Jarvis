#!/usr/bin/env python3
"""Compatibility launcher for the source-layout ORION runtime."""

from __future__ import annotations

import importlib.util
import runpy
import sys
from pathlib import Path


SOURCE = Path(__file__).resolve().parent / "src" / "orion"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

if __name__ == "__main__":
    runpy.run_path(str(SOURCE / "jarvis.py"), run_name="__main__")
else:
    specification = importlib.util.spec_from_file_location("_orion_jarvis_impl", SOURCE / "jarvis.py")
    if specification is None or specification.loader is None:
        raise ImportError("The ORION runtime entrypoint could not be loaded.")
    implementation = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(implementation)
    globals().update({name: value for name, value in vars(implementation).items() if not name.startswith("__")})
