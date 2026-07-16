#!/bin/zsh
set -e

PROJECT_DIR="${0:A:h:h}"
cd "$PROJECT_DIR"
PYTHON="${ORION_PYTHON:-$PROJECT_DIR/.venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  echo "ORION development environment is missing. Run ./setup.sh first."
  exit 1
fi

"$PYTHON" -m compileall -q src/orion tests
PYTHONPATH="$PROJECT_DIR/src/orion${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON" -m unittest discover -s tests
