# Orchestration, evidence and recovery

This applies to any finite build, training, simulation, analysis or EDA workload.
Read project rules first. Existing owner instructions define execution location,
the intended endpoint, retry policy, concurrency target and preservation scope.

## Resource sizing and throughput

Measure CPU, working-set memory, cgroup memory peak and application child RSS
per phase; they are different measurements. Size memory with measured peak
headroom. Do not shrink a late-stage limit because an early sample is small.
Keep real application thread counts and CPU requests consistent: a serial tail
using 0.925 cores is 19.3% of a 4.8-core request but 23.1% of a 4-core request.
This is arithmetic about a measured case, not a universal four-core setting.

Large file copies through CephFS fill the page cache, and the kernel charges it
to the Pod's memory cgroup. The cgroup peak and working set of a copy-heavy
phase then include cache, so size memory from the application's own peak RSS
(the children's maximum resident set). A peak measured in a Pod killed early is
a lower bound. After a native OOMKilled, hold the case for resources and retry
with a larger request (one study used 1.5 times the killed limit), not the same
shape.

Separate phases with different resource profiles when there is a durable,
verified handoff. Examples include preprocessing/training/evaluation,
compile/test, and placement/routing. Only the predecessor's completed case may
enter its successor. Do not rerun a completed predecessor to change pod shape.
Do not assume in-place resource resizing is supported or admitted; an observed
resize rejection leaves the existing allocation unchanged.

For many independent expensive cases, one case per Job increases real
parallelism and confines failures. Small batches can be better for very short
cases with expensive setup. Batch size, image/bootstrap overhead, measured phase
lengths and remaining case count should explain the choice. Prebuilt private
images, immutable archives and local emptyDir scratch can reduce startup cost;
do not fan out simultaneous package installation without considering the setup
window and registry/network load.

A maximum-throughput dispatcher should:

1. Read actual namespace quotas/LimitRanges and all users' nonterminal pods.
   Interpret quota scopes and selectors; a priority-class ban is not global
   capacity. Terminating and Unknown/nonterminal pods still consume capacity.
   CPU, RAM, GPU and scheduling constraints may bind before Pod count does.
2. Hold one shared dispatch lock and account for reserved starts across local
   coordinators. Use fresh observations; fail closed on unknown identities or
   stale capacity. Do not impose an undisclosed total/per-design cap.
3. Take only eligible original work, preferring ready downstream phases when
   useful. Record reservations before create and native UIDs immediately after.
4. Probe the exact intended Pod shape. For a strict create workflow, first
   preflight before allocating a Job, create a suspended Job, bind its UID,
   recheck its owner-bound Pod admission and capacity, then unsuspend with UID
   tests. The server may reject even a suspend UPDATE during an account block.
5. Refill available slots as cases finish; do not wait for an entire batch wave
   if independent work is ready. Respect actual native admission/quota. The
   last dry-run success cannot authorize a later refused launch.
6. Explain finite tails: requested target, actual running/pending count,
   eligible remaining cases, holds and namespace capacity are separate numbers.
   Never create fake work, new seeds or duplicate completed runs to reach a target.

Small startup waves are a reasonable initial operating choice, not a fixed
cluster cap. If the owner requests saturation, remove hidden local throttles
within that authorized scope while preserving actual policy/admission checks.
Do not describe local startup exemptions as server grace periods.

## Startup pacing and low-utilization refusals

A Pod spends its first minutes pulling the image, staging inputs and reading
data, usually below the CPU band. One account (2026-10) got the refusal "Your
pods resources utilization is too low" after bursts of starts. In the 15 minutes
before each refusal, about a third to a half of its Pods were under 15 minutes
old and a quarter to a third were outside the bands. Hours without refusals had
at most about a sixth young. Each refusal blocked every new Pod for 1–4 hours,
which cost far more throughput than slower starts would have. This is one
account's correlation, not published policy.

Pacing that worked there, reported as a local rule:

- Cap the Pods still ramping (Pending, or young and not yet measured in band)
  at a share of the running Pods, with a floor and a ceiling. That study used
  25%, a floor of 8 and later 12, and a ceiling of 40. A young Pod already in
  band frees its slot. With a stale utilization snapshot, count every young Pod.
  `scripts/start_budget.py` computes this from `band_check.py --json` rows.
- Start long-lived work first. A Pod whose setup is a large share of its life
  (a short phase, or a step that reads gigabytes before computing) stays out of
  band for most of it. Batch very short phases, order candidates by expected
  lifetime, and give a workload with a long ramp its own smaller cap and spacing
  so it cannot fill the whole wave.
- Pods that start together mature together, so one wave can trip an aggregate
  rule such as "at most four Pods outside the bands". Stagger starts.
- A candidate that fails preparation for a reason that needs review leaves the
  candidate list until reviewed. Retrying it every cycle spends the start budget
  and starts nothing.

Pacing limits the start rate, never the total, and must not hide a lower target.
Measure the young and out-of-band shares before and after a change, and drop a
rule that does not prevent refusals.

## Guards that stop out-of-band Pods

A local guard that stops Pods outside the bands protects the account, but it can
destroy finished work. In one study (2026-10), a 24-hour audit of the guard's
own stops found that most hit productive Pods:

- Each step of a multi-step Pod starts a new process that reloads its data, so
  RAM starts low again at every step, not only at Pod start. A step whose RAM
  ramp outlasts the guard's startup window (there, 14–18 minutes against a
  15-minute window) is stopped just before it would enter the band. Protect a
  Pod whose CPU is in band while its RAM ramps, per step group, with a bound
  from native creation sized from measured ramps and from that workload's
  longest normal step (one design's clock-tree step ran up to 156 minutes
  below 20% RAM, so a one-hour window kept stopping it).
