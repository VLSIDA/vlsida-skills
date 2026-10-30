#!/bin/bash
# Export closed files from a PVC through this Pod's stdout using only bash + coreutils + gzip (runs on a stock
# ubuntu image: no Python, no bootstrap). Pair with scripts/stdout_artifacts.py on the host.
#
# Plan (one line per file, tab-separated):   <id> <TAB> <path> <TAB> <parts: "all" or comma-separated indices>
# Each file is compressed with `gzip -9 -n` (no name/timestamp, so every Pod produces the same bytes) and split
# into PART-byte parts. Requested parts are written as `UCRC <part sha> <i> <base64 line>` chunks plus one
# `UCR {"event":"ARTIFACT",...,"part":k,"parts":n,"full_sha256":...}` event. Parts past the per-Pod base64 BUDGET
# become PART_DEFERRED events so the host can start a follow-up Pod for exactly those parts; the host keeps a
# file only when the joined parts match full_sha256. Mount the PVC read-only; write only to SCRATCH.
#
# Size BUDGET under the kubelet's container-log rotation size (often 10 MiB): `kubectl logs` returns only the
# current log file, so anything written before a rotation is lost.
set -uo pipefail
PLAN=${PLAN:-/control/export_plan.tsv}
SCRATCH=${SCRATCH:-/scratch/export}
PART=${PART:-4800000}
BUDGET=${BUDGET:-7000000}
used=0
ev() { printf 'UCR %s\n' "$1"; }
while IFS=$'\t' read -r id path want; do
  [ -n "$id" ] || continue
  if [ ! -f "$path" ]; then ev "{\"event\":\"MISSING\",\"run_id\":\"$id\",\"path\":\"$path\"}"; continue; fi
  rm -rf "$SCRATCH" && mkdir -p "$SCRATCH"
  gzip -9 -n -c "$path" > "$SCRATCH/f.gz" || { ev "{\"event\":\"EXPORT_ERROR\",\"run_id\":\"$id\",\"error\":\"gzip failed\"}"; continue; }
  full_sha=$(sha256sum "$SCRATCH/f.gz" | cut -d' ' -f1)
  full_bytes=$(stat -c %s "$SCRATCH/f.gz")
  (cd "$SCRATCH" && split -b "$PART" -d -a 3 f.gz p_)
  parts=$(ls "$SCRATCH"/p_* | wc -l)
  if [ "$want" = all ]; then idx=$(seq 0 $((parts - 1))); else idx=$(echo "$want" | tr ',' ' '); fi
  for k in $idx; do
    f=$(printf '%s/p_%03d' "$SCRATCH" "$k")
    [ -f "$f" ] || { ev "{\"event\":\"EXPORT_ERROR\",\"run_id\":\"$id\",\"error\":\"no part $k of $parts\"}"; continue; }
    b=$(stat -c %s "$f"); need=$(( (b + 2) / 3 * 4 ))
    psha=$(sha256sum "$f" | cut -d' ' -f1)
    if [ $((used + need)) -gt "$BUDGET" ]; then
      ev "{\"event\":\"PART_DEFERRED\",\"run_id\":\"$id\",\"part\":$k,\"parts\":$parts,\"full_sha256\":\"$full_sha\",\"full_bytes\":$full_bytes}"
      continue
    fi
    n=0
    while IFS= read -r line; do printf 'UCRC %s %d %s\n' "$psha" "$n" "$line"; n=$((n + 1)); done < <(base64 -w 12000 "$f")
    used=$((used + need))
    ev "{\"event\":\"ARTIFACT\",\"run_id\":\"$id\",\"kind\":\"gzip_part\",\"name\":\"$(basename "$path").gz\",\"part\":$k,\"parts\":$parts,\"full_sha256\":\"$full_sha\",\"full_bytes\":$full_bytes,\"source\":\"$path\",\"sha256\":\"$psha\",\"bytes\":$b,\"chunks\":$n}"
  done
done < "$PLAN"
ev "{\"event\":\"BATCH_COMPLETE\",\"pod\":\"${POD_NAME:-}\",\"exported_b64\":$used}"
