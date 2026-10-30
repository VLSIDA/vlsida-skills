"""Small, read-only Kubernetes monitoring primitives; Python standard library."""
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile


def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def timestamp(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def quantity(value):
    """Kubernetes decimal/binary quantities, in base units (cores or bytes)."""
    match = re.fullmatch(r'([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)([numkKMGTPE]|[KMGTPE]i)?', str(value))
    if not match:
        raise ValueError('Unsupported Kubernetes quantity: ' + str(value))
    suffix = match[2] or ''
    powers = {'': 1, 'n': 1e-9, 'u': 1e-6, 'm': 1e-3, 'k': 1e3, 'K': 1e3}
    powers.update({c: 1000 ** n for n, c in enumerate('MGTPE', 2)})
    powers.update({c + 'i': 1024 ** n for n, c in enumerate('KMGTPE', 1)})
    result = float(match[1]) * powers[suffix]
    if not math.isfinite(result) or result < 0:
        raise ValueError('Invalid resource quantity: ' + str(value))
    return result


def pod_request(pod, resource):
    """Effective request, including init peaks, restartable init sidecars, overhead."""
    spec = pod['spec']
    def requested(container):
        return quantity(container.get('resources', {}).get('requests', {}).get(resource, '0'))
    app = sum(requested(c) for c in spec.get('containers', []))
    sidecars = init_peak = 0
    for container in spec.get('initContainers', []):
        value = requested(container)
        if container.get('restartPolicy') == 'Always':
            sidecars += value
            init_peak = max(init_peak, sidecars)
        else:
            init_peak = max(init_peak, sidecars + value)
    declared = spec.get('resources', {}).get('requests', {}).get(resource)
    effective = quantity(declared) if declared is not None else max(app + sidecars, init_peak)
    return effective + quantity(spec.get('overhead', {}).get(resource, '0'))


def condition(job, name):
    return any(c.get('type') == name and c.get('status') == 'True'
               for c in job.get('status', {}).get('conditions', []))


def job_status(job):
    if condition(job, 'Complete') and condition(job, 'Failed'):
        return 'Conflicting terminal evidence'
    if condition(job, 'Complete'):
        return 'Job complete'
    if condition(job, 'Failed'):
        return 'Job failed'
    if job.get('spec', {}).get('suspend') or condition(job, 'Suspended'):
        return 'Suspended'
    if condition(job, 'FailureTarget'):
        return 'Failure pending'
    return 'Active' if job.get('status', {}).get('active', 0) else 'Queued / awaiting native evidence'


def compact_job(job):
    m = job['metadata']
    return {'name': m['name'], 'uid': m['uid'], 'labels': m.get('labels', {}),
            'created_at': m.get('creationTimestamp'), 'status': job_status(job),
            'conditions': job.get('status', {}).get('conditions', []),
            'active': job.get('status', {}).get('active', 0),
            'succeeded': job.get('status', {}).get('succeeded', 0),
            'failed': job.get('status', {}).get('failed', 0)}


def compact_pod(pod, metric=None, now=None, max_metric_age=300):
    now = now if now is not None else dt.datetime.now(dt.timezone.utc).timestamp()
    m = pod['metadata']; status = pod.get('status', {})
    phase = status.get('phase', 'Unknown')
    row = {'name': m['name'], 'uid': m['uid'], 'labels': m.get('labels', {}),
           'owners': m.get('ownerReferences', []), 'phase': phase,
           'node': pod.get('spec', {}).get('nodeName'), 'deleting': bool(m.get('deletionTimestamp')),
           'created_at': m.get('creationTimestamp'), 'cpu_ratio': None, 'memory_ratio': None,
           'cpu_cores': None, 'memory_bytes': None, 'outside': None, 'usage_notes': [],
           'nonterminal': phase not in ('Succeeded', 'Failed'), 'metric_at': None,
           'containers': [{'name': x['name'], 'restarts': x.get('restartCount', 0),
                           'state': x.get('state', {})}
                          for x in status.get('containerStatuses', [])]}
    try:
        row['cpu_request'] = pod_request(pod, 'cpu')
        row['memory_request'] = pod_request(pod, 'memory')
    except (ValueError, KeyError) as exc:
        row['usage_notes'].append(str(exc)); return row
    if metric is None:
        row['usage_notes'].append('Metrics unavailable'); return row
    try:
        measured = timestamp(metric['timestamp'])
        created = timestamp(m['creationTimestamp'])
        if now - measured > max_metric_age or measured > now + 60 or measured < created:
            raise ValueError('Stale metrics or sample predates this Pod identity')
        metric_uid = metric.get('metadata', {}).get('uid')
        if metric_uid and metric_uid != m['uid']:
            raise ValueError('Metric Pod UID differs')
        names = {x['name'] for x in metric.get('containers', [])}
        running = {x['name'] for x in status.get('containerStatuses', []) + status.get('initContainerStatuses', [])
                   if 'running' in x.get('state', {})}
        if not metric.get('containers') or not running.issubset(names):
            raise ValueError('Metrics omit a running container')
        row['cpu_cores'] = sum(quantity(x['usage']['cpu']) for x in metric['containers'])
        row['memory_bytes'] = sum(quantity(x['usage']['memory']) for x in metric['containers'])
        row['metric_at'] = metric['timestamp']
        for resource, usage, lower, upper in [('cpu', row['cpu_cores'], .2, 2),
                                               ('memory', row['memory_bytes'], .2, 1.5)]:
            request = row[resource + '_request']
            if request <= 0:
                row['usage_notes'].append(resource + ' request missing/zero')
                continue
            ratio = usage / request; row[resource + '_ratio'] = ratio
            if not lower <= ratio <= upper:
                row['usage_notes'].append(resource + ' outside instantaneous band')
        known = [row['cpu_ratio'], row['memory_ratio']]
        bad = ((known[0] is not None and not .2 <= known[0] <= 2) or
               (known[1] is not None and not .2 <= known[1] <= 1.5))
        row['outside'] = True if bad else False if None not in known else None
    except (ValueError, KeyError, TypeError) as exc:
        row['cpu_ratio'] = row['memory_ratio'] = None
        row['usage_notes'].append(str(exc))
    return row


def pod_slots(quotas, namespace_pods):
    """Pod-count ceiling only; scoped priority-class zero quotas are not global."""
    applicable = [q for q in quotas if not q.get('spec', {}).get('scopes') and
                  not q.get('spec', {}).get('scopeSelector') and 'pods' in q.get('status', {}).get('hard', {})]
    if not applicable:
        return {'ceiling': None, 'used': None, 'free': None}
    ceiling = min(int(q['status']['hard']['pods']) for q in applicable)
    observed = sum(p.get('status', {}).get('phase') not in ('Succeeded', 'Failed') for p in namespace_pods)
    used = max([observed] + [int(q['status'].get('used', {}).get('pods', 0)) for q in applicable])
    return {'ceiling': ceiling, 'used': used, 'free': max(0, ceiling - used)}


def atomic_write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(value)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ApiError(RuntimeError):
    pass


class Kube:
    def __init__(self, context, namespace, timeout=25):
        self.context = context; self.namespace = namespace; self.timeout = timeout

    def run(self, arguments, document=None):
        command = ['kubectl', '--context', self.context, '-n', self.namespace,
                   '--request-timeout=' + str(max(1, self.timeout - 3)) + 's', *arguments]
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            stdout, stderr = proc.communicate(None if document is None else json.dumps(document), timeout=self.timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.communicate()
            raise ApiError('kubectl timed out (including possible OIDC authentication); no empty success inferred')
        if proc.returncode:
            raise ApiError((stderr or stdout)[-3000:].strip())
        return stdout

    def json(self, arguments, document=None):
        try:
            return json.loads(self.run(arguments, document))
        except ValueError as exc:
            raise ApiError('kubectl returned invalid JSON') from exc

    def logs(self, pod, container, tail=200):
        """Bind logs to a native Pod UID, including a check after the log read."""
        name = pod['metadata']['name']; uid = pod['metadata']['uid']
        before = self.json(['get', 'pod', name, '-o', 'json'])
        if before['metadata']['uid'] != uid:
            raise ApiError('Pod identity changed before stdout read')
        text = self.run(['logs', name, '-c', container, '--timestamps=true',
                         '--tail=' + str(tail), '--limit-bytes=65536', '--pod-running-timeout=5s'])
        after = self.json(['get', 'pod', name, '-o', 'json'])
        if after['metadata']['uid'] != uid:
            raise ApiError('Pod identity changed during stdout read')
        return text
