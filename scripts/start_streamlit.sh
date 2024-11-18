#!/usr/bin/env bash
# Start the Market Trend Streamlit app (used by LaunchAgent).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

PYTHON="$ROOT/.venv/bin/python"
STREAMLIT="$ROOT/.venv/bin/streamlit"
if [[ ! -x "$STREAMLIT" ]]; then
  echo "error: missing streamlit at $STREAMLIT" >&2
  exit 1
fi

exec "$STREAMLIT" run "$ROOT/app/streamlit_app.py" \
  --server.address=127.0.0.1 \
  --server.port=8501 \
  --server.headless=true \
  --browser.gatherUsageStats=false
