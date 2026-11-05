# Live HTML and console monitoring

The helpers are workload-independent, host-side and read-only. They do not
replace a dispatcher or application-specific evidence collector. All Python
dependencies are in the standard library; native collection also needs kubectl
and the configured OIDC plugin. Every subprocess is bounded including auth.

## Start a live dashboard

```bash
SKILL_DIR="$HOME/.claude/skills/nautilus-nrp"
python3 "$SKILL_DIR/scripts/live_status.py" \
  --context nautilus --namespace my-namespace \
  --selector 'app=my-study,user=my-cruzid' \
  --output ./live-status
```

Use `--once` for one snapshot. For persistent use, start it through the project's
existing host process manager, recording the PID/command and stdout path. Do not
start another dispatcher or a cluster helper for a dashboard. One output lock
prevents overlapping collectors. Reusing an output directory with another scope
is rejected. No changes to running experiments are needed.

Open `live-status/index.html`. It embeds its current dataset and works offline.
In file mode auto refresh reloads the generated file while retaining filters
in the URL hash. For smoother polling, the user may serve that local directory:

```bash
python3 -m http.server --bind 127.0.0.1 --directory ./live-status 8765
```

This is a local-only option; do not publish/expose a service without the user's
requested scope. HTTP mode polls sibling snapshot.json. A failed fetch retains
the last good display and shows an error; it never substitutes empty success.

Output files:

- `index.html`: standalone page, no CDN or external scripts.
- `snapshot.json`: current display data, polled by the page.
- `collector-state.json`: compact last-good native observations for restart.
- `.monitor.lock`: one collector per output directory.

Files are written atomically with owner-only permissions. Observation failures
retain prior values AND their original timestamps, recording the failed attempt
separately. The page shows stale/unavailable sources, namespace versus workload
counts, scoped quotas, target versus actual count, native states, reported
application states, instantaneous CPU/RAM and artifact links. GPU utilization,
peak RSS, source validity and scientific quality are outside this collector.
Bulk PVC reads and log scraping are not part of native collection.

## Attach a local application ledger

Use `--runs-file ./runs.json` to display individual cases, parameters, metrics
and artifacts. An application adapter should export this normalized form from
its authoritative local coordinator ledger. Do not point it into a live PVC.

```json
{
  "title": "My parameter study",
  "updated_at": "2026-10-18T12:00:00+00:00",
  "target_pods": 200,
  "runs": [
    {
      "run_id": "model_a_lr001_seed42",
      "group": "model_a",
      "seed": 42,
      "parameters": {"learning_rate": 0.001},
      "status": "complete",
      "phase": "evaluate",
      "endpoint": "evaluation.json",
      "job_name": "my-cruzid-evaluate-001",
      "job_uid": "retained-native-job-uid",
      "evidence": {
        "reference": "evidence/case001-receipt.json",
        "job_uid": "retained-native-job-uid",
        "pod_uid": "retained-native-pod-uid",
        "endpoint": "evaluation.json"
      },
      "metrics": {"accuracy": 0.92, "wall_seconds": 180},
      "artifacts": [
        {"label": "Loss curve", "href": "images/loss.png", "image": true}
      ]
    }
  ]
}
```

Supported application statuses: planned, running, complete, flow_failed, held,
collection_held, cancelled, unknown. run_id must be unique. Optional group,
seed, parameters, phase, endpoint, metrics and artifacts work for any workload.
All planned rows remain, including cancelled and failed cases. Duplicate IDs
or invalid URLs are rejected rather than silently dropping data.

Application verdicts remain **reported by the adapter**. It must first verify
the real case/phase/endpoint receipts, runtime/config hashes and native identity
according to its experiment rules. The dashboard cannot independently validate
an arbitrary scientific outcome. Terminal reports missing reference/UID/endpoint
metadata are labelled unverified; current native UID conflicts are held. Native
objects can legitimately expire after evidence is retained, so the application
ledger may outlive them. Native Job Complete/Failed are separate columns and do
not themselves populate application successes/failures.

Artifact paths resolve relative to the dashboard directory. Use existing local
results or authorized HTTP(S) links; script/file/data URLs are rejected. Images
load only when the user selects Show image. The adapter should supply figure
labels including stage, method, units and any missing-data explanation. Do not
invent artifacts for stages that never ran.

Filtering covers groups, reported and native states, and free-text search over
parameters, nodes and metrics. Headers sort rows. CSV exports only the filtered
rows and quotes fields, neutralizing spreadsheet formula prefixes in strings.
Unknown measurements remain missing rather than zero.

## Record full-shape admission separately

```bash
python3 "$SKILL_DIR/scripts/check_admission.py" \
  --context nautilus --namespace my-namespace --manifest ./intended-job.json \
  --output ./admission.json
```

Input is the exact intended Job or Pod JSON (a Job contributes its Pod template).
Use the adaptable [generic Job starter](../examples/batch-job.json) when the
project does not already have one; replace its example identity, workload and
measured resource profile before probing or creating anything.
The helper preserves the Pod spec, labels and annotations, changes only the
probe name, and requests a **Pod CREATE server dry-run**. It creates no real
Job/Pod or seed attempt. Output includes time, scope, spec hash and allowed/error;
exit codes are 0 admitted, 1 explicitly refused, 2 unknown/auth/transport timeout.
Add `--admission-file ./admission.json` to the dashboard. Another namespace's
proof is marked unknown, and old proof is shown as historical. A real scheduler
still must handle actual create/unsuspend rejection and quota races.

## Console watch and band checks

```bash
python3 "$SKILL_DIR/scripts/watch_job.py" \
  --context nautilus --namespace my-namespace --job my-cruzid-study-001 \
  --container worker --job-uid known-native-uid \
  --pattern 'epoch|checkpoint|synth|grt|ERROR|FAILED|Killed|OOM' \
  --evidence-dir ./native-evidence
"$SKILL_DIR/examples/band-check.sh" my-namespace '^my-cruzid-' --json
```

The watcher handles all exact owned Pods, binds stdout before/after to Pod UID,
deduplicates milestones and stops only on native Complete/Failed. Suspended or
FailureTarget does not mean completion. Native failure exits 1, missing required
observations/terminal stdout exits 2. Its stdout is a bounded diagnostic tail,
not a complete scientific receipt collector; a long batch needs its own retained
per-case event stream and final evidence. Multi-container workloads should name
the application container explicitly.

The band checker includes init peaks, sidecars, Pod-level requests and overhead.
Missing, stale, identity-mismatched or partial metrics are unknown. It checks
CPU/RAM only and does not probe admission. Exit codes: 0 all observed in band,
1–100 outside count, 101/102 API/metrics failure, 104 unknown without a known
outside result. The shell entrypoints retain their original calling convention.

## Offline demo and validation

```bash
python3 "$SKILL_DIR/scripts/demo_status.py" --output ./nautilus-demo
python3 -m unittest discover -s "$SKILL_DIR/tests" -v
```

The demo is synthetic, includes training, simulation and OpenROAD cases, and
performs no cluster calls or EDA. It is a UI example, never experimental evidence.
Use `live_status.py --snapshot-file ./retained-collector-state.json --runs-file
./runs.json --output ./review --once` to render already-retained real evidence
offline. Do not treat a historical file's generated timestamp as a fresh API read.
