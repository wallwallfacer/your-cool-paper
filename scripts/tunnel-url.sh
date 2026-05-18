#!/usr/bin/env bash
# Print the current Cloudflare quick-tunnel URL for the running com.papers-cool.tunnel.
# The URL is regenerated every time cloudflared restarts (quick-tunnel mode), so
# this just greps the most recent one out of the LaunchAgent's log.
#
# Usage:
#   scripts/tunnel-url.sh         # print URL to stdout
#   scripts/tunnel-url.sh -c      # also copy to clipboard (macOS pbcopy)
set -euo pipefail

LOG="${HOME}/.papers-cool/tunnel.log"
if [[ ! -f "$LOG" ]]; then
  echo "tunnel log not found: $LOG" >&2
  exit 1
fi

url=$(grep -oE 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' "$LOG" | tail -1 || true)
if [[ -z "$url" ]]; then
  echo "no tunnel URL found in $LOG" >&2
  exit 1
fi

if [[ "${1:-}" == "-c" ]]; then
  printf '%s' "$url" | pbcopy
  echo "$url  (copied)"
else
  echo "$url"
fi
