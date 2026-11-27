#!/usr/bin/env bash
# Start CertiFlow for development: API on :8000 + frontend (hot reload) on :5173.
# Open http://localhost:5173 (VS Code forwards the port). Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")"

# Local settings and API key (git-ignored): cp .env.dev.example .env.dev
if [ -f .env.dev ]; then set -a; . ./.env.dev; set +a; fi

export CERTIFLOW_LIBRARY="${CERTIFLOW_LIBRARY:-samples/assets/library.json}"
export CERTIFLOW_LLM="${CERTIFLOW_LLM:-mock}"

. .venv/bin/activate

# Restart cleanly if an earlier run is still holding the ports
fuser -k 8000/tcp 5173/tcp >/dev/null 2>&1 || true

# Bring the database schema up to date (Alembic migrations; does nothing if already current)
certiflow web init-db

certiflow web serve --port 8000 &
API=$!
(cd web && npm run dev -- --port 5173 --strictPort) &
WEB=$!

trap 'kill $API $WEB 2>/dev/null; wait 2>/dev/null' EXIT INT TERM
echo "CertiFlow dev: http://localhost:5173  (library=$CERTIFLOW_LIBRARY, llm=$CERTIFLOW_LLM)"
wait -n
