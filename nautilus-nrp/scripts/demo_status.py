#!/usr/bin/env python3
"""Generate a synthetic dashboard demo; no cluster calls or scientific compute."""
import argparse
import datetime as dt
import json
from pathlib import Path
from nrp_common import atomic_write, compact_job, compact_pod, utcnow
from live_status import build_view, write_output


def make_demo():
    now = dt.datetime.now(dt.timezone.utc)
    started = (now - dt.timedelta(hours=1)).isoformat(); measured = now.isoformat()
    jobs = []; pods = []
    for name, phase, group in [('alice-train-001', 'Succeeded', 'training'),
                               ('alice-sim-001', 'Succeeded', 'simulation'),
                               ('alice-grt-001', 'Running', 'openroad'),
                               ('alice-preprocess-001', 'Running', 'preprocessing')]:
        job_uid = name + '-job-uid'
        job = {'metadata': {'name': name, 'uid': job_uid, 'creationTimestamp': started,
                           'labels': {'app': 'demo', 'user': 'alice', 'group': group}},
               'spec': {'suspend': False}, 'status': {'active': int(phase == 'Running'),
               'conditions': [] if phase == 'Running' else [{'type': 'Complete', 'status': 'True'}]}}
        pod = {'metadata': {'name': name + '-pod', 'uid': name + '-pod-uid', 'creationTimestamp': started,
                           'labels': job['metadata']['labels'],
                           'ownerReferences': [{'kind': 'Job', 'uid': job_uid, 'name': name}]},
               'spec': {'nodeName': 'synthetic-node', 'containers': [{'name': 'worker',
                        'resources': {'requests': {'cpu': '4', 'memory': '12Gi'}}}]},
               'status': {'phase': phase, 'containerStatuses': [{'name': 'worker', 'restartCount': 0,
                           'state': {'running': {}} if phase == 'Running' else {'terminated': {'exitCode': 0}}}]}}
        metric = {'metadata': {'name': pod['metadata']['name']},
                  'timestamp': measured if group != 'preprocessing' else (now - dt.timedelta(minutes=20)).isoformat(),
                  'containers': [{'name': 'worker', 'usage': {'cpu': '1800m', 'memory': '8Gi'}}]}
        jobs.append(compact_job(job)); pods.append(compact_pod(pod, metric if phase == 'Running' else None))
    quota = {'metadata': {'name': 'pod-ceiling'}, 'spec': {},
             'status': {'hard': {'pods': '200'}, 'used': {'pods': '3'}}}
    scoped_zero = {'metadata': {'name': 'priority-class-ban'}, 'spec': {'scopes': ['PriorityClass']},
                   'status': {'hard': {'pods': '0'}, 'used': {'pods': '0'}}}
    namespace_pods = [{'metadata': {'name': p['name'], 'uid': p['uid']}, 'status': {'phase': p['phase']}} for p in pods]
    namespace_pods.append({'metadata': {'name': 'other-owner-job', 'uid': 'other'}, 'status': {'phase': 'Pending'}})
    sections = {key: {'observed_at': measured, 'error': None, 'value': value} for key, value in
                {'jobs': jobs, 'pods': pods, 'namespace_pods': namespace_pods,
                 'quotas': [quota, scoped_zero], 'metrics': []}.items()}
    snapshot = {'schema_version': 1, 'generated_at': measured, 'context': 'synthetic-demo',
                'namespace': 'demo', 'selector': 'app=demo,user=alice', 'sections': sections}
    cases = []
    for index, (run_id, group, status, endpoint) in enumerate([
            ('train-lr001-seed42', 'training', 'complete', 'evaluation.json'),
            ('sim-voltage090-seed42', 'simulation', 'flow_failed', 'simulation-report'),
            ('design-a-rent060-seed42', 'openroad', 'running', '5_1_grt'),
            ('preprocess-shard004', 'preprocessing', 'held', 'encoded.parquet')]):
        job = jobs[index]
        cases.append({'run_id': run_id, 'group': group, 'seed': 42,
                      'status': status, 'phase': group, 'endpoint': endpoint,
                      'job_name': job['name'], 'job_uid': job['uid'],
                      'parameters': {'learning_rate': .001} if index == 0 else {'setting': index},
                      'metrics': {'wall_seconds': 180} if index < 2 else {},
                      'evidence': {'reference': 'SYNTHETIC example receipt, not experimental evidence',
                                   'job_uid': job['uid'], 'pod_uid': pods[index]['uid'], 'endpoint': endpoint}})
    cases.append({'run_id': 'cancelled-case', 'group': 'simulation', 'seed': 43, 'status': 'cancelled'})
    runs = {'title': 'Nautilus monitor · SYNTHETIC DEMO', 'updated_at': measured, 'target_pods': 200, 'runs': cases}
    admission = {'checked_at': measured, 'context': 'synthetic-demo', 'namespace': 'demo',
                 'allowed': False, 'error': 'SIMULATED admission refusal; this is not a live account check'}
    return snapshot, runs, admission


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(); snapshot, runs, admission = make_demo()
    write_output(args.output, snapshot, build_view(snapshot, runs, admission), 60)
    atomic_write(args.output/'runs.json', json.dumps(runs, indent=2) + '\n')
    atomic_write(args.output/'admission.json', json.dumps(admission, indent=2) + '\n')
    print(str(args.output/'index.html'))


if __name__ == '__main__':
    main()
