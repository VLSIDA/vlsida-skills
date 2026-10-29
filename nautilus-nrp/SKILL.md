---
name: nautilus-nrp
description: Help create and manage Kubernetes jobs, pods, and persistent storage on the Nautilus NRP research cluster. Includes templates for jobs, interactive pods, and PVC-based persistent storage.
user_invocable: true
---

You help the user create and manage workloads on the [National Research Platform (NRP) Nautilus](https://nrp.ai/) Kubernetes cluster.

## Overview

Nautilus is a shared, NSF-funded Kubernetes cluster for research. Users get a namespace and can run batch Jobs, interactive Pods, and use persistent storage. Access is via `kubectl` after registering at the NRP portal.

## Cluster Policies — HARD LIMITS, read before writing any manifest

Nautilus is shared and NSF-funded; these are enforced, not advisory. Violating
them gets workloads deleted and repeat offenders banned. Source:
https://nrp.ai/documentation/userdocs/start/policies/

### What gets you banned

> *"Users running a Job with sleep command or equivalent ... will be banned"*

Enforcement is **utilization-based**, not intent-based. A pod is in violation
outside these bands, and **more than 4 violating pods** puts the account at risk:

| resource | required utilization vs. request |
|---|---|
| CPU | **20–200%** |
| memory | **20–150%** |
| GPU | **above 40%** (aim near 100%) |

### Lifetimes and purging

| thing | limit |
|---|---|
| interactive pod | destroyed at **6 hours** |
| long-running deployment | deleted at **2 weeks** unless allow-listed |
| storage volume | purged after **6 months** unaccessed, without notice |
| interactive pod cap | **2 GPUs / 32 GB RAM / 16 CPU cores** |
| A100 quota | **zero by default** for all namespaces — must be requested |

You get **3 notifications** before a workload is deleted.

### Requests and limits

- **`limits` must be within 20% of `requests`.** Not 2x. For >~100 pods/jobs,
  policy is **`limit == request`**.
- **Request what you will actually use.** Over-requesting is the usual way to
  fall below the 20% CPU floor.
- GPU: `nvidia.com/gpu: N` must be **equal** in requests and limits.

### The shape that is always safe

**Batch Jobs that run to completion.** They finish and exit, so they never
accumulate idle time and never meet the 6h / 2-week reapers. Prefer **many small
Jobs over few fat pods**: throughput is bound by the namespace pod quota, not by
per-pod width, and small honest pods keep utilization high.

### Watch out: multi-phase workloads — split phases that differ in parallelism or memory

Any job whose resource profile **shifts across phases** is a util-floor hazard: NRP measures
utilization against your *request*, and a single request can only match one phase. The
disparity shows up on either axis:

- **CPU** — a job that fans out to N workers and then finishes on **one** thread (bottom-up
  solve → single top-level pass, common in EDA/annealing flows): request N cores and the
  serial tail runs at ~`1/N` util, dragging the average under the 20% CPU floor.
- **Memory** — a brief high-memory phase inside a long low-memory run: request the peak and
  the long cheap phase sits far under it.
- Often **both at once**, and the phases can be *dynamic* (data-dependent: which phase is
  heavy, and how heavy, varies per input).

When the heavy and light work are interleaved inside **one process**, you can only
`size to average, not peak` (CPU under-request merely throttles; memory under-request risks
OOM, so leave headroom). But when the phases are **separable stages**, the robust fix is to
**split at the phase boundary into separate Jobs**, each sized to its own phase, passing
intermediate state through a PVC (checkpoint at the end of stage 1, restore at the start of
stage 2). Each Job then has a *flat* profile that matches its request, so both CPU and memory
stay in-band — and the heavy stage can run at higher parallelism than you'd dare request for
the whole job. Give the stages distinct Job names but a shared key (e.g. a `-stage1`/`-stage2`
suffix on the name, same label) so the checkpoint lines up. If a stage is **non-deterministic
across resource sizes**, verify that splitting reproduces the single-run result before relying
on it (it often does — e.g. thread count rarely changes the output — but confirm). A pod at
**≤1 CPU / 2 GB is exempt** from the util rules, so a genuinely tiny screen stage can bypass
the floor entirely.

**Worked example — OpenROAD RTL-to-GDS (OpenROAD-flow-scripts / ORFS, OpenLane):** the memory case.
**Detailed routing** briefly spikes to tens of GB and is highly multi-threaded, while
**synthesis, floorplan, placement, CTS, and global route** dominate wall-clock at a few GB and
are largely single-threaded. One whole-flow Job sized for the route peak (e.g. 32 GB) sinks
under the 20% memory floor across the long synth/place tail and flags the account. Split it:

| stage | make range | resources | why |
|---|---|---|---|
| **GRT screen** | `synth .. globalroute` | ~2 CPU, a few GB, 2 threads | light + partly single-threaded; checkpoint the post-GRT working dir to a PVC |
| **DRT confirm** | `globalroute .. finish` (restore ckpt) | **wide: 8 CPU, route-peak GB, 8 threads** | detailed route is memory-heavy *and* parallel → both CPU and memory util stay in-band because there is no low-use tail |

### Before sizing any sweep

```bash
kubectl describe quota -n <namespace>      # actual ceilings
kubectl get pods -n <namespace> -o wide    # what is already running
```

## Prerequisites

- An NRP account — register and log in at **https://nrp.ai** via CILogon
- A namespace allocated to the user's research group
- `kubectl` **and** the `kubelogin` OIDC plugin installed (see below)
- `~/.kube/config` in place (see below)

> The portal moved to **https://nrp.ai**. The old `portal.nrp-nautilus.io` and
> `docs.nrp-nautilus.io` hosts are superseded; docs now live at
> https://nrp.ai/documentation/.

### Getting cluster access

**There is no per-user kubeconfig and no "download config" button in the portal.**
`https://nrp.ai/config` is a single **public** file, identical for every user. It
carries only the cluster endpoint, the CA cert, and an `exec` block; your identity
comes from the OIDC browser flow at first use, not from the file. Don't go hunting
the portal UI for a personalised download — there isn't one.

```bash
# 1. kubectl
curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
install -m 0755 kubectl ~/.local/bin/kubectl

# 2. kubelogin -- REQUIRED. Without it the kubeconfig does not work at all.
#    kubectl invokes it as a credential plugin, so it MUST be on PATH under
#    the name `kubectl-oidc_login` (install under both names to be safe).
#    https://github.com/int128/kubelogin
unzip kubelogin_linux_amd64.zip
install -m 0755 kubelogin ~/.local/bin/kubelogin
install -m 0755 kubelogin ~/.local/bin/kubectl-oidc_login

# 3. the shared config
mkdir -p ~/.kube && chmod 700 ~/.kube
curl -o ~/.kube/config -fsSL "https://nrp.ai/config"

# 4. verify -- first command triggers the CILogon browser flow, then caches a token
kubectl config get-contexts          # expect context "nautilus"
kubectl get pods -n <namespace>      # "No resources found" == working, empty namespace
```

**Shared-host warning.** The stock config sets
`--listen-address=0.0.0.0:8000` for the OIDC callback, which binds *all*
interfaces. On a multi-user login node, change it to `127.0.0.1:8000` (and
SSH-forward that port if the browser is elsewhere) so another user on the box
cannot intercept the authorization code.

See [NRP documentation](https://nrp.ai/documentation/) for the rest.

## Example Templates

This skill includes example scripts and templates in `~/.claude/skills/nautilus-nrp/examples/`:

- **`job-template.yaml`** — Batch Job template (from HighTide project)
- **`run.sh`** — Job submission/management script (from HighTide project)
- **`interactive-pod.yaml`** — Template for an interactive development pod
- **`pvc-template.yaml`** — PersistentVolumeClaim template for shared storage
- **`monitor-job.sh`** — Stream milestones from a running Job into the Claude Code `Monitor` tool (see below)

When the user asks you to create K8s manifests for Nautilus, use these as starting points and adapt them to the user's needs.

## Monitoring Long-Running Jobs with the Monitor Tool

Nautilus batch jobs often run for 30+ minutes (long builds, training runs, RTL-to-GDSII flows). Polling with `kubectl logs -f` ties up the conversation; a one-shot `kubectl wait` hides progress. The Claude Code `Monitor` tool is the right fit: you arm it once with a watcher script, and each emitted line becomes a chat notification while you keep working.

`examples/monitor-job.sh` is a ready-made watcher. Key properties:

- Emits on pod **phase changes** (`Pending` → `Running` → terminal).
- Emits on **stage milestones** matched by a caller-supplied regex, de-duplicated so the same line isn't spammed.
- Emits on **terminal job condition** (`Complete` / `Failed`) with a tail of the last 40 log lines, then exits — this is the hand-off back to Claude.
- Tolerant of transient `kubectl` failures (no `set -e`, `|| true`-style fallbacks via `2>/dev/null`).

### Typical invocation (inline Monitor call)

Don't try to make the script fit every workflow — copy its body into a Monitor call and tune `PATTERN` to the stages/errors you actually care about for that job. Example for a multi-stage hardware build:

```bash
Monitor(
  description="coralnpu k8s job milestones",
  timeout_ms=3600000,
  persistent=false,
  command="""
set +e
JOB=$CRUZID-hightide-asap7-coralnpu
NS=vlsida
PATTERN='synth|floorplan|place|cts|route|final|ERROR|FAILED|Traceback|Killed|OOM|Aborted|INFO: Build completed|Elapsed time'
# ... body of examples/monitor-job.sh ...
"""
)
```

### Guidance when arming the watcher

- **Cover the failure tail, not just success.** Include `ERROR|FAILED|Traceback|Killed|OOM|Aborted` in the regex. A filter that only matches the happy-path milestones stays silent through a crashloop.
- **Sleep interval.** Default 60s is right for long jobs on a shared cluster — tighter polling wastes kube-apiserver calls and emits redundant "still running" events. Drop to 10–15s only if you genuinely need fine-grained progress.
- **Timeout.** Monitor tops out at 1h. For longer runs, let it time out, check job state with `kubectl get job ... -o jsonpath='{.status.conditions[*]}'`, and re-arm. This is normal.
- **Pod label.** The script selects pods via `-l job-name=$JOB`. If you use a different selector (e.g., `app=hightide,design=X`), update the `kubectl get pod` line.
- **Never `tail -f` raw logs into Monitor.** Every stdout line becomes a notification — unfiltered logs will auto-stop the monitor for emitting too much. Always grep.

## Key Nautilus Concepts

### Naming Convention
**All Jobs and Pods must be named with the user's CruzID as a prefix** (e.g., `jdoe-build-sram`, `jdoe-train-run-3`). The cluster is shared, so the prefix is how anyone — including the user — can tell at a glance who owns a running workload. If you don't know the user's CruzID, ask before creating the manifest. Also set a `user: <cruzid>` label on the resource for label-based filtering (`kubectl get jobs -l user=<cruzid>`).

### Resource Requests
Nautilus is a shared cluster. Always set both `requests` and `limits`:
- **Keep `limits` within 20% of `requests`** — cluster policy, not a suggestion.
  (An earlier version of this skill said "~2x requests for burst capacity";
  that violates policy. For >~100 pods/jobs, policy is `limit == request`.)
- **Requests must be honest, or you get flagged.** Enforcement is utilization-
  based: CPU must run at 20–200% of requested, memory at 20–150%, GPU above 40%.
  More than 4 pods outside those bands puts the account at risk. Requesting 16
  cores for a workload that is single-threaded most of the time is the common
  way to trip this.
- Be conservative — the scheduler is cluster-wide and over-requesting blocks others
- GPU requests: use `nvidia.com/gpu: N` in both requests and limits (must be equal)

### Namespaces
All resources must target the user's namespace. Use `-n <namespace>` on every `kubectl` command, or set a default:
```bash
kubectl config set-context --current --namespace=<namespace>
```

### Node Affinity (Optional)
Nautilus spans many sites. To target specific hardware or locations, use node selectors or affinity rules:
```yaml
nodeSelector:
  nvidia.com/gpu.product: "NVIDIA-A100-SXM4-80GB"
```

### Job Best Practices on Nautilus

**Lifetimes and purging (policy).** Interactive pods are destroyed after
**6 hours**; long-running deployments are deleted after **2 weeks** unless
allow-listed. You get **3 notifications** before deletion. Storage volumes not
accessed for **6 months** may be purged without notice. Interactive pods are
capped at **2 GPUs / 32 GB RAM / 16 CPU cores**.

Batch **Jobs that run to completion are the safe shape** — they finish and exit,
so they never accumulate idle time and never hit the 6h/2w reapers.

- **Do NOT force one-pod-per-node** (`podAntiAffinity` on `kubernetes.io/hostname`) unless a job
  genuinely needs a whole node — it strands the node's other cores (CPU-only NRP nodes have
  44–380 cores; an 8-core pod would waste the rest). Let the scheduler bin-pack multiple pods per
  node up to capacity; throughput is then bound by the namespace pod quota, not 1-per-node. Keep
  resource *requests* honest so the scheduler packs safely.
- **Never use an idle `sleep` "parking" pod** (e.g. a busybox reader that just
  mounts a PVC and sleeps). Policy is explicit: *"users running a Job with sleep
  command or equivalent ... will be banned"*, and NRP's admission webhook rejects
  it up front: *"pods resources utilization is too low"*. To read
  a shared PVC, instead `kubectl exec`/`kubectl cp` through an **already-running workload pod** that
  mounts the same PVC, or run a **short Job that does real work and exits** (e.g. tar the results to
  stdout). Idle low-usage pods get blocked; working pods don't.
- Set `ttlSecondsAfterFinished` to auto-cleanup completed jobs (e.g., 3600 for 1 hour)
- Set `backoffLimit` to control retries (1-2 is typical)
- Use `restartPolicy: Never` for jobs
- Use init containers for repo cloning or setup steps
- Label everything (`app`, `project`, `user`) for easy bulk management

## Container Images: the NRP GitLab registry

Every time a pod starts it **pulls its container image from a registry**, so your image must live somewhere the cluster can reach. NRP hosts its own GitLab with an integrated **container registry** at `gitlab-registry.nrp-nautilus.io` — it's free for NRP users, pulls fast from inside the cluster, and keeps private images off Docker Hub (whose pull-rate limits bite hard on a shared cluster where hundreds of pods pull at once). **This is the recommended place to store images for Nautilus.**

### One-time setup
1. Sign in to the NRP GitLab at **https://gitlab.nrp-nautilus.io** (same NRP credentials).
2. Create a project (e.g. `myproject`). Your image path is then:
   ```
   gitlab-registry.nrp-nautilus.io/<gitlab-username-or-group>/<project>[:tag]
   ```
   e.g. `gitlab-registry.nrp-nautilus.io/<cruzid>/orfs-fork:latest`.
3. Create an access token so `docker` (push) and the cluster (pull) can authenticate — a private registry needs auth for **both**:
   - **Project → Settings → Repository → Deploy tokens** is cleanest (scoped to one project, revocable independently of your account). For least privilege create **two**: one with `write_registry` (push from your workstation) and one with only `read_registry` (the cluster's pull secret).
   - Or a **personal access token** with `read_registry` + `write_registry` scopes (works across all your projects).

### Push an image
```bash
docker login gitlab-registry.nrp-nautilus.io        # username + token (from above)

IMG=gitlab-registry.nrp-nautilus.io/<user>/<project>:latest
docker build -t "$IMG" .
docker push "$IMG"
```
Tip — avoid shipping your whole working tree as build context by **streaming a minimal context** to `docker build`:
```bash
tar cz --exclude=.git --exclude='*/results' Dockerfile src/ | docker build -f Dockerfile -t "$IMG" -
```

### Let cluster jobs pull a PRIVATE image
Pods can't use your workstation's `docker login` — they authenticate via an **imagePullSecret** in the namespace. Create a `docker-registry` secret from a **read** token:
```bash
kubectl create secret docker-registry nrp-gitlab-pull \
  --docker-server=gitlab-registry.nrp-nautilus.io \
  --docker-username=<read-token-username> \
  --docker-password=<read-token> \
  -n <namespace>
```
Then reference it in every Job/Pod spec (alongside the image):
```yaml
spec:
  imagePullSecrets:
  - name: nrp-gitlab-pull
  containers:
  - name: worker
    image: gitlab-registry.nrp-nautilus.io/<user>/<project>:latest
```
(A **public** project's registry needs no secret — but private is the default and the safer choice.)

### Tips
- **Give the cluster a read-only token.** It only needs to pull; never put a `write_registry` credential in the pull secret.
- **`imagePullPolicy: Always` when you reuse a tag.** K8s caches by tag, so if you keep pushing to `:latest`, pods on a warm node may run a stale image. Either set `imagePullPolicy: Always` or push a **unique tag per build** (e.g. a git SHA).
- **Keep images lean.** Every pod pull moves the whole image over the network; a fat image slows every cold start, and pulls count toward pod-startup time under the namespace pod quota. Multi-stage builds + stripping build tools help a lot.
- **Secrets are per-namespace.** If you run in multiple namespaces, create the pull secret in each.

## Persistent Storage on Nautilus

Nautilus provides **CephFS**-backed persistent storage via PersistentVolumeClaims (PVCs). This is the recommended way to keep data across job runs.

### Creating a PVC
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-project-data
  namespace: <namespace>
spec:
  storageClassName: rook-cephfs   # CephFS for shared/multi-read-write
  accessModes:
    - ReadWriteMany               # Multiple pods can mount simultaneously
  resources:
    requests:
      storage: 100Gi
```

Key storage classes on Nautilus:
| StorageClass | Backend | Access Modes | Use Case |
|---|---|---|---|
| `rook-cephfs` | CephFS | ReadWriteMany | Shared data, multi-pod access, home dirs |
| `rook-ceph-block` | Ceph RBD | ReadWriteOnce | Single-pod databases, high-IOPS workloads |

### Mounting a PVC in a Pod/Job
```yaml
containers:
- name: worker
  volumeMounts:
  - name: data
    mountPath: /data
volumes:
- name: data
  persistentVolumeClaim:
    claimName: my-project-data
```

### Persistent Storage Tips
1. **Use `rook-cephfs` with `ReadWriteMany`** for most research workloads — it lets multiple pods (or jobs) share the same data simultaneously.
2. **Don't store ephemeral build artifacts on PVCs** — use `emptyDir` volumes for scratch space that doesn't need to persist.
3. **Pre-populate data with a one-off pod**: Create a simple pod that mounts the PVC, download/copy your dataset, then delete the pod.
4. **Size generously** — CephFS quotas are soft on Nautilus, but request what you expect to use.
5. **Back up important data externally** — PVCs are durable but not backed up. Use `gsutil`, `rclone`, or `rsync` to keep copies elsewhere.
6. **Use subPath** to share one PVC across multiple purposes:
   ```yaml
   volumeMounts:
   - name: data
     mountPath: /datasets
     subPath: datasets
   - name: data
     mountPath: /results
     subPath: results
   ```

### Other Storage Options
- **GCS / S3 buckets**: Upload results to cloud storage from within jobs (as the HighTide example does with `gcloud storage rsync`). Good for sharing across clusters or with external collaborators.
- **ConfigMaps / Secrets**: For small config files or credentials (< 1 MiB).
- **hostPath**: Avoid on Nautilus — pods can land on any node.

## Common Workflows

### Submit a batch job
```bash
kubectl apply -n <namespace> -f job.yaml
```

### Monitor jobs
```bash
kubectl get jobs -n <namespace>
kubectl get pods -n <namespace>
kubectl logs -f job/<job-name> -n <namespace>
```

### Start an interactive session
```bash
kubectl apply -n <namespace> -f interactive-pod.yaml
kubectl exec -it -n <namespace> <pod-name> -- /bin/bash
```

### Clean up
```bash
# Delete specific job
kubectl delete job <job-name> -n <namespace>

# Delete all jobs with a label
kubectl delete jobs -n <namespace> -l app=myproject

# Delete completed jobs
kubectl delete jobs -n <namespace> --field-selector status.successful=1
```

### Check PVC usage
```bash
kubectl get pvc -n <namespace>
kubectl exec -n <namespace> <pod-name> -- df -h /data
```

## Adapting the HighTide Example

The `examples/run.sh` and `examples/job-template.yaml` show a production pattern for batch job submission:
- Templated YAML with placeholder substitution
- Label-based job management (status, delete by filter)
- Init container for repo cloning
- Secret mounting for credentials
- Remote cache integration

When creating new job scripts, adapt this pattern to the user's specific project, replacing the HighTide-specific parts (repo URL, Bazel build commands, GCS cache) with the user's build system and workflow.