- A worker copying a finished step from node-local scratch to the PVC uses
  almost no CPU or RAM for one to five minutes, longer on a slow node. Before
  stopping a Pod, read its own event stream, and skip it while the last event
  is a successful step end or stage-out (that study needed 45 minutes of grace
  after one copy took over 11), or a step start a few minutes old (short
  bookkeeping steps run between copies). That study had destroyed 29 finished
  routing steps of 1.4–5 hours each in one day before adding this.
- A worker that streams a chatty tool's output straight to a CephFS file can
  stall the computation itself: the log writer blocks in uninterruptible I/O,
  the pipe fills and the tool's processes block writing to it, so CPU drops
  near zero and the guard stops the Pod. Write step output to node-local
  scratch and copy it once when the step ends. Inspect one stalled Pod
  (`/proc/<pid>/stat` state, `wchan`, `fd` targets) before tuning thresholds.
- Protected Pods that are still outside keep counting toward aggregate limits
  such as "at most four Pods outside". Many protected ramps at once keep the
  aggregate rule active, so it stops every unprotected straggler. Pace the
  starts of steps with long ramps so only a few ramp at once.
- Audit stops by phase and by each worker's last event (step start, step end,
  stage-out). A stop count alone hides what the stops cost.

## Auxiliary Pods next to a live workload

Rendering, export or analysis Pods that run while the main study is still
launching share its account and its local gates. One study (2026-10) hit three
different failures within eight hours by running render Pods beside its last
workers:

1. Named with the account's prefix but not the study's, the render Pods counted
   as "other workload" in the study's launch gate, which held recovery launches
   while three or more such Pods were starting or outside the bands. Render Pods
   kept that count at three, and recovery launches waited 18 minutes.
2. Renamed into the study's own prefix, the render Pods counted toward the
   study's guard instead. With three routing Pods in a slow memory ramp and
   another assistant's Pod already outside, they pushed the count past four.
   The guard can only stop study Pods, so it stopped a placement worker that
   was restoring its checkpoints (17 minutes lost).
3. Hidden from both, one large render Pod (10–12 GB request) still starting at
   1% memory was the fifth Pod outside the bands, beside three routing Pods in
   their memory ramp and one placement Pod. NRP refused a render launch. It
   then refused the study three times in the next 20 minutes, 1.5–3 minutes
   each, although the large render Pods were gone two minutes after the first
   refusal (NRP appears to measure over a time window). Two placement restarts
   started late.

What worked:

- While the main workload has unfinished launches, run auxiliary Pods only at
  the size NRP does not count (1 CPU and 2 GB) and only when they really fit.
  Measure each kind of work first: one render type peaked at 0.5–1.1 GB RSS and
  fit; another needed 7–12 GB and did not.
- Start auxiliary Pods that need more only after the main workload's last Pod
  has finished, or keep them inside the bands for their whole life, startup
  included. A Pod that spends its first minutes far below its request is out of
  band for those minutes.
