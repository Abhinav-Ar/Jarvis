#!/bin/zsh
set -e

cd "${0:A:h:h}"

if [[ ! -d .venv ]]; then
  /opt/homebrew/bin/python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env. Add your OPENAI_API_KEY before starting ORION."
fi

echo "Setup complete. Start in text mode with: ./start.sh --text"
echo "Start in voice mode with: ./start.sh"
