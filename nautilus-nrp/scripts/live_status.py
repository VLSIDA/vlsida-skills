#!/usr/bin/env python3
"""Read-only native snapshots and a self-contained live HTML dashboard.

Never submits, deletes, retries work, scans a PVC, or infers scientific success.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import fcntl
import json
from pathlib import Path
import signal
import time
from urllib.parse import quote, urlsplit

from nrp_common import (ApiError, Kube, atomic_write, compact_job, compact_pod,
                        pod_slots, timestamp, utcnow)

ROOT = Path(__file__).resolve().parent.parent
STATES = {'planned', 'running', 'complete', 'flow_failed', 'held', 'collection_held', 'cancelled', 'unknown'}


def read_json(path):
    def invalid(value):
        raise ValueError('Non-finite JSON number: ' + value)
    return json.loads(Path(path).read_text(), parse_constant=invalid)


def safe_link(value):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value) or '\\' in value:
        return None
    value = value.strip(); parsed = urlsplit(value)
    if parsed.scheme not in ('', 'http', 'https') or (not parsed.scheme and (parsed.netloc or value.startswith('/'))):
        return None
    return value


def load_runs(path):
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get('runs'), list):
        raise ValueError('Runs file needs a runs array')
    ids = set()
    for row in data['runs']:
        if not isinstance(row, dict):
            raise ValueError('Each planned run must be an object')
        rid = row.get('run_id')
        if not isinstance(rid, str) or not rid or rid in ids:
            raise ValueError('Missing or duplicate planned run_id: ' + str(rid))
        ids.add(rid)
        if row.get('status', 'planned') not in STATES:
            raise ValueError('Unsupported reported status for ' + rid)
        if not isinstance(row.get('parameters', {}), dict) or not isinstance(row.get('metrics', {}), dict):
            raise ValueError('parameters and metrics must be objects for ' + rid)
        for artifact in row.get('artifacts', []):
            if not isinstance(artifact, dict) or not safe_link(artifact.get('href')):
                raise ValueError('Invalid artifact URL for ' + rid)
    target = data.get('target_pods')
    if target is not None and (type(target) is not int or target < 1):
        raise ValueError('target_pods must be a positive integer')
    return data


def collect(client, previous=None):
    previous = previous or {}; sections = copy.deepcopy(previous.get('sections', {}))
    requests = {
        'jobs': ['get', 'jobs', '-l', client.selector, '-o', 'json'],
        'pods': ['get', 'pods', '-l', client.selector, '-o', 'json'],
        'namespace_pods': ['get', 'pods', '-o', 'json'],
        'quotas': ['get', 'resourcequota', '-o', 'json'],
        'metrics': ['get', '--raw', '/apis/metrics.k8s.io/v1beta1/namespaces/' + quote(client.namespace, safe='') + '/pods'],
    }
    def request(item):
        key, arguments = item
        try:
            response = client.json(arguments)
            if not isinstance(response.get('items'), list):
                raise ValueError('Native List response lacks items')
            return key, response['items'], None, utcnow()
        except (ApiError, OSError, ValueError) as exc:
            return key, None, str(exc), utcnow()
    with ThreadPoolExecutor(max_workers=4) as pool:
        observations = list(pool.map(request, requests.items()))
    raw = {key: values for key, values, error, at in observations if error is None}
    metrics = {m['metadata']['name']: m for m in raw.get('metrics', sections.get('metrics', {}).get('value', []))}
    for key, values, error, at in observations:
        if error:
            retained = sections.setdefault(key, {'observed_at': None, 'value': []})
            retained.update(error=error, attempted_at=at)
            continue
        if key == 'jobs':
            values = [compact_job(j) for j in values]
        elif key == 'pods':
            values = [compact_pod(p, metrics.get(p['metadata']['name'])) for p in values]
        elif key == 'namespace_pods':
            values = [{'metadata': {'name': p['metadata']['name'], 'uid': p['metadata']['uid']},
                       'status': {'phase': p.get('status', {}).get('phase', 'Unknown')}} for p in values]
        sections[key] = {'observed_at': at, 'error': None, 'value': values}
    return {'schema_version': 1, 'generated_at': utcnow(), 'context': client.context,
            'namespace': client.namespace, 'selector': client.selector, 'sections': sections}


def build_view(snapshot, runs=None, admission=None, stale_after=180):
    result = copy.deepcopy(snapshot); result['stale_after'] = stale_after; sections = result.setdefault('sections', {})
    now = time.time(); warnings = []
    for key in ('jobs', 'pods', 'namespace_pods', 'quotas', 'metrics'):
        section = sections.setdefault(key, {'observed_at': None, 'value': [], 'error': 'Not observed'})
        age = now - timestamp(section['observed_at']) if section.get('observed_at') else None
        section['age_seconds'] = age
        section['stale'] = bool(section.get('error')) or age is None or age > stale_after or age < -60
        if section['stale']:
            warnings.append(key + ': ' + (section.get('error') or 'observation stale or unavailable'))
    jobs = {j['name']: j for j in sections['jobs']['value']}
    pods = sections['pods']['value']
    def owned(job):
        return [p for p in pods if any(o.get('kind') == 'Job' and o.get('uid') == job['uid'] for o in p['owners'])]
    rows = []
    if runs is not None:
        for run in runs['runs']:
            row = copy.deepcopy(run)
            row['application_status'] = row.get('status', 'planned')
            job = jobs.get(row.get('job_name'))
            if job and row.get('job_uid') and job['uid'] != row['job_uid']:
                row['native_status'] = 'Job UID mismatch; collection held'; children = []
            else:
                row['native_status'] = job['status'] if job else 'No current native Job evidence'
                children = owned(job) if job else []
            evidence = row.get('evidence', {})
            if row['application_status'] in ('complete', 'flow_failed'):
                reported = (isinstance(evidence, dict) and evidence.get('reference') and
                            evidence.get('job_uid') == row.get('job_uid') and evidence.get('job_uid') and
                            evidence.get('pod_uid') and
                            (not row.get('endpoint') or evidence.get('endpoint') == row['endpoint']))
                if not reported or 'UID mismatch' in row['native_status']:
                    row['application_status'] = 'unverified report: ' + row['application_status']
            row['pods'] = children
            row['artifacts'] = [{'label': a.get('label', 'Artifact'), 'href': safe_link(a['href']),
                                 'image': a.get('image', False)} for a in row.get('artifacts', [])]
            rows.append(row)
        result.update(title=runs.get('title', 'Nautilus runs'), target_pods=runs.get('target_pods'),
                      runs_observed_at=runs.get('updated_at'), reported_cases=len(rows))
    else:
        for job in jobs.values():
            rows.append({'run_id': job['name'], 'job_name': job['name'], 'job_uid': job['uid'],
                         'group': job['labels'].get('group', job['labels'].get('design', '')),
                         'native_status': job['status'], 'application_status': 'not supplied',
                         'pods': owned(job), 'parameters': {}, 'metrics': {}, 'artifacts': []})
        result.update(title='Nautilus workload monitor', target_pods=None, reported_cases=None)
    result['rows'] = rows
    result['slots'] = pod_slots(sections['quotas']['value'], sections['namespace_pods']['value'])
    result['slots']['stale'] = sections['quotas']['stale'] or sections['namespace_pods']['stale']
    result['scoped_active_pods'] = sum(p['nonterminal'] for p in pods)
    result['namespace_active_pods'] = sum(p['status']['phase'] not in ('Succeeded', 'Failed')
                                         for p in sections['namespace_pods']['value'])
    result['admission'] = admission
    if admission:
        same_scope = admission.get('context') == result.get('context') and admission.get('namespace') == result.get('namespace')
        if not same_scope:
            result['admission'] = {**admission, 'allowed': None, 'error': 'Admission evidence belongs to another context/namespace'}
            warnings.append('Admission proof scope mismatch')
    result['warnings'] = warnings
    return result


def render(view, refresh_seconds=60):
    payload = json.dumps(view, allow_nan=False, separators=(',', ':')).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    template = (ROOT/'assets/live-dashboard.html').read_text()
    return template.replace('__INITIAL_DATA__', payload).replace('__REFRESH_SECONDS__', str(refresh_seconds))


def write_output(output, snapshot, view, interval):
    output = Path(output)
    atomic_write(output/'snapshot.json', json.dumps(view, allow_nan=False, indent=2) + '\n')
    atomic_write(output/'collector-state.json', json.dumps(snapshot, allow_nan=False) + '\n')
    atomic_write(output/'index.html', render(view, interval))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', default='nautilus')
    parser.add_argument('--namespace')
    parser.add_argument('--selector', help='Explicit workload labels; required for native collection')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--runs-file', type=Path, help='Local normalized application ledger; never read from a live PVC')
    parser.add_argument('--admission-file', type=Path, help='Output of check_admission.py; no automatic probe')
    parser.add_argument('--snapshot-file', type=Path, help='Render a retained collector snapshot, offline')
    parser.add_argument('--interval', type=int, default=60)
    parser.add_argument('--stale-after', type=int, default=180)
    parser.add_argument('--timeout', type=int, default=25)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    if args.interval < 5 or args.timeout < 5 or args.stale_after < 5:
        parser.error('interval, timeout and stale-after must be at least five seconds')
    if not args.snapshot_file and (not args.namespace or not args.selector):
        parser.error('Native collection requires --namespace and --selector')
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output/'.monitor.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('Another collector owns this output directory')
        stop = False
        def stopped(*_):
            nonlocal stop
            stop = True
        signal.signal(signal.SIGTERM, stopped); signal.signal(signal.SIGINT, stopped)
        client = Kube(args.context, args.namespace, args.timeout); client.selector = args.selector
        state_path = args.output/'collector-state.json'
        previous = read_json(state_path) if state_path.exists() else None
        if previous and (previous.get('context'), previous.get('namespace'), previous.get('selector')) != (args.context, args.namespace, args.selector) and not args.snapshot_file:
            parser.error('Output directory belongs to a different context, namespace or selector')
        last_runs = last_admission = None
        while not stop:
            snapshot = read_json(args.snapshot_file) if args.snapshot_file else collect(client, previous)
            input_errors = []
            try:
                runs = load_runs(args.runs_file) if args.runs_file else None
                last_runs = runs
            except (OSError, ValueError, TypeError) as exc:
                runs = last_runs; input_errors.append('Application ledger unavailable; last good data retained: ' + str(exc))
            try:
                admission = read_json(args.admission_file) if args.admission_file else None
                if admission is not None and not isinstance(admission, dict):
                    raise ValueError('Admission evidence must be a JSON object')
                last_admission = admission
            except (OSError, ValueError, TypeError) as exc:
                admission = last_admission; input_errors.append('Admission file unavailable; last good proof retained: ' + str(exc))
            view = build_view(snapshot, runs, admission, args.stale_after)
            view['warnings'].extend(input_errors)
            write_output(args.output, snapshot, view, args.interval); previous = snapshot
            print(json.dumps({'at': utcnow(), 'active_workload_pods': view['scoped_active_pods'],
                              'warnings': view['warnings'], 'html': str(args.output/'index.html')}), flush=True)
            if args.once or args.snapshot_file:
                return 2 if input_errors or (not args.snapshot_file and any(view['sections'][k]['stale'] for k in ('jobs', 'pods', 'namespace_pods', 'quotas'))) else 0
            end = time.monotonic() + args.interval
            while not stop and time.monotonic() < end:
                time.sleep(min(1, max(0, end - time.monotonic())))


if __name__ == '__main__':
    raise SystemExit(main())