- Exempt Pods are still refused while the account is over the limit. Their
  launches need the same dry-run check and back-off as the study's.
- Decide deliberately how the study's gate and guard see auxiliary Pods
  (name prefix, `user` label). Excluding them from local accounting is only
  safe when NRP also excludes them.
- Size auxiliary memory per item from a measured model when cost depends on the
  input (for example on a design's area), not from the smallest probe. Retry an
  OOMKilled item alone at the next size step.

## Admission and utilization diagnosis

Keep the raw native error, operation, context, namespace, Pod-spec hash and
timestamp. A failed Pod dry-run means no persisted Pod; a Job dry-run by itself
does not invoke the controller's future Pod create. API reads, exec and logs can
continue during a launch restriction. Current in-band CPU/RAM cannot prove that
historical account enforcement has cleared. Recheck the intended shape with a
bounded, modest interval; do not hammer the API, and do not promise a fixed
unblock time or call the user permanently banned without administrative evidence.

Metric errors are not zero utilization. Preserve unknown values, sample ages
and missing container data. The bundled band checker measures CPU/RAM only;
it does not measure GPU utilization or establish the admission verdict.
Use the user's existing remediation authorization and current evidence. An
instantaneously low but progressing job differs from a persistently idle or
stalled writer. Do not delete healthy work solely because an old block persists.

For stalled-I/O diagnosis, use bounded own-Pod stdout growth, process states,
wait channels and stage receipts. Repeated D-state processes waiting on Ceph
metadata with negligible progress are useful evidence; a single slow log sample
is insufficient. Age/poll thresholds are local policies and should be named as
such. Save evidence before stopping an authorized exact worker.

The violation count is per user account. Pods of other users in a shared
namespace count against their own accounts (the refusal names the account),
but they still use the namespace's quota.

## Metrics gaps and unhealthy nodes

An account may be unable to read Node objects. One got Forbidden at cluster
scope for `kubectl get node`. Forbidden is not "not found" and says nothing
about whether the node exists, so keep the raw error text. Judge a node from your
own Pods: their events, conditions, restarts and presence in the metrics API.

A Running Pod missing from several consecutive fresh metrics snapshots after
its startup window cannot be shown to be in band, and its node is often
unhealthy. With the owner's authorization, one study stopped such Pods after 3
snapshots (each under 3 minutes old) past a 15-minute startup window, held them
as infrastructure interruptions, and excluded the node for new Pods:

```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
      - matchExpressions:
        - {key: kubernetes.io/hostname, operator: NotIn, values: [bad-node.example.edu]}
```

Record each exclusion with its evidence and date, and review it later.
Exclusions are temporary facts about one period, not universal defaults. A node
lost under a running Pod (eviction, node failure, the Pod vanishing) is an
infrastructure outcome, never an application failure. Recover only from that
attempt's verified checkpoints, after proving its writer is gone.

The Pod's own events still name its node after the Pod is gone, until they
expire (the Kubernetes default is one hour): `kubectl get events
--field-selector involvedObject.name=<pod> -o json`, field `source.host` of
the kubelet's events. Save them as soon as a Job fails without a Pod.

Node symptoms one account met in 2026-10, each handled by requeueing the exact
attempt from its verified receipts and excluding the node for new Pods:

| Symptom | Visible evidence |
|---|---|
| Node NotReady, or a NoExecute taint | NodeNotReady / TaintManagerEviction events; Pod deleted; Job Failed (BackoffLimitExceeded) |
| Kubelet stops running Pods with no stated cause | Only "Killing: Stopping container"; no taint, eviction or preemption event. One node stopped three Pods in the same second, one of them another user's; another stopped two |
| Pods vanish with no event at all | Six Pods on one node gone in the same second; Jobs Failed without a Pod |
| Pods on a lost node stuck Terminating | DeletionByTaintManager; two never-started Pods stuck 28 hours until deleted by exact UID |
| Image pull never finishes | ContainerCreating "Pulling image ..." for 50 minutes; the Pod never started |
| Container restarted under `restartPolicy: Never` | restartCount 1 with no recorded exit |
| Running Pod missing from the metrics API | podmetrics NotFound for 20+ minutes, which blinds band checks and guards |
| No `memory.oom.group` | OOM kills one process and looks like a step failure (see above) |

Exclusions that month included nodes named `pas.*` (internet2 PoPs),
`k8s-haosu-*`, `k8s-chase-ci-*` and `hcc-*` (UNL), and single hosts at other
sites. Those are dated observations to check against new evidence, not a
standing deny-list. Read the attempt's own receipts (through a Pod of yours,
small files only) to find where the retry resumes.

