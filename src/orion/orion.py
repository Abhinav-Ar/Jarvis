"""ORION application entry point; legacy jarvis.py remains migration-compatible."""
from jarvis import main

if __name__ == "__main__":
    raise SystemExit(main())
