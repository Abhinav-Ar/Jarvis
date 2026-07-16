#!/bin/zsh
set -e
PROJECT_DIR="${0:A:h:h}"
cd "$PROJECT_DIR"

if [[ ! -x .venv/bin/python ]]; then
  echo "ORION is not installed yet. Run ./setup.sh first."
  exit 1
fi

exec .venv/bin/python src/orion/orion.py "$@"
