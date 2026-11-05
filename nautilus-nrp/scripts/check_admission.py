#!/usr/bin/env python3
"""Probe the intended Pod shape through server dry-run; never creates a Job/Pod."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re

from nrp_common import ApiError, Kube, atomic_write, utcnow


def pod_probe(document, namespace):
    kind = document.get('kind')
    if kind == 'Job':
        spec = copy.deepcopy(document['spec']['template']['spec'])
        labels = copy.deepcopy(document['spec']['template'].get('metadata', {}).get('labels', {}))
        annotations = copy.deepcopy(document['spec']['template'].get('metadata', {}).get('annotations', {}))
    elif kind == 'Pod':
        spec = copy.deepcopy(document['spec']); labels = copy.deepcopy(document['metadata'].get('labels', {}))
        annotations = copy.deepcopy(document['metadata'].get('annotations', {}))
    else:
        raise ValueError('Input must be a JSON Job or Pod manifest')
    if document.get('metadata', {}).get('namespace', namespace) != namespace:
        raise ValueError('Manifest namespace differs from explicit probe namespace')
    name = document['metadata']['name']
    if not re.fullmatch(r'[a-z0-9]([a-z0-9.-]*[a-z0-9])?', name):
        raise ValueError('A DNS-safe manifest name with the owner prefix is required')
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    probe_name = name[:44].rstrip('-.') + '-probe-' + digest[:10]
    return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': probe_name, 'namespace': namespace,
            'labels': labels, 'annotations': annotations,
            **({'ownerReferences': copy.deepcopy(document['metadata']['ownerReferences'])}
               if kind == 'Pod' and document['metadata'].get('ownerReferences') else {})}, 'spec': spec}, digest


def probe(client, document):
    pod, digest = pod_probe(document, client.namespace)
    result = {'checked_at': utcnow(), 'context': client.context, 'namespace': client.namespace,
              'manifest_name': document['metadata']['name'], 'pod_spec_sha256': digest,
              'operation': 'Pod CREATE server dry-run', 'allowed': None}
    try:
        response = client.json(['create', '--dry-run=server', '-f', '-', '-o', 'json'], pod)
        if response.get('kind') != 'Pod' or response.get('metadata', {}).get('name') != pod['metadata']['name']:
            raise ApiError('Dry-run response does not match requested Pod')
        result.update(allowed=True, message='This intended shape was admitted at the recorded instant; no object persisted')
    except (ApiError, OSError) as exc:
        # Unknown timeouts/auth/network failures differ from an explicit server refusal.
        error = str(exc)
        refused = any(text in error.lower() for text in ('denied the request', 'exceeded quota', 'forbidden', 'admission webhook', 'error from server'))
        result.update(allowed=False if refused else None, error=error)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True, help='Exact intended Job/Pod manifest as JSON')
    p.add_argument('--namespace', required=True); p.add_argument('--context', default='nautilus')
    p.add_argument('--output', type=Path, required=True); p.add_argument('--timeout', type=int, default=25)
    args = p.parse_args()
    result = probe(Kube(args.context, args.namespace, args.timeout), json.loads(args.manifest.read_text()))
    atomic_write(args.output, json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
    return 0 if result['allowed'] is True else 1 if result['allowed'] is False else 2


if __name__ == '__main__':
    raise SystemExit(main())
