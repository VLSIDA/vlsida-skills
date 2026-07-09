---
name: gcloud
description: Help with Google Cloud Platform using the gcloud CLI, Google Cloud Storage (GCS), and Google Compute Engine (GCE). Covers authentication, project configuration, bucket management, file transfers, and VM lifecycle.
user_invocable: true
---

You help the user work with Google Cloud Platform via the `gcloud` CLI and related tools.

## Scope

This skill covers:
- **gcloud CLI** — authentication, project/region config, common commands
- **Google Cloud Storage (GCS)** — bucket management, file upload/download, sync
- **Google Compute Engine (GCE)** — creating, managing, and connecting to VMs

## Prerequisites

- `gcloud` CLI installed (`google-cloud-cli` package or https://cloud.google.com/sdk/docs/install)
- Authenticated: `gcloud auth login`
- A GCP project set: `gcloud config set project PROJECT_ID`

## gcloud CLI Essentials

### Authentication

```bash
# Interactive login (opens browser)
gcloud auth login

# Application default credentials (for client libraries)
gcloud auth application-default login

# Service account auth
gcloud auth activate-service-account --key-file=key.json

# Check current identity
gcloud auth list
```

### Configuration

```bash
# Set default project
gcloud config set project PROJECT_ID

# Set default region/zone
gcloud config set compute/region us-west1
gcloud config set compute/zone us-west1-b

# View current config
gcloud config list

# Named configurations (for multiple projects/accounts)
gcloud config configurations create my-config
gcloud config configurations activate my-config
gcloud config configurations list
```

### Useful general commands

```bash
# List projects
gcloud projects list

# Describe current project
gcloud projects describe $(gcloud config get project)

# Check enabled APIs
gcloud services list --enabled

# Enable an API
gcloud services enable storage.googleapis.com
```

## Google Cloud Storage (GCS)

The modern CLI uses `gcloud storage` (preferred over legacy `gsutil`).

### Bucket operations

```bash
# Create a bucket
gcloud storage buckets create gs://BUCKET_NAME --location=us-west1

# List buckets
gcloud storage buckets list

# Describe a bucket
gcloud storage buckets describe gs://BUCKET_NAME

# Delete a bucket (must be empty, or use --recursive)
gcloud storage rm --recursive gs://BUCKET_NAME
```

### File operations

```bash
# Upload a file
gcloud storage cp local-file.txt gs://BUCKET_NAME/path/

# Upload a directory recursively
gcloud storage cp --recursive local-dir/ gs://BUCKET_NAME/path/

# Download a file
gcloud storage cp gs://BUCKET_NAME/path/file.txt ./local-dest/

# List objects
gcloud storage ls gs://BUCKET_NAME/path/

# List with details (size, timestamps)
gcloud storage ls -l gs://BUCKET_NAME/path/

# Delete objects
gcloud storage rm gs://BUCKET_NAME/path/file.txt
gcloud storage rm --recursive gs://BUCKET_NAME/path/
```

### Sync (mirror directories)

```bash
# Sync local to GCS (upload new/changed, optionally delete remote extras)
gcloud storage rsync local-dir/ gs://BUCKET_NAME/path/

# Sync GCS to local
gcloud storage rsync gs://BUCKET_NAME/path/ local-dir/

# Delete destination files not in source
gcloud storage rsync --delete-unmatched-destination-objects local-dir/ gs://BUCKET_NAME/path/

# Dry run
gcloud storage rsync --dry-run local-dir/ gs://BUCKET_NAME/path/
```

### Access control

```bash
# Make a file publicly readable
gcloud storage objects update gs://BUCKET_NAME/file.txt --add-acl-grant=entity=allUsers,role=READER

# Set uniform bucket-level access (recommended)
gcloud storage buckets update gs://BUCKET_NAME --uniform-bucket-level-access

# Grant a user access via IAM
gcloud storage buckets add-iam-policy-binding gs://BUCKET_NAME \
  --member=user:email@example.com \
  --role=roles/storage.objectViewer
```

### Signed URLs (temporary access)

```bash
# Generate a signed URL (requires service account key or impersonation)
gcloud storage sign-url gs://BUCKET_NAME/file.txt --duration=1h
```

## Google Compute Engine (GCE)

### Create a VM

```bash
# Basic VM
gcloud compute instances create my-vm \
  --zone=us-west1-b \
  --machine-type=e2-medium \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=50GB

# With GPU
gcloud compute instances create gpu-vm \
  --zone=us-west1-b \
  --machine-type=n1-standard-8 \
  --accelerator=type=nvidia-tesla-t4,count=1 \
  --maintenance-policy=TERMINATE \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=200GB

# Preemptible (much cheaper, can be reclaimed)
gcloud compute instances create cheap-vm \
  --zone=us-west1-b \
  --machine-type=e2-medium \
  --provisioning-model=SPOT \
  --image-family=ubuntu-2404-lts-amd64 \
  --image-project=ubuntu-os-cloud
```

### VM lifecycle

```bash
# List instances
gcloud compute instances list

# Start/stop/delete
gcloud compute instances start my-vm --zone=us-west1-b
gcloud compute instances stop my-vm --zone=us-west1-b
gcloud compute instances delete my-vm --zone=us-west1-b

# Describe (detailed info)
gcloud compute instances describe my-vm --zone=us-west1-b
```

### SSH and file transfer

```bash
# SSH into a VM
gcloud compute ssh my-vm --zone=us-west1-b

# SSH with port forwarding
gcloud compute ssh my-vm --zone=us-west1-b -- -L 8080:localhost:8080

# Copy files to/from VM
gcloud compute scp local-file.txt my-vm:~/dest/ --zone=us-west1-b
gcloud compute scp --recurse my-vm:~/results/ ./local-results/ --zone=us-west1-b
```

### Disks

```bash
# Create a persistent disk
gcloud compute disks create my-disk --size=100GB --zone=us-west1-b

# Attach to a running VM
gcloud compute instances attach-disk my-vm --disk=my-disk --zone=us-west1-b

# Detach
gcloud compute instances detach-disk my-vm --disk=my-disk --zone=us-west1-b
```

### Firewall rules

```bash
# Allow HTTP
gcloud compute firewall-rules create allow-http \
  --allow=tcp:80 --target-tags=http-server

# Allow a custom port
gcloud compute firewall-rules create allow-custom \
  --allow=tcp:8080 --source-ranges=0.0.0.0/0

# List rules
gcloud compute firewall-rules list
```

## Tips

- Use `--format=json` or `--format="value(FIELD)"` to extract specific fields for scripting.
- Use `--quiet` to suppress interactive prompts in scripts.
- Use `gcloud compute instances list --filter="status=RUNNING"` to filter results.
- Check costs: `gcloud billing accounts list` and use the [pricing calculator](https://cloud.google.com/products/calculator).
- Always set `--zone` explicitly or configure a default to avoid prompts.
