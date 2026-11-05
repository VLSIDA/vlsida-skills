# Access, images and storage

## Prerequisites

- An NRP account — register and log in at **https://nrp.ai** via CILogon
- A namespace allocated to the user's research group
- `kubectl` **and** the `kubelogin` OIDC plugin installed (see below)
- `~/.kube/config` in place (see below)

## Lifecycle and resource policies

Recheck the [current cluster policies](https://nrp.ai/documentation/userdocs/start/policies/)
before provisioning. Published limits checked 2026-10-29:

| Resource | Policy |
|---|---|
| Interactive Pod without a controller | Six-hour lifetime; at most 2 GPUs, 32 GB RAM and 16 CPU cores |
| Long-running idle Deployment | Minimal requests, no GPU; deleted after two weeks unless excepted |
| Deployment purging | Three notifications before deletion for workloads outside the exception list |
| Inactive storage volume | May be purged after six months without access or notice; NRP storage is not archival storage |
| A100 GPUs | Default quota is zero; request access through the NRP portal |

Interactive `sleep` is allowed under its own limits. Batch Jobs must perform
finite work and exit. Keep resources close to measured use; see the main skill
for utilization bands and request/limit requirements.

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

### When the token expires (and logging in over SSH)

The cached OIDC token expires. From then on **every `kubectl` call blocks**,
silently, on a kubelogin process listening on port 8000, until someone completes
the browser login. Wrap every scripted `kubectl` call in `timeout`, so a dead
token surfaces as a failure instead of a hang.

- **Logged in over SSH?** Forward the callback port, then open the URL locally:
  ```bash
  ssh -N -L 8000:localhost:8000 <user>@<host>   # on your laptop; leave it running
  # then browse to http://localhost:8000 and finish the login there
  ```
- **"Request to authenticate with CiLogon has been denied. Please authenticate
  with the source you've previously signed up with."** NRP's identity provider
  (authentik) remembers the source you registered with. Pick that one on the login
  page, not CILogon.
- **Agents can't do the browser step.** They should stop and ask the user.

See [NRP documentation](https://nrp.ai/documentation/) for the rest.

## Container Images: the NRP GitLab registry

Every time a pod starts it **pulls its container image from a registry**, so your image must live somewhere the cluster can reach. NRP hosts its own GitLab with an integrated **container registry** at `gitlab-registry.nrp-nautilus.io` — it's free for NRP users, pulls fast from inside the cluster, and keeps private images off Docker Hub (whose pull-rate limits bite hard on a shared cluster where hundreds of pods pull at once). **This is the recommended place to store images for Nautilus.**

> **Unpublished or embargoed code** (e.g. work under paper submission): push
> only to a **private** project, never to a public registry, and only with the
> owner's OK.
>
> An alternative that needs no image at all: stage the built tools and code onto
> the PVC, run on a stock public base image (e.g. `ubuntu:24.04`), and install
> runtime packages at pod start, with retries. That setup takes a few minutes per
> pod; see [startup pacing](orchestration.md#startup-pacing-and-low-utilization-refusals)
> before launching a large wave.

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

### Storage operations

Use emptyDir for local scratch, and a dedicated PVC/prefix for persistent results.
Use an existing healthy workload for narrow inspection, or a finite real-work
staging/export Job; never an idle batch helper. A metadata walk can interfere
with other CephFS writers. Follow [orchestration.md](orchestration.md#storage-and-interrupted-work)
for closed-prefix recovery, live-read restrictions and cross-client inode checks.
Request expected capacity; do not assume quota behavior or backup coverage.
Export/backup only within the user's authorized destination and data scope.
