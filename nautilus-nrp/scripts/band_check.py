#!/usr/bin/env python3
"""CPU/RAM observations only: outside != admission refused; unknown != healthy."""
import argparse
import json
import re
import sys
from urllib.parse import quote
from nrp_common import ApiError, Kube, compact_pod


def summarize(pods, metrics, name_regex):
    byname = {m['metadata']['name']: m for m in metrics}
    return [compact_pod(p, byname.get(p['metadata']['name'])) for p in pods
            if p.get('status', {}).get('phase') == 'Running' and name_regex.search(p['metadata']['name'])]


def exit_code(rows):
    bad = sum(r['outside'] is True for r in rows)
    return min(bad, 100) if bad else 104 if any(r['outside'] is None for r in rows) else 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('namespace'); p.add_argument('name_regex', nargs='?', default='.')
    p.add_argument('--context', default='nautilus'); p.add_argument('--json', action='store_true')
    args = p.parse_args(); rx = re.compile(args.name_regex); client = Kube(args.context, args.namespace)
    try:
        pods = client.json(['get', 'pods', '-o', 'json'])['items']
    except (ApiError, OSError) as exc:
        print(str(exc), file=sys.stderr); return 101
    try:
        metrics = client.json(['get', '--raw', '/apis/metrics.k8s.io/v1beta1/namespaces/' + quote(args.namespace, safe='') + '/pods'])['items']
    except (ApiError, OSError) as exc:
        print(str(exc), file=sys.stderr); return 102
    rows = summarize(pods, metrics, rx)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        bad = [r for r in rows if r['outside'] is True]; unknown = [r for r in rows if r['outside'] is None]
        print(f'{len(rows)} running pods matched; {len(bad)} outside instantaneous CPU/RAM bands; {len(unknown)} unknown. Native admission not probed; GPU not measured.')
        def percent(value):
            return 'unknown' if value is None else f'{100 * value:.1f}%'
        for row in sorted(bad + unknown, key=lambda r: r.get('cpu_ratio') or 0):
            print(f"  {row['name']} cpu={percent(row['cpu_ratio'])} mem={percent(row['memory_ratio'])}: " + '; '.join(row['usage_notes']))
    return exit_code(rows)


if __name__ == '__main__':
    raise SystemExit(main())
