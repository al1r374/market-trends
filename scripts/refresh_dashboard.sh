#!/usr/bin/env bash
# Refresh market_data.db, clear Streamlit caches, restart the dashboard.
# Use after adding/updating markets so new series appear in the app.
#
# Usage:
#   ./scripts/refresh_dashboard.sh              # update all markets
#   ./scripts/refresh_dashboard.sh GoldBox      # update selected market ids
#   ./scripts/refresh_dashboard.sh --no-update  # only clear cache + restart
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
if [[ ! -x "$PYTHON" || ! -x "$STREAMLIT" ]]; then
  echo "error: missing venv tools under $ROOT/.venv/bin" >&2
  exit 1
fi

DO_UPDATE=1
MARKET_ARGS=()
for arg in "$@"; do
  if [[ "$arg" == "--no-update" ]]; then
    DO_UPDATE=0
  else
    MARKET_ARGS+=(--market "$arg")
  fi
done

if [[ "$DO_UPDATE" -eq 1 ]]; then
  echo "==> Updating market data…"
  if [[ ${#MARKET_ARGS[@]} -gt 0 ]]; then
    "$PYTHON" -m market_trend.etl.update "${MARKET_ARGS[@]}"
  else
    "$PYTHON" -m market_trend.etl.update
  fi
fi

echo "==> Clearing Streamlit cache…"
"$STREAMLIT" cache clear

# Bust mtime-based @st.cache_data keys even if content was unchanged.
touch "$ROOT/market_data.db" "$ROOT/config.yaml" 2>/dev/null || true

# Drop stale bytecode so Streamlit reloads market_trend modules.
find "$ROOT/market_trend" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

LABEL="com.market-trend.app"
UID_NUM="$(id -u)"
if launchctl print "gui/${UID_NUM}/${LABEL}" >/dev/null 2>&1; then
  echo "==> Restarting LaunchAgent ${LABEL}…"
  launchctl kickstart -k "gui/${UID_NUM}/${LABEL}"
else
  echo "==> Restarting Streamlit on :8501…"
  if lsof -nP -iTCP:8501 -sTCP:LISTEN >/dev/null 2>&1; then
    # shellcheck disable=SC2046
    kill $(lsof -nP -iTCP:8501 -sTCP:LISTEN -t) 2>/dev/null || true
    sleep 1
  fi
  nohup "$ROOT/scripts/start_streamlit.sh" \
    >"$ROOT/logs/streamlit.out.log" 2>"$ROOT/logs/streamlit.err.log" &
fi

echo
echo "Done. Open http://127.0.0.1:8501 and select the new markets in the sidebar."
echo "(Query-param selection is sticky — newly added markets are not auto-selected.)"
