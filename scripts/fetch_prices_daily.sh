#!/usr/bin/env bash
# Daily refresh of all configured market prices into market_data.db.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

PYTHON="$ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "error: missing venv python at $PYTHON" >&2
  exit 1
fi

LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/fetch_prices.log"

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
  "$PYTHON" -m market_trend.etl.update
  status=$?
  echo "exit=$status"
  exit "$status"
} >>"$LOG_FILE" 2>&1