## Separate transport, worker and application outcomes

Track at least the following states per case/phase, rather than one global
design hold:

| State | Interpretation |
|---|---|
| Planned / queued | No accepted attempt has started |
| Active | Exact native Job/Pod identities are being observed |
| Application complete | Requested endpoint and case receipts verified |
| Observed application failure | Real scientific/build/test outcome, not an infrastructure guess |
| Infrastructure held | Node loss, eviction, transport or bootstrap interruption under review |
| Resources held | Native OOMKilled or evidenced resource-policy interruption |
| Collection held | Required Pod, stdout or artifacts unavailable; no outcome inferred |
| Cancelled by owner | Unfinished work excluded durably, including after restart |

A harness can intentionally exit zero after recording failures for some cases.
Conversely, a missing terminal Pod does not establish scientific failure. Keep
case and phase IDs, source/config/runtime hashes, requested endpoint, Job UID,
Pod UID, restart count, container exit/termination reason and stage receipts.
Bind stdout to an exact Pod before and after reading it; cached or truncated
stdout is not a substitute for missing receipt evidence. If stdout cannot be
verified, retain it as unverified and hold only the affected cases.

Only native Complete/Failed conditions end a Job watcher. Suspended and
FailureTarget are not terminal completion. Kubernetes may start duplicate
workers even for nominally single-Pod Jobs, so claims/output commits must tolerate
that possibility. Choose backoff and pod-failure policies to match the retry
contract; do not assume an automatic replacement preserves scientific meaning.

Preserve verified successes and failures when a design/arm is cancelled.
Record a separate durable cancellation map for unfinished cases and exclude it
in selection, restart and terminal accounting. Retain the original planned
inventory, report the cancelled subset, and never claim every planned run ran.

A hold is a queue state, not an endpoint. Report holds by reason with counts,
and give each reason a resolution: evidence to collect, or an owner decision.
When the owner releases held work, apply each resolution idempotently, only to
the exact attempt its evidence describes (same Job UID, same status), and record
what changed. Resolutions one study used:

| Hold | Resolution |
|---|---|
| Parent Pod identity missing | Recover it from snapshots or events; the worker still verifies receipts |
| Writer lost with its node; Job Failed, no active Pod | Owner accepts the loss; resume from the last verified checkpoint |
| Checkpoint fails integrity | Restart that phase from its own empty attempt folder |
| Submission recorded but the Job was never created | Restore the previous attempt from history |

## Changing a step limit mid-study

A time or memory limit is part of the experiment's conditions. If one proves too
short for a class of cases (for example a placement step killed at 12 hours),
raise it only together with a rerun of every case that hit the old limit. Bind
the authorization to the exact case list and the old results' hashes. Move the
old results to a superseded record instead of deleting them, canary one case
before releasing the rest, and report how many outcomes come from each limit.
Never mix outcomes produced under different limits silently. Raise any guard
that would stop a productive step early (an idle or ramp window) to match the
new limit.

## Step-limit kills, late output and memory livelock

`timeout --signal=TERM --kill-after=60s <limit> make ...` signals the command's
whole process group but returns as soon as its direct child exits. A grandchild
shell can still be running then: ORFS's `flow.sh` runs each tool in a subshell
with an EXIT trap, and that shell appends "Terminated" to the step's output
file after `timeout` has returned. A worker that checks the published copy
against the size it measured before copying then sees a mismatch. If it raises
before writing the step's receipt, the coordinator sees a hold, not a timeout,
and can rerun the whole step from zero with a fresh limit. One study had a
12-hour global-routing step rerun from zero this way. With the real flow
scripts, 11 of 12 local timeout kills appended the line late.

- Treat a step that reached its own limit as that step's outcome even when the
  following copy fails. Write the receipt first, or let the coordinator convert
  exactly that hold (start time plus limit matches, no later step started).
- When verifying a copy of a log that may still grow, compare the bytes you
  copied, or wait for the writer group to exit.

A step can also stall at its memory limit without the kernel ever invoking the
OOM killer: anonymous memory at the limit, almost no file cache, high
`memory.pressure` ("full") and a silent log for hours. It then holds its
resources until its time limit. With `memory.oom.group` set to 1, a real OOM
kills the whole container (OOMKilled) and a memory-escalation retry can start.
Decide in advance whether to wait for the time limit or to record the run
early. An exec for diagnosis allocates memory and can itself trigger the OOM.

