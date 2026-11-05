---
name: nautilus-nrp
description: Create, run, monitor, diagnose and recover Kubernetes workloads on NRP Nautilus. Includes read-only live HTML dashboards, bounded monitoring and admission probes, general batch and sweep orchestration, exporting results through Pod logs, and OpenROAD/ORFS guidance (large-design limits, failure text, saved-grid congestion, rendering).
---

# Nautilus NRP workloads

Use this skill for Nautilus compute, storage and monitoring across builds,
simulations, ML, data processing, parameter sweeps and EDA. Keep workload
semantics and execution location defined by the user or repository. OpenROAD
is an optional specialization, not the assumed workload.

## Start with the current context

Read the project's agent rules and shared/assistant memory. Recover the active
coordinator, manifest, namespace, PVC, immutable runtime and ownership labels
before changing a live study. Reuse existing authorization; do not ask again for
routine steps already requested. A skill update does not authorize sending
messages, exposing a service, changing unrelated jobs or retrying scientific
failures. Preserve other assistants' files, processes and evidence.

Choose only the references needed:

- [Orchestration and recovery](references/orchestration.md): quota refill,
  resource sizing, startup pacing, stop guards that keep finished work,
  auxiliary Pods beside a live study, admission, metrics gaps, node-loss
  symptoms and exclusions, cancellation and holds, step-limit changes and
  step-limit kill races, memory livelock and OOM visibility, native evidence,
  CephFS recovery, exporting artifacts through stdout, node-local scratch
  staging and Pod identity recovery.
- [Live monitoring](references/live-monitoring.md): runnable HTML dashboard,
  application-ledger schema, admission probe and console watcher.
- [OpenROAD / ORFS](references/openroad.md): phase pools, endpoints, large-design
  step limits and memory ramps, diagnostics and failure text, frozen
  experiments, congestion from the saved global-routing grid, die shots and
  rendering costs.
- [Access, images and storage](references/access-images-storage.md): OIDC/SSH,
  registry credentials and PVC setup. Read when access or staging needs work.

## Cluster policy versus operational evidence

