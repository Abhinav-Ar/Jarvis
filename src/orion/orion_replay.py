"""Inspect ORION's sanitized regression replay corpus without executing actions."""

from __future__ import annotations
import argparse, json
from orion_kernel import kernel

def main() -> int:
    parser = argparse.ArgumentParser(description="ORION replay inspector")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--query", default="")
    args = parser.parse_args()
    with kernel()._connect() as db:
        if args.query:
            rows = db.execute("SELECT * FROM replay_turns WHERE request LIKE ? OR response LIKE ? ORDER BY id DESC LIMIT ?", (f"%{args.query}%", f"%{args.query}%", args.limit)).fetchall()
        else:
            rows = db.execute("SELECT * FROM replay_turns ORDER BY id DESC LIMIT ?", (args.limit,)).fetchall()
    print(json.dumps([dict(row) for row in rows], indent=2))
    return 0

if __name__ == "__main__": raise SystemExit(main())