Check how OOMs surface on each node. On cgroup v2 nodes with
`memory.oom.group` = 1 (all 26 nodes one study checked), the container dies
OOMKilled and the coordinator sees a resource outcome. On a node without it
(one node there had no cgroup v2 memory files at all, so probably cgroup v1),
the kernel kills only the largest process: the tool dies, the worker survives
and records an ordinary step failure. Record the cgroup version and
`memory.oom.group` in each step receipt, treat a step failure without them as
possibly an OOM, and exclude such nodes before lowering memory requests.

## Stopping exact authorized work

Save fresh native Job/Pod/spec/UID/stdout evidence and mark the queue held or
cancelled first. Prevent the Job controller from replacing a stopped Pod.
A UID-tested suspend is one option; when actual utilization refusal rejects
that UPDATE, an authorized exact-UID Job DELETE with Orphan propagation followed
by exact-UID Pod DELETE can stop the writer without replacement. Confirm the
controller is gone/deleting before stopping its Pod. Ordinary permission,
network, UID or spec errors do not justify a destructive fallback.

Do not force-delete an uninterruptible writer, bulk-delete a namespace, stop
another assistant's controller or reuse a name after an unreviewed UID change.
Keep normal termination evidence and confirm quiescence before moving files.

## Storage and interrupted work

CephFS metadata operations can stall writers and make otherwise busy workloads
look idle. Do not run recursive du/tar/cp/rsync across live run trees, including
from a helper with a shared mount. Native API and own-Pod stdout are the default
progress sources. Existing healthy helpers must have enough memory/headroom
for the actual inspection; never assume an old Pod name is still running.

Before recovery, prove there is no surviving controller/Pod/child writer for
the exact case/phase, including terminating or orphaned writers. A stale claim
alone is not proof. Inspect only its known closed prefix and exact receipts:

- Preserve valid completed phases and observed application failures. A case
  with missing collection evidence is not automatically unfinished.
- Archive an unfinished attempt's entire owned state/output/log/report prefix
  into a fresh, non-overwriting archive on the same filesystem. Prefer atomic
  renames over recursive copies. Preserve canonical per-case measurements and
  lineage too; record absent prefixes for failures before bootstrap.
- Keep source and seed unchanged for an infrastructure reexecution allowed by
  the existing retry plan. Give it a fresh native Job/attempt identity and a
  parent/archive reference. Count only one final observation per planned case.
- For a verified predecessor and an unstarted successor, preserve predecessor
  files in place and release only that successor. In a partially interrupted
  batch, release only reviewed case IDs; retain original batch membership and
  native identity in history.
- Metadata can be slow. Use small, independently journalled case units and
  bounded concurrency over disjoint, quiescent prefixes. A timed-out exec client
  does not prove its remote command stopped. Reconcile exact remote writers
  before retrying an archive operation; preserve partial journals and detect
  source/destination collisions instead of overwriting or deleting either.

**Cross-client filesystem identity:** st_dev is local to a mount/node. For a
rename, compare device and inode before/after within the same client. Across
nodes, first verify the same native PVC UID/backing volume; compare stable
filesystem file IDs/inodes where supported, or use content/manifests as needed.
Do not reject a preserved Ceph inode solely because another client's st_dev is
different, and do not assume inode numbers identify files across different PVCs.

## Exporting artifacts through Pod stdout

When results must leave the cluster but other Pods' trees must not be read,
have a finite Pod write its outputs to its own stdout and read them back with
`kubectl logs` after it finishes. `scripts/stdout_artifacts.py` implements the
protocol (`Emitter` in the Pod, `collect` on the host);
`examples/stdout_export.sh` does the same with bash, gzip and coreutils on a
stock image.

- Keep each Pod's export well under the kubelet's container-log rotation size
  (often 10 MiB). `kubectl logs` returns only the current log file, so data
  written before a rotation is lost. One study used a 7 MB base64 budget and
  marked anything past it "stored" for a follow-up Pod.
- Write base64 in short lines (about 12 KB) tagged with the file's SHA-256 and a
  chunk index, then one JSON event with the hash, size and chunk count. Keep a
  file only if every chunk is present and the hash matches.
