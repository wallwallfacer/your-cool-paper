#!/usr/bin/env bash
# Manage the shared wstunnel LaunchAgent that exposes both dream-dict and
# papers-cool through the Azure VPS via WebSocket over HTTPS.
#
# Usage:
#   scripts/run-tunnel.sh         # run info (same as status)
#   scripts/run-tunnel.sh start   # start tunnel LaunchAgent
#   scripts/run-tunnel.sh stop    # stop tunnel LaunchAgent
#   scripts/run-tunnel.sh restart # restart tunnel
#   scripts/run-tunnel.sh status  # show tunnel status
#   scripts/run-tunnel.sh url     # print public URL
set -euo pipefail

PUBLIC_URL="https://app.xingchendahai.org/papers/"
LABEL="com.shared.wstunnel"
TARGET="gui/$(id -u)/${LABEL}"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

case "${1:-status}" in
  run|status)
    launchctl print "$TARGET" 2>/dev/null | grep -E "state|pid" | head -3 || echo "not loaded"
    echo "→ $PUBLIC_URL"
    ;;
  start)
    launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl kickstart "$TARGET"
    sleep 2
    "$0" status
    ;;
  stop)
    launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null && echo "tunnel stopped" || echo "tunnel not running"
    ;;
  restart)
    launchctl kickstart -k "$TARGET"
    sleep 2
    "$0" status
    ;;
  url)
    exec "$(dirname "$0")/tunnel-url.sh" "${2:-}"
    ;;
  *)
    echo "usage: $0 [run|start|stop|restart|status|url]" >&2
    exit 2
    ;;
esac
