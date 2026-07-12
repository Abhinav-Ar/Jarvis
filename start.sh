#!/bin/zsh
set -e
cd "${0:A:h}"

if [[ ! -x .venv/bin/python ]]; then
  echo "Jarvis is not installed yet. Run ./setup.sh first."
  exit 1
fi

exec .venv/bin/python jarvis.py "$@"
