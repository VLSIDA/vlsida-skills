#!/usr/bin/env python3
"""Summarize a GCell congestion dump (examples/gcell_dump.tcl): all GCells and GCells outside macros.

    python3 gcell_stats.py grid.cong            # JSON on stdout
    python3 gcell_stats.py grid.cong --die-area-um2 3.2e7 --density 0.1229   # also check the predicted GCell count

Why outside macros: the saved GRT grid stores macro-blocked tracks as usage, so every GCell touching a macro reads
exactly 1.0 on its blocked layers. Statistics over all GCells then mostly measure macro area. "Outside macros" drops
every GCell whose rectangle intersects a macro outline.

GCell rectangles: GEXT holds the FIRST and LAST GCell origins (OpenROAD's getGridX/getGridY list origins), so the
pitch is (x1 - x0) / (n - 1) and the last GCell runs on to the die edge (gcd: 12 origins 0..31.35 um, die 36.725 um).
The Vastu checkout's congestion_heatmap.py and its 2026-10 study divided by n instead, so their mask drifts by up to
one GCell toward the far edges. On saved nangate45 dumps that reclassified 0.1-0.4% of the GCells, mostly macro-edge
GCells reading 1.0, and raised cnn's outside-macro share at >= 0.99 from about 0.32% to 0.37%.

Why shares and not only p95: usage/capacity per GCell takes few distinct values (capacities are small track counts),
so p95 moves in steps (0.75, 0.8, 0.9, 1.0) and paired comparisons of p95 are almost always zero. The shares of
GCells at >= 0.9 and >= 0.99 separate arms far better. Overflow (> 1.0) counts all GCells; blockage alone never
exceeds 1.0.

Standard library only (numpy is used when importable, for speed). Quantiles are Type 7 (linear interpolation).
"""
import argparse
import json
import math
import sys
from array import array
from pathlib import Path


def parse(path):
    """(nx, ny, extent [x0,y0,x1,y1], values array('f') row-major from the bottom row, macros [[x0,y0,x1,y1]])."""
    nx = ny = None
    extent, macros, values, rows = None, [], array('f'), 0
    with Path(path).open() as f:
        for line in f:
            t = line.split()
            if not t:
                continue
            if t[0] == 'GRID':
                nx, ny = int(t[1]), int(t[2])
            elif t[0] == 'GEXT':
                extent = [float(x) for x in t[1:5]]
            elif t[0] == 'R':
                if nx is None or len(t) - 1 != nx:
                    raise ValueError('GCell row width differs from GRID')
                values.extend(float(x) for x in t[1:])
                rows += 1
            elif t[0] == 'MACRO':
                macros.append([float(x) for x in t[1:5]])
            else:
                raise ValueError('unknown record ' + t[0])
    if nx is None or extent is None or rows != ny or min(nx, ny) < 2:
        raise ValueError('incomplete GCell dump')
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError('invalid usage/capacity value')
    return nx, ny, extent, values, macros


def _span(lo, hi, origin, pitch, n):
    """GCell indices overlapped by [lo, hi]; GCell i covers [origin + i*pitch, origin + (i+1)*pitch), the last runs on."""
    if hi <= origin:
        return 0, -1
    first = min(n - 1, max(0, int(math.floor((lo - origin) / pitch))))
    last = min(n - 1, max(0, int(math.ceil((hi - origin) / pitch)) - 1))
    return first, last


def macro_mask(nx, ny, extent, macros):
    """bytearray, 1 where the GCell rectangle intersects any macro outline (extent = first and last GCell origins)."""
    x0, y0, x1, y1 = extent
    dx, dy = ((x1 - x0) / (nx - 1) if nx > 1 else math.inf), ((y1 - y0) / (ny - 1) if ny > 1 else math.inf)
    mask = bytearray(nx * ny)
    for mx0, my0, mx1, my1 in macros:
        i0, i1 = _span(mx0, mx1, x0, dx, nx)
        j0, j1 = _span(my0, my1, y0, dy, ny)
        if i1 < i0 or j1 < j0:
            continue
        for j in range(j0, j1 + 1):
            mask[j * nx + i0:j * nx + i1 + 1] = b'\x01' * (i1 - i0 + 1)
    return mask


def _quantile(sorted_values, q):
    n = len(sorted_values)
    h = (n - 1) * q
    lo = math.floor(h)
    return sorted_values[lo] + (h - lo) * (sorted_values[min(lo + 1, n - 1)] - sorted_values[lo])


def stats(values):
    if not len(values):
        return {'gcells': 0}
    try:
        import numpy as np
        a = np.frombuffer(values, dtype=np.float32) if isinstance(values, array) else np.asarray(values, dtype=np.float32)
        q = np.quantile(a, [0.5, 0.95, 0.99])
        return {'gcells': int(a.size), 'peak': float(a.max()), 'p99': float(q[2]), 'p95': float(q[1]), 'p50': float(q[0]),
                'mean': float(a.mean()), 'frac_ge_0_9': float((a >= 0.9).mean()), 'frac_ge_0_99': float((a >= 0.99).mean()),
                'frac_over_1': float((a > 1.0).mean()), 'frac_zero_capacity_demand': float((a == 1.5).mean())}
    except ImportError:
        s = sorted(values)
        n = len(s)
        return {'gcells': n, 'peak': s[-1], 'p99': _quantile(s, .99), 'p95': _quantile(s, .95), 'p50': _quantile(s, .5),
                'mean': sum(s) / n, 'frac_ge_0_9': sum(1 for v in s if v >= 0.9) / n,
                'frac_ge_0_99': sum(1 for v in s if v >= 0.99) / n, 'frac_over_1': sum(1 for v in s if v > 1.0) / n,
                'frac_zero_capacity_demand': sum(1 for v in s if v == 1.5) / n}


def summarize(path):
    nx, ny, extent, values, macros = parse(path)
    mask = macro_mask(nx, ny, extent, macros)
    outside = array('f', (v for v, m in zip(values, mask) if not m))
    return {'grid_shape': [nx, ny], 'extent_um': extent, 'macro_count': len(macros),
            'macro_gcell_fraction': sum(mask) / len(mask), 'all_gcells': stats(values), 'outside_macros': stats(outside)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('dump', type=Path)
    ap.add_argument('--die-area-um2', type=float, help='compare the GCell count with die area x density')
    ap.add_argument('--density', type=float, default=0.1229, help='GCells per um2 (nangate45 ORFS default measured 0.1222-0.1231)')
    a = ap.parse_args(argv)
    out = summarize(a.dump)
    if a.die_area_um2:
        out['predicted_gcells'] = a.die_area_um2 * a.density
        out['gcells_over_predicted'] = out['all_gcells']['gcells'] / out['predicted_gcells']
    print(json.dumps(out, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