- Exactly one process may write these lines. Worker processes return paths and
  the parent emits them: concurrent writes larger than PIPE_BUF interleave in
  the middle of lines.
- Split files larger than one Pod's budget into fixed-size parts of a
  deterministic encoding (`gzip -9 -n` stores no name or timestamp), so parts
  from different Pods join. Check the whole file's hash after joining.
- A finished Pod keeps its log until the Job's TTL removes it. Deleting a Job
  deletes its Pods and their logs, so read a live Pod's log before stopping it
  to keep the items it already finished.
- If batch names are hashes of their contents, a retry of exactly the same items
  gets the old name and is skipped as already launched. Add a retry counter to
  the hash.
- Record which checkpoint each artifact came from and its SHA-256. Check it
  against the hash the run committed when one exists; say "unverified" when it
  does not, rather than leaving the field out.

## Node-local scratch for CephFS-heavy steps

When a step reads or writes many files on a CephFS PVC, run it on node-local
scratch (an emptyDir) and stage data in and out. In one EDA study this cut task
start to step start from 3–14 minutes to under one minute, and Pods reached the
bands within about 6 minutes. `examples/scratch_stage.py` shows the pattern.

- Stage in only the step's inputs and verify each copy's SHA-256, against a
  committed hash when one exists. Cache verified hashes keyed by device, inode,
  size, mtime and ctime; a changed key only costs a re-hash.
- Stage out each new or changed file under a private temporary name on the PVC:
  fsync it, rename it into place, fsync the directory, then re-read it with the
  page cache dropped and compare hashes. Write the step's done marker last, so a
  crash never leaves a marker for unverified outputs.
- Request ephemeral storage sized to the staged data, with a limit that has
  headroom. If the namespace LimitRange sets no default, the request is 0: the
  scheduler ignores local disk and the Pod is among the first evicted under disk
  pressure. Exceeding the limit also evicts the Pod.
- A staging, copy or verification error, a full scratch disk or an
  ephemeral-storage eviction is a retryable infrastructure or resource hold.
  A kill at the step's own time limit is still that step's outcome.
- Drop cache for staged files (posix_fadvise DONTNEED) and size memory from the
  application's RSS; see Resource sizing.
- Smoke-test the new worker on a few real cases before switching the queue to
  it. Include the adoption of a scratch commit by a later phase and a crash
  between stage-out and the marker.

## Pod identities

Record each Pod's name and UID as soon as it exists, and keep periodic snapshots
of your own Pods (name, UID, owning Job UID). Events expire (default TTL one
hour). The Job controller names Pods from "<job>-" cut to 58 characters plus 5
random characters. Keep Job names to 57 characters or fewer, and map Pods to
Jobs by owner UID or the `batch.kubernetes.io/job-name` label, never by
stripping the suffix. `scripts/pod_identity.py` recovers identities from saved
events or snapshots. A recovered name is a candidate until the checkpoint's own
receipts confirm it.

## Host coordination and handoff

Use one persistent host coordinator, an atomic local ledger and a lock.
A watchdog can check PID plus command identity, heartbeat/native-observation
ages, pending holds and endpoint progress. Unexpected-exit restarts must check
the same lock and frozen inputs, have a bounded restart rate and honor explicit
stops, cancellations and the scientific endpoint. A watchdog restart is not
permission to restart a scientific attempt. Host supervision needs no idle
Nautilus Pod and no outbound chat/email messages.

Change a live coordinator by version, not by editing it. Each behaviour change
is a new module that imports the previous one, with a test suite that inherits
the previous suite and replaces only the tests the change makes obsolete. Roll
out by stopping the old process gracefully while holding the queue lock,
archiving its ledger byte for byte, and starting the new version against a
freeze file that pins every input's SHA-256. Check the new version's first
native observation and first launch round before leaving it.

Record current launch paths/PIDs, runtime hashes, queue state, proof directories,
cancellation map and preservation rules in the project's shared and relevant
assistant memories. Preserve older entries and mark old observations historical.
Do not copy personal workload names, temporary node failures, fixed pod counts
or study-specific seed ranges into universal defaults.

Primary references: [NRP policy](https://nrp.ai/documentation/userdocs/start/policies/),
[Kubernetes Jobs](https://kubernetes.io/docs/concepts/workloads/controllers/job/),
[API dry-run and conditional changes](https://kubernetes.io/docs/reference/using-api/api-concepts/).
