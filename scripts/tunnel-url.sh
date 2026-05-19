#!/usr/bin/env bash
# Print the public URL for the papers-cool VPS tunnel.
#
# Usage:
#   scripts/tunnel-url.sh         # print URL to stdout
#   scripts/tunnel-url.sh -c      # also copy to clipboard (macOS pbcopy)
set -euo pipefail

PUBLIC_URL="https://app.xingchendahai.org/papers/"

if [[ "${1:-}" == "-c" ]]; then
  printf '%s' "$PUBLIC_URL" | pbcopy
  echo "$PUBLIC_URL  (copied)"
else
  echo "$PUBLIC_URL"
fi
