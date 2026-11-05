#!/usr/bin/env bash
# Read-only compatibility entrypoint, with bounded API calls.
# band-check.sh <namespace> [pod-name-regex] [--context nautilus] [--json]
# Exit 0=in band, 1..100=outside count, 101/102=API error, 104=unknown metrics.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/../scripts/band_check.py" "$@"
