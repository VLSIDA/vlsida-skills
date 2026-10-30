#!/usr/bin/env python3
"""Worker-side example: run a step on node-local scratch instead of a CephFS PVC.

Pattern measured on a CephFS-heavy EDA step (2026-10): task start to step start
went from 3-14 min to under 1 min, and the Pod reached the CPU/RAM bands within
about 6 min. Adapt paths and the command to your workload. Python stdlib only.

  stage-in : copy the step's inputs from the PVC to scratch; verify each copy's
             SHA-256 (against a committed hash when you have one).
  run      : run the unchanged command with its work directory on scratch.
  stage-out: for every new or changed scratch file -> copy to a private temp on
             the PVC -> fsync -> rename into place -> fsync the directory ->
             re-read from the PVC with the page cache dropped and compare
             SHA-256. Only then write the step's done marker.

A crash at any point leaves no done marker for incomplete outputs. Treat a
staging/copy/verify error as a retryable infrastructure hold, never as an
application failure. Give the Pod an emptyDir plus requests.ephemeral-storage
sized to the staged inputs and outputs: with request 0 the scheduler ignores local
disk and the Pod is first in line for disk-pressure eviction.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import uuid

CHUNK = 8 * 1024 * 1024


def sha256(path, drop_cache=False):
    digest = hashlib.sha256()
    with open(path, 'rb', buffering=0) as stream:
        if drop_cache and hasattr(os, 'posix_fadvise'):
            os.posix_fadvise(stream.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
        for chunk in iter(lambda: stream.read(CHUNK), b''):
            digest.update(chunk)
    return digest.hexdigest()


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def stage_in(names, pvc_dir, scratch_dir, expected=None):
    """Copy inputs to scratch; raise if a copy differs from its source or from expected[name]."""
    scratch_dir = Path(scratch_dir); scratch_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        source, target = Path(pvc_dir) / name, scratch_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        got = sha256(target)
        if got != sha256(source) or (expected and expected.get(name) not in (None, got)):
            raise RuntimeError('stage-in hash mismatch: ' + name)


def snapshot(root):
    root = Path(root)
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}


def stage_out(scratch_dir, pvc_dir, temp_dir, before):
    """Publish files that are new or changed since `before`; return {relative path: sha256}."""
    scratch_dir, pvc_dir, temp_dir = Path(scratch_dir), Path(pvc_dir), Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    published = {}
    for rel, state in sorted(snapshot(scratch_dir).items()):
        if before.get(rel) == state:
            continue
        source, destination = scratch_dir / rel, pvc_dir / rel
        temporary = temp_dir / (uuid.uuid4().hex + '.tmp')
        shutil.copy2(source, temporary)
        with open(temporary, 'rb') as stream:
            os.fsync(stream.fileno())
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, destination)           # temp_dir must be on the same filesystem
        fsync_dir(destination.parent)
        want = sha256(source)
        if sha256(destination, drop_cache=True) != want:
            raise RuntimeError('published copy differs after fsync: ' + rel)
        published[rel] = want
    return published


def run_step(command, inputs, pvc_dir, scratch_dir, temp_dir, marker):
    stage_in(inputs, pvc_dir, scratch_dir)
    before = snapshot(scratch_dir)
    rc = subprocess.run(command, cwd=scratch_dir).returncode
    if rc:
        return rc                                    # application failure: record it; publish logs as evidence
    stage_out(scratch_dir, pvc_dir, temp_dir, before)
    Path(marker).write_text('done\n')                # only after every output verified on the PVC
    return 0
