#!/bin/zsh
set -e
cd "${0:A:h}"

if [[ ! -x .venv/bin/python ]]; then
  echo "ORION is not installed yet. Run ./setup.sh first."
  exit 1
fi

exec .venv/bin/python orion.py "$@"
