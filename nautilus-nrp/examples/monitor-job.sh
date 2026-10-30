#!/usr/bin/env bash
# Read-only compatibility entrypoint for Claude Monitor or a host terminal.
# monitor-job.sh <job> <namespace> [milestone-regex]
# JOB, NS, PATTERN, SLEEP_SECS, NRP_CONTEXT and CONTAINER are also supported.
# Exit 0=native Complete, 1=native Failed, 2=observation/collection held.
# Suspended and FailureTarget are not terminal completion.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
JOB_NAME="${1:-${JOB:?job name required}}"
RUN_NAMESPACE="${2:-${NS:?namespace required}}"
MILESTONES="${3:-${PATTERN:-ERROR|FAILED|Traceback|Killed|OOM|Aborted|Elapsed time}}"
EXTRA=()
if [[ -n "${CONTAINER:-}" ]]; then EXTRA+=(--container "$CONTAINER"); fi
exec python3 "$SCRIPT_DIR/../scripts/watch_job.py" --job "$JOB_NAME" --namespace "$RUN_NAMESPACE" \
  --context "${NRP_CONTEXT:-nautilus}" --interval "${SLEEP_SECS:-60}" --pattern="$MILESTONES" "${EXTRA[@]}"
