#!/usr/bin/env bash
# Dual-purpose:
#   1. No args  → exec `uv run uvicorn ...` (what com.papers-cool.server LaunchAgent calls).
#   2. With arg → manage that LaunchAgent (restart / status / stop / start / logs).
#
# Mirrors your-dream-dict/scripts/run-server.sh so the muscle memory is the same.
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

LABEL="com.papers-cool.server"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
TARGET="gui/$(id -u)/${LABEL}"
LOG_DIR="$HOME/Library/Logs/papers-cool"
mkdir -p "$LOG_DIR"

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

case "${1:-run}" in
  run)
    # Bind 0.0.0.0 so the SSH tunnel / LAN can reach it.
    exec /opt/homebrew/bin/uv run uvicorn papers_cool.main:app \
        --host "$HOST" --port "$PORT" --log-level info
    ;;
  restart)
    launchctl kickstart -k "$TARGET"
    sleep 2
    launchctl print "$TARGET" | grep -E "state|pid" | head -3
    ;;
  status)
    launchctl print "$TARGET" | grep -E "state|pid" | head -3
    ;;
  start)
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    ;;
  stop)
    launchctl bootout "gui/$(id -u)" "$PLIST"
    ;;
  logs)
    exec tail -f "$LOG_DIR/server.log" "$LOG_DIR/server.err.log"
    ;;
  *)
    echo "usage: $0 [run|restart|status|start|stop|logs]" >&2
    exit 2
    ;;
esac
