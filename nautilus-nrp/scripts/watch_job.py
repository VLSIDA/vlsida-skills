#!/usr/bin/env python3
"""Watch exact native Job/Pod identities and bounded stdout; no cluster writes."""
import argparse
import json
from pathlib import Path
import re
import signal
import time
from nrp_common import ApiError, Kube, atomic_write, condition, job_status, utcnow


def observe(client, name, expected_uid=None, container=None, pattern=None):
    job = client.json(['get', 'job', name, '-o', 'json']); uid = job['metadata']['uid']
    if expected_uid and uid != expected_uid:
        raise ApiError('Job UID changed; observation held, no automatic takeover')
    all_pods = client.json(['get', 'pods', '-l', 'job-name=' + name, '-o', 'json'])['items']
    pods = [p for p in all_pods if any(o.get('kind') == 'Job' and o.get('uid') == uid
                                      for o in p['metadata'].get('ownerReferences', []))]
    terminal = condition(job, 'Complete') or condition(job, 'Failed')
    events = [{'event': 'native_job', 'job': name, 'uid': uid, 'status': job_status(job)}]
    held = False; logs = {}
    for pod in pods:
        m = pod['metadata']; phase = pod.get('status', {}).get('phase', 'Unknown')
        events.append({'event': 'native_pod', 'pod': m['name'], 'uid': m['uid'], 'phase': phase,
                       'node': pod.get('spec', {}).get('nodeName')})
        if phase not in ('Running', 'Succeeded', 'Failed'):
            continue
        names = [c['name'] for c in pod['spec']['containers']]
        selected = container or (names[0] if len(names) == 1 else None)
        if not selected or selected not in names:
            events.append({'event': 'collection_held', 'pod': m['name'], 'reason': 'Specify the application container'}); held = True; continue
        try:
            text = client.logs(pod, selected, 40 if terminal else 200); logs[m['uid']] = text
            for line in text.splitlines():
                if terminal or (pattern and pattern.search(line)):
                    events.append({'event': 'stdout', 'pod_uid': m['uid'], 'line': line})
        except (ApiError, OSError) as exc:
            events.append({'event': 'collection_held', 'pod': m['name'], 'reason': str(exc)}); held = True
    if terminal and not pods:
        events.append({'event': 'collection_held', 'reason': 'Native terminal Job has no retained exact owned Pod'}); held = True
    code = (2 if held else 1 if condition(job, 'Failed') else 0) if terminal else None
    return {'job_uid': uid, 'events': events, 'exit_code': code, 'job': job, 'pods': pods, 'logs': logs}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--job', required=True); p.add_argument('--namespace', required=True)
    p.add_argument('--context', default='nautilus'); p.add_argument('--job-uid'); p.add_argument('--container')
    p.add_argument('--interval', type=int, default=60)
    p.add_argument('--pattern', default='ERROR|FAILED|Traceback|Killed|OOM|Aborted|Elapsed time')
    p.add_argument('--evidence-dir', type=Path); p.add_argument('--once', action='store_true')
    args = p.parse_args()
    if args.interval < 1:
        p.error('interval must be positive')
    pattern = re.compile(args.pattern); client = Kube(args.context, args.namespace)
    uid = args.job_uid; seen = set(); stop = False
    def stopped(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, stopped); signal.signal(signal.SIGINT, stopped)
    while not stop:
        try:
            result = observe(client, args.job, uid, args.container, pattern); uid = result['job_uid']
        except (ApiError, OSError) as exc:
            print(json.dumps({'at': utcnow(), 'event': 'observation_held', 'reason': str(exc)}), flush=True); return 2
        for event in result['events']:
            key = json.dumps(event, sort_keys=True)
            if key not in seen:
                print(json.dumps({'at': utcnow(), **event}), flush=True); seen.add(key)
        if result['exit_code'] is not None:
            if args.evidence_dir:
                folder = args.evidence_dir / (args.job + '--' + uid)
                atomic_write(folder/'job.json', json.dumps(result['job'], indent=2) + '\n')
                atomic_write(folder/'pods.json', json.dumps(result['pods'], indent=2) + '\n')
                for pod_uid, text in result['logs'].items():
                    atomic_write(folder/(pod_uid + '.stdout.log'), text)
            return result['exit_code']
        if args.once:
            return 0
        end = time.monotonic() + args.interval
        while not stop and time.monotonic() < end:
            time.sleep(min(1, max(0, end - time.monotonic())))
    return 130


if __name__ == '__main__':
    raise SystemExit(main())
