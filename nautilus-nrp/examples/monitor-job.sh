#!/bin/bash
# Stream milestones from a long-running Kubernetes Job for use with Claude
# Code's `Monitor` tool. Emits one line per phase change or stage milestone
# (de-duplicated), then exits on terminal success/failure with a tail of
# the last log lines.
#
# Intended use: pass the body of this script (with JOB/NS/PATTERN filled
# in) as the `command` to the Monitor tool. Each echoed line becomes a
# chat notification, so the grep filter must be narrow enough to avoid
# flooding but wide enough to cover every terminal state (success AND
# crash/OOM/kill).
#
# Usage:
#   ./monitor-job.sh <job-name> <namespace> [milestone-regex]
#
# Example (adapted inline in a Monitor invocation):
#   JOB=my-hightide-job NS=vlsida \
#   PATTERN='synth|floorplan|place|cts|route|final|ERROR|FAILED|Traceback|Killed|OOM' \
#   ./monitor-job.sh
#
# Exit codes:
#   0 — job reached a terminal condition (check last log lines for pass/fail)
#   non-zero — script error

set +e

JOB="${1:-${JOB:?job name required}}"
NS="${2:-${NS:?namespace required}}"
PATTERN="${3:-${PATTERN:-ERROR|FAILED|Traceback|Killed|OOM|Aborted|INFO: Build completed|Elapsed time}}"
SLEEP_SECS="${SLEEP_SECS:-60}"

echo "watch: job=$JOB ns=$NS pattern=$PATTERN"

last_phase=""
last_milestone=""

while true; do
    # Pod phase changes (Pending → Running → Succeeded/Failed)
    phase=$(kubectl get pod -n "$NS" \
        -l "job-name=$JOB" \
        -o jsonpath='{.items[0].status.phase}' 2>/dev/null)
    if [[ -n "$phase" && "$phase" != "$last_phase" ]]; then
        echo "phase: $phase"
        last_phase="$phase"
    fi

    # Terminal job condition — emit once, dump tail, exit
    jobstate=$(kubectl get job "$JOB" -n "$NS" \
        -o jsonpath='{.status.conditions[?(@.status=="True")].type}' 2>/dev/null)
    if [[ -n "$jobstate" ]]; then
        echo "job-condition: $jobstate"
        kubectl logs "job/$JOB" -n "$NS" --tail=40 2>/dev/null \
            | sed 's/^/log: /'
        break
    fi

    # Stage milestones — grep the recent log tail, emit only on change
    if [[ "$phase" == "Running" ]]; then
        line=$(kubectl logs "job/$JOB" -n "$NS" --tail=200 2>/dev/null \
            | grep -E --line-buffered "$PATTERN" \
            | tail -1)
        if [[ -n "$line" && "$line" != "$last_milestone" ]]; then
            echo "log: $line"
            last_milestone="$line"
        fi
    fi

    sleep "$SLEEP_SECS"
done