Check the [current NRP policies](https://nrp.ai/documentation/userdocs/start/policies/)
and [NRP guidance for AI assistants](https://nrp.ai/llms.txt) when making
policy-dependent decisions. Published utilization bands checked 2026-10-29:

| Resource | Published utilization against requests |
|---|---|
| CPU | 20–200% |
| RAM | 20–150% |
| GPU | Above 40% |

NRP limits violations to at most four pods; requests and limits must be within
20%, and equal for more than roughly 100 jobs/pods. The policy documents an
exception for pods requesting 1 CPU and 2 GB. Observed in 2026-10: the count is
per user account (other users' Pods in a shared namespace count against their
own accounts), and exempt-size Pods are still refused while the account is over
the limit. Auxiliary Pods (rendering, export) can push a study's account over;
see the orchestration reference. Probe the intended workload shape;
a tiny probe cannot establish that a large one will be admitted. Do not resize a
real workload solely to exploit an exception.

An idle `sleep infinity` batch Job is prohibited. Interactive pods have separate
rules (including a six-hour lifetime); do not generalize the batch prohibition
into a ban on every interactive sleep. Use a finite real-work Job for staging or
export, or an existing healthy workload, rather than an idle batch helper.

Keep three facts separate:

1. API access and metrics can work while new Pod admission is refused.
2. Instantaneous utilization, historical account enforcement and a native
   admission response can disagree. Missing/stale metrics are unknown, not zero
   and not healthy. Preserve timestamps and actual error text.
3. A low-utilization refusal establishes a current launch restriction, not a
   permanent administrative ban. In observed runs, refusal persisted after
   current readings returned in band; no fixed clearance ETA is established.

Do not delete currently healthy workers just because admission still refuses.
Inspect actual sustained idle/stall evidence and the user's remediation policy.
Sizing, small startup waves and prebuilt images reduce setup overhead. A startup
age threshold is a local heuristic, never a promised NRP grace period. In one
account, refusals followed start bursts in which a third to a half of the Pods
were young, and each blocked all new Pods for 1–4 hours. Pace starts by account
size (`scripts/start_budget.py`), start long-lived work first, and move
CephFS-heavy steps to node-local scratch; see the orchestration reference.

## Execution invariants

- Use explicit context and namespace. Every automated kubectl call needs both
  a request timeout and a wall-clock timeout including the OIDC plugin.
  The Python helpers bound the whole subprocess group.
- Name resources with the submitter's CruzID and label Jobs AND Pods with owner,
  workload and phase identifiers. Inspect namespace-wide usage, including other
  users and controllers; mutate only the authorized workload and exact UIDs.
- Read real ResourceQuotas, scopes and LimitRanges. A scoped priority-class quota
  of zero is not a global zero-Pod ceiling. A target such as 200 is a requested
  ceiling, not evidence of 200 running pods or a universal Nautilus limit.
- Set CPU, memory and ephemeral-storage requests and limits for every container,
  including init containers. Template values are illustrative; size them from
  the workload's measured use and local scratch needs.
- For maximum independent parallelism, use one eligible case per Job when setup
  overhead permits. Do not hide a lower per-design cap. Count shared reservations
  under one coordinator lock before launch. Never fabricate extra cases to fill
  slots once a finite workload tapers.
- Probe the full intended Pod spec with `--dry-run=server`. A Job-only dry run
  does not test the Pods its controller will create. Treat actual refusal as a
  deferred launch, before consuming an attempt when possible. Dry-run approval
  is time-specific; real admission can still refuse later.
- Keep source, images, worker scripts, manifests and endpoint settings immutable
  for live work. Create new versions for future Jobs instead of editing scripts
  under a running shell. Record resource-profile transitions and runtime hashes.
- A Job may finish successfully while individual application cases fail. Maintain
  per-case outcomes and endpoint receipts. Do not infer scientific success from
  Job Complete, a log substring or cached stdout with unknown native identity.
- Keep cancellation durable in the queue and across restarts. Preserve previous
  completed outcomes; cancel only unfinished work. Infrastructure, OOM, collection
  and scientific failures remain distinct. Recover only the affected case/phase
  according to the established retry policy, retaining the original seed and
  history. Never silently replace a failed scientific observation.
- Do not scan/export another live writer's PVC tree or clear a claim on age alone.
  Diagnose progress from native API, own-Pod stdout and bounded own-process
  inspection. Before recovery prove the old writer and controller are quiescent.

## Reusable scripts

[`examples/batch-job.json`](examples/batch-job.json) is a generic suspended-Job
starter. Replace owner, namespace, image/command, PVC and measured resources;
its sample CPU/RAM values are illustrative. Use the verified admission and
UID-bound unsuspend sequence in the orchestration reference. It has no idle
command, implicit retries or dependency on HighTide/OpenROAD.

All new helpers use Python's standard library and make **no cluster mutations**.
`check_admission.py` makes only a non-persisting server-side dry-run request.
They do not dispatch/retry work, allocate helper pods, publish a site or send
messages. A read-only dashboard is not a scheduler.

```bash
SKILL_DIR="$HOME/.claude/skills/nautilus-nrp"
python3 "$SKILL_DIR/scripts/live_status.py" \
  --context nautilus --namespace my-namespace \
  --selector 'app=my-study,user=my-cruzid' --output ./live-status --once
```

Omit `--once` for an owned host monitor. Add `--runs-file ./runs.json` for
parameters, seeds, reported results and artifacts, and `--admission-file` for a
recorded full-shape probe. The page distinguishes native state, reported case
outcomes and missing evidence; it has auto refresh, filters, sorting, CSV export,
quota/freshness panels and optional artifact images. No CDN or telemetry.

```bash
python3 "$SKILL_DIR/scripts/check_admission.py" \
  --context nautilus --namespace my-namespace --manifest ./job.json \
  --output ./admission.json
python3 "$SKILL_DIR/scripts/watch_job.py" \
  --context nautilus --namespace my-namespace --job my-cruzid-study-001 \
  --container worker --evidence-dir ./native-evidence
"$SKILL_DIR/examples/band-check.sh" my-namespace '^my-cruzid-'
```

For a dispatcher, two offline helpers read saved JSON and never contact the
cluster. `start_budget.py` turns `band_check.py --json` rows into the number of
new Pods that keep the still-ramping share under a proportional cap.
`pod_identity.py` recovers a gone Job's Pod name and UID from saved events or
Pod snapshots, handling truncated generated names; it exits 3 if any Job is
ambiguous or missing.

```bash
python3 "$SKILL_DIR/scripts/band_check.py" my-namespace '^my-cruzid-' --json > rows.json
python3 "$SKILL_DIR/scripts/start_budget.py" rows.json --pending 3
python3 "$SKILL_DIR/scripts/pod_identity.py" --jobs jobs.json \
  --events events.json --snapshots pod_snapshots.jsonl
```

[`examples/scratch_stage.py`](examples/scratch_stage.py) is a worker-side
pattern for running a step on node-local scratch with verified stage-in and
stage-out (temp + fsync + rename + re-read hash, then the done marker).

To get results out of a finite Pod without reading other Pods' trees, write
them to its stdout and collect the saved log after it ends.
`scripts/stdout_artifacts.py` provides the in-Pod `Emitter` (base64 chunks plus
a SHA-256 event per file, under a per-Pod budget below the kubelet's log
rotation size) and the host-side `collect`, which keeps only files whose hash
and size match. [`examples/stdout_export.sh`](examples/stdout_export.sh) does
the same with bash, gzip and coreutils on a stock image, splitting large files
into deterministic `gzip -9 -n` parts that follow-up Pods can complete.

```bash
timeout --signal=TERM --kill-after=5s 40s kubectl --context nautilus \
  -n my-namespace --request-timeout=30s logs pod/my-cruzid-export-abc12 > pod.log
python3 "$SKILL_DIR/scripts/stdout_artifacts.py" collect --log pod.log \
  --out ./artifacts --json ./artifacts/summary.json   # exits 1 if any file is damaged
```

For OpenROAD, [`examples/gcell_dump.tcl`](examples/gcell_dump.tcl) dumps the
congestion grid that global routing saved in an ODB, and
`scripts/gcell_stats.py` summarizes it over all GCells and outside macros
(see the OpenROAD reference for why both are needed).

```bash
GCELL_ODB=results/.../5_1_grt.odb GCELL_DUMP=grid.cong \
  openroad -no_init -exit "$SKILL_DIR/examples/gcell_dump.tcl"
python3 "$SKILL_DIR/scripts/gcell_stats.py" grid.cong --die-area-um2 3.2e7
```

The legacy `examples/monitor-job.sh` and `band-check.sh` CLI entrypoints remain.
The HighTide-specific `examples/run.sh`/`job-template.yaml` are preserved adapters,
not a universal sweep controller. They now use equal requests/limits, explicit
context and bounded API calls, and never delete/recreate a Job after a failed
submission. For a large research sweep, implement the queue/admission/evidence
invariants in the orchestration reference instead of treating that adapter as
an experiment harness.

Validate helper changes with `python3 -m unittest discover -s tests -v` from this
skill directory. Use the offline demo instructions in the monitoring reference;
validation does not launch compute or touch a live run tree.
