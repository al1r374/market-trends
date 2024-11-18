#!/usr/bin/env bash
# One-shot install: markets.local hosts entry + LaunchAgent/Daemon for app + proxy.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(id -un)"
UID_NUM="$(id -u)"
AGENTS_DIR="$HOME/Library/LaunchAgents"
DAEMONS_DIR="/Library/LaunchDaemons"

APP_SRC="$ROOT/scripts/com.market-trend.app.plist"
PROXY_SRC="$ROOT/scripts/com.market-trend.proxy.plist"
APP_DST="$AGENTS_DIR/com.market-trend.app.plist"
PROXY_DST="$DAEMONS_DIR/com.market-trend.proxy.plist"

mkdir -p "$ROOT/logs" "$AGENTS_DIR"
chmod +x "$ROOT/scripts/start_streamlit.sh" "$ROOT/scripts/fetch_prices_daily.sh"

if ! command -v caddy >/dev/null 2>&1 && [[ ! -x /opt/homebrew/bin/caddy ]]; then
  echo "error: caddy not found; run: brew install caddy" >&2
  exit 1
fi

# Resolve http://markets.local/ via /etc/hosts (needs sudo).
# Both A and AAAA avoid macOS mDNS/IPv6 stalls on *.local names.
# Drop legacy market.local entries if present.
if grep -Eq '[[:space:]]market\.local([[:space:]]|$)' /etc/hosts; then
  echo "Removing legacy market.local from /etc/hosts (sudo)…"
  sudo sed -i '' -E '/[[:space:]]market\.local([[:space:]]|$)/d' /etc/hosts
fi
if ! grep -Eq '^[[:space:]]*127\.0\.0\.1[[:space:]]+markets\.local([[:space:]]|$)' /etc/hosts; then
  echo "Adding markets.local (IPv4) to /etc/hosts (sudo)…"
  echo "127.0.0.1	markets.local" | sudo tee -a /etc/hosts >/dev/null
fi
if ! grep -Eq '^[[:space:]]*::1[[:space:]]+markets\.local([[:space:]]|$)' /etc/hosts; then
  echo "Adding markets.local (IPv6) to /etc/hosts (sudo)…"
  echo "::1	markets.local" | sudo tee -a /etc/hosts >/dev/null
fi

# Streamlit: user LaunchAgent (login).
cp "$APP_SRC" "$APP_DST"
launchctl bootout "gui/$UID_NUM/com.market-trend.app" 2>/dev/null || true
if ! launchctl bootstrap "gui/$UID_NUM" "$APP_DST" 2>/dev/null; then
  # Already registered or bootstrap race — reload in place.
  launchctl unload "$APP_DST" 2>/dev/null || true
  launchctl load "$APP_DST"
fi
launchctl enable "gui/$UID_NUM/com.market-trend.app" 2>/dev/null || true
launchctl kickstart -k "gui/$UID_NUM/com.market-trend.app" 2>/dev/null \
  || launchctl start com.market-trend.app

# Caddy on :80 needs root → LaunchDaemon.
echo "Installing Caddy LaunchDaemon for port 80 (sudo)…"
sudo cp "$PROXY_SRC" "$PROXY_DST"
sudo chown root:wheel "$PROXY_DST"
sudo launchctl bootout system/com.market-trend.proxy 2>/dev/null || true
if ! sudo launchctl bootstrap system "$PROXY_DST" 2>/dev/null; then
  sudo launchctl unload "$PROXY_DST" 2>/dev/null || true
  sudo launchctl load "$PROXY_DST"
fi
sudo launchctl enable system/com.market-trend.proxy 2>/dev/null || true
sudo launchctl kickstart -k system/com.market-trend.proxy 2>/dev/null \
  || sudo launchctl start com.market-trend.proxy

# Quick health check
sleep 1
if ! curl -sf --max-time 5 http://127.0.0.1:8501/_stcore/health >/dev/null; then
  echo "warning: Streamlit not healthy on :8501 — see $ROOT/logs/streamlit.err.log" >&2
fi
if ! curl -sf --max-time 5 http://markets.local/ >/dev/null; then
  echo "warning: http://markets.local/ not reachable — see $ROOT/logs/caddy.err.log" >&2
fi

echo
echo "Done. Open: http://markets.local/"
echo "Logs: $ROOT/logs/"
echo "User: $USER_NAME"
