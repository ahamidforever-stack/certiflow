#!/usr/bin/env bash
# Start a throw-away CertiFlow for the Playwright walkthrough: mock LLM (free, offline), sample office
# assets, a fresh database in $E2E_DIR, the built frontend served by the API on $E2E_PORT.
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${E2E_DIR:?}" "${E2E_PORT:?}"
rm -rf "$E2E_DIR" && mkdir -p "$E2E_DIR"
export CERTIFLOW_DATA_DIR="$E2E_DIR/data" CERTIFLOW_LLM=mock CERTIFLOW_QUEUE=thread \
       CERTIFLOW_LIBRARY=samples/assets/library.json CERTIFLOW_STATIC_DIR="$E2E_DIR/dist" \
       CERTIFLOW_SECRET_KEY=e2e-only-not-secret CERTIFLOW_DATABASE_URL= CERTIFLOW_CHECKPOINT_DSN=
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
(cd web && npx vite build --outDir "$E2E_DIR/dist" --emptyOutDir --logLevel warn)
$PY -m certiflow.cli web init-db >/dev/null
$PY -m certiflow.cli web create-user translator1 --role certified_translator --name "E2E Translator" --password e2e-pass-123 >/dev/null
$PY -c "import sys; from pathlib import Path; from certiflow import samples; samples.make_source_pdf(Path(sys.argv[1]))" "$E2E_DIR/certificate.pdf"
exec $PY -m certiflow.cli web serve --host 127.0.0.1 --port "$E2E_PORT"
