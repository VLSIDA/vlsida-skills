---
name: nautilus-nrp
description: Help create and manage Kubernetes jobs, pods, and persistent storage on the Nautilus NRP research cluster. Includes templates for jobs, interactive pods, and PVC-based persistent storage.
user_invocable: true
---

You help the user create and manage workloads on the [National Research Platform (NRP) Nautilus](https://nationalresearchplatform.org/nautilus/) Kubernetes cluster.

## Overview

Nautilus is a shared, NSF-funded Kubernetes cluster for research. Users get a namespace and can run batch Jobs, interactive Pods, and use persistent storage. Access is via `kubectl` after registering at the NRP portal.

## Prerequisites

- `kubectl` configured with Nautilus cluster access
- A namespace allocated to the user's research group
- NRP portal account: https://portal.nrp-nautilus.io/

See [NRP Nautilus docs](https://docs.nrp-nautilus.io/) for initial setup.

## Example Templates

This skill includes example scripts and templates in `~/.claude/skills/nautilus-nrp/examples/`:

- **`job-template.yaml`** — Batch Job template (from HighTide project)
- **`run.sh`** — Job submission/management script (from HighTide project)
- **`interactive-pod.yaml`** — Template for an interactive development pod
- **`pvc-template.yaml`** — PersistentVolumeClaim template for shared storage

When the user asks you to create K8s manifests for Nautilus, use these as starting points and adapt them to the user's needs.

## Key Nautilus Concepts

### Resource Requests
Nautilus is a shared cluster. Always set both `requests` and `limits`:
- Set limits to ~2x requests for burst capacity
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
- Set `ttlSecondsAfterFinished` to auto-cleanup completed jobs (e.g., 3600 for 1 hour)
- Set `backoffLimit` to control retries (1-2 is typical)
- Use `restartPolicy: Never` for jobs
- Use init containers for repo cloning or setup steps
- Label everything (`app`, `project`, `user`) for easy bulk management

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
