#!/usr/bin/env python3
"""Recover Job -> Pod identities after the Pods are gone. Read-only: local files only.

Recovery code that binds checkpoints to the Pod that wrote them needs that Pod's
exact name. When a Pod was deleted before anyone recorded it, use:

  --events FILE     `kubectl get events -o json`, saved while the Job's events
                    still existed (default event TTL: 1 hour). Job events
                    "Created pod: NAME" are bound to the Job UID: authoritative.
  --snapshots FILE  JSONL; each line a snapshot whose "pods" list holds
                    {"name", "uid", optional "owners"} rows, e.g. a dispatcher's
                    periodic account observations. Matched by name prefix and,
                    when a row has ownerReferences, by Job UID.
  --jobs FILE       JSON list of {"name", "uid"} Jobs to resolve.

The Job controller asks for generateName "<job>-"; the API server cuts that base
to 58 characters and appends 5 random ones. A Job name longer than 57 characters
therefore does NOT prefix its Pod names, and stripping the last "-xxxxx" from a
Pod name does not give the Job name. Map live Pods by ownerReferences UID or the
batch.kubernetes.io/job-name label instead. Indexed Jobs use another pattern and
are not handled here.

A Job resolves only when exactly one Pod matches; otherwise it is reported as
ambiguous (retries, or two long names sharing a prefix) or missing. Exit status
3 if any Job is unresolved. Verify the recovered name against the checkpoint's
own writer receipts before trusting it.
"""
import argparse
import json
import re

GENERATED_BASE = 58          # 63-character name limit minus 5 random characters
RANDOM = 5
CREATED = re.compile(r'Created pod: (\S+)')


def pod_prefix(job_name):
    return (job_name + '-')[:GENERATED_BASE]


def belongs(pod_name, job_name):
    prefix = pod_prefix(job_name)
    return pod_name.startswith(prefix) and len(pod_name) == len(prefix) + RANDOM


def owner_ok(row, job):
    """False only when the row names a different owning Job UID."""
    owners = [o for o in row.get('owners') or [] if isinstance(o, dict) and o.get('kind') == 'Job']
    return not owners or not job.get('uid') or any(o.get('uid') == job['uid'] for o in owners)


def from_events(events, jobs):
    """{job name: {pod names}} from Job 'Created pod' events bound to the Job UID."""
    by_uid = {j['uid']: j['name'] for j in jobs if j.get('uid')}
    found = {}
    for event in (events or {}).get('items', []):
        obj = event.get('involvedObject', {})
        if obj.get('kind') != 'Job' or obj.get('uid') not in by_uid:
            continue
        match = CREATED.search(event.get('message', ''))
        if match:
            found.setdefault(by_uid[obj['uid']], set()).add(match.group(1))
    return found


def from_snapshots(lines, jobs):
    """({job name: {pod name: pod uid}}, {job name: {pod names shared with another job}})."""
    found, shared = {}, {}
    for line in lines:
        try:
            snapshot = json.loads(line)
        except ValueError:
            continue
        rows = snapshot.get('pods') if isinstance(snapshot, dict) else None
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            pod = str(row.get('name', ''))
            matches = [j['name'] for j in jobs if belongs(pod, j['name']) and owner_ok(row, j)]
            if len(matches) > 1:
                for job in matches:
                    shared.setdefault(job, set()).add(pod)
            elif matches:
                seen = found.setdefault(matches[0], {})
                uid = row.get('uid')
                seen[pod] = uid if seen.get(pod, uid) == uid else None   # conflicting UIDs: unknown
    return found, shared


def resolve(jobs, events=None, snapshot_lines=()):
    evented = from_events(events, jobs)
    seen, shared = from_snapshots(snapshot_lines, jobs)
    out = {}
    for job in (j['name'] for j in jobs):
        observed = seen.get(job, {})
        if evented.get(job):
            names, source, unsure = evented[job], 'events', set()
        else:
            names, source, unsure = set(observed), 'snapshots', shared.get(job, set())
        if len(names) == 1 and not unsure:
            pod = next(iter(names))
            out[job] = {'status': 'resolved', 'pod_name': pod, 'pod_uid': observed.get(pod), 'source': source}
        else:
            candidates = sorted(names | unsure)
            out[job] = {'status': 'ambiguous' if candidates else 'missing', 'candidates': candidates,
                        'source': source if candidates else None}
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--jobs', required=True)
    p.add_argument('--events')
    p.add_argument('--snapshots')
    args = p.parse_args()
    with open(args.jobs) as stream:
        jobs = json.load(stream)
    events = None
    if args.events:
        with open(args.events) as stream:
            events = json.load(stream)
    if args.snapshots:
        with open(args.snapshots) as stream:
            result = resolve(jobs, events, stream)
    else:
        result = resolve(jobs, events)
    print(json.dumps(result, indent=2))
    return 0 if all(v['status'] == 'resolved' for v in result.values()) else 3


if __name__ == '__main__':
    raise SystemExit(main())
