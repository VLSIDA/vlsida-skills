#!/usr/bin/env python3
"""How many new Pods may start now without a startup burst. Local pacing heuristic, not NRP policy.

Input: `band_check.py --json` rows, or any list of rows with name, phase,
created_at, outside, cpu_ratio and memory_ratio (nrp_common.compact_pod). A Pod
holds a startup slot while it is Pending, or Running for less than --window
seconds and not yet measured inside the CPU/RAM bands (no metrics, or outside).
Young Pods already working in band do not. band_check lists Running Pods only,
so pass the number of your Pending Pods with --pending.

    cap   = clamp(floor(fraction * running), floor, ceiling)
    allow = max(0, cap - holding)

Why (2026-10, one account): low-utilization admission refusals followed bursts
of short, setup-dominated Pods. In the 15 minutes before each refusal, about a
third to a half of the account's Pods were young; hours without refusals had at
most about a sixth. Each refusal blocked every new Pod for 1-4 hours. Pacing
starts by account size kept the fill growing without re-triggering them. The
defaults are that study's values: tune them per workload and report the rule as
your own pacing, never as a cluster limit. Never contacts the cluster.
"""
import argparse
import json
import math
import sys
import time

from nrp_common import timestamp


def holds_slot(row, now, window):
    """True for a Pending Pod, or a Running Pod that is young and not measured in band."""
    if row.get('phase') == 'Pending':
        return True
    if row.get('phase') != 'Running':
        return False
    try:
        age = now - timestamp(row['created_at'])
    except (KeyError, AttributeError, ValueError, TypeError):
        return True                                  # unknown age: count it
    if not 0 <= age < window:
        return False
    measured = all(isinstance(row.get(k), (int, float)) for k in ('cpu_ratio', 'memory_ratio'))
    return not (measured and row.get('outside') is False)


def start_budget(rows, now=None, window=900, fraction=0.25, floor=8, ceiling=40, pending=0):
    now = time.time() if now is None else now
    running = sum(1 for r in rows if r.get('phase') == 'Running')
    holding = sorted(str(r.get('name')) for r in rows if holds_slot(r, now, window))
    cap = max(floor, min(ceiling, int(math.floor(fraction * running))))
    used = len(holding) + pending
    return {'running': running, 'holding': used, 'cap': cap, 'allow': max(0, cap - used),
            'holding_pods': holding, 'pending_outside_rows': pending, 'window_s': window,
            'fraction': fraction, 'floor': floor, 'ceiling': ceiling,
            'note': 'local pacing heuristic; native admission still decides'}


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('rows', nargs='?', help='band_check.py --json output (default: stdin)')
    p.add_argument('--pending', type=int, default=0, help='own Pending Pods not in the rows')
    p.add_argument('--window', type=float, default=900, help='startup window, seconds (example: 900)')
    p.add_argument('--fraction', type=float, default=0.25, help='share of running Pods (example: 0.25)')
    p.add_argument('--floor', type=int, default=8, help='minimum cap (example: 8)')
    p.add_argument('--ceiling', type=int, default=40, help='maximum cap (example: 40)')
    args = p.parse_args()
    with (open(args.rows) if args.rows else sys.stdin) as stream:
        rows = json.load(stream)
    print(json.dumps(start_budget(rows, window=args.window, fraction=args.fraction, floor=args.floor,
                                  ceiling=args.ceiling, pending=args.pending), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
