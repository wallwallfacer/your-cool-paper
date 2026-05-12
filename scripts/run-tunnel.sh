#!/usr/bin/env bash
# Run the cloudflared quick-tunnel pointed at the local papers-cool server.
# Same LaunchAgent management pattern as run-server.sh.
#
# Install cloudflared:  brew install cloudflared
set -euo pipefail

cd "$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

LABEL="com.papers-cool.tunnel"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
TARGET="gui/$(id -u)/${LABEL}"
LOG_DIR="$HOME/.papers-cool"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/tunnel.log"

PORT="${PORT:-8000}"

case "${1:-run}" in
  run)
    # quick-tunnel mode → generates a fresh https://<random>.trycloudflare.com on each start.
    # Logs are appended; tunnel-url.sh greps the most recent URL out of the file.
    exec /opt/homebrew/bin/cloudflared tunnel \
        --no-autoupdate \
        --url "http://127.0.0.1:${PORT}" \
        --logfile "$LOG_FILE" \
        --loglevel info
    ;;
  restart)
    launchctl kickstart -k "$TARGET"
    sleep 4
    "$(dirname "$0")/tunnel-url.sh"
    ;;
  status)
    launchctl print "$TARGET" | grep -E "state|pid" | head -3
    ;;
  start)
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    sleep 4
    "$(dirname "$0")/tunnel-url.sh"
    ;;
  stop)
    launchctl bootout "gui/$(id -u)" "$PLIST"
    ;;
  logs)
    exec tail -f "$LOG_FILE"
    ;;
  url)
    exec "$(dirname "$0")/tunnel-url.sh" "${2:-}"
    ;;
  *)
    echo "usage: $0 [run|start|stop|restart|status|logs|url]" >&2
    exit 2
    ;;
esac
