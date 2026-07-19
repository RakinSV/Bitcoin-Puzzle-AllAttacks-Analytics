#!/usr/bin/env python3
"""
Abstract herd-kangaroo MODEL — design harness (not the product).

Models the walk in SCALAR space (each kangaroo = its discrete log, an integer)
with a pseudo-random jump function of the point's x-coordinate. This is standard
for analysing kangaroo geometry: it reproduces the collision dynamics without the
cost of real EC point math, so it runs ~1000x faster and lets us test real herd
sizes at 40-50 bits.

Key modelling facts (faithful to the GPU algorithm):
  * a point P=s*G and -P=(N-s)*G share the same x. The jump index and the DP test
    both depend on x, so they depend on the "x-representative" xr(s)=min(s,N-s).
  * two kangaroos are "at the same point" (a collision) iff xr(s1)==xr(s2).
  * tame scalar = tame_base + dist ; wild = k + dist ; neg = (N - k) + dist.

DPs are recorded the moment they occur (no batch-boundary phase penalty), so this
isolates the herd GEOMETRY (time-to-collision) from the detection issue.

Usage:  python tests/_herd_model.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ecc.curve import N as ORDER
from analysis.rng_analysis import KNOWN_KEYS

N_JUMP = 32
_HALF = ORDER // 2


def _mix(z):
    """splitmix64 — a fast, good scalar hash to stand in for x-coordinate bits."""
    z = (z + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return z ^ (z >> 31)


def xr(s):
    s %= ORDER
    return s if s <= _HALF else ORDER - s


def build_dists(W):
    mean = max(N_JUMP, int(W ** 0.5) // 2)
    return [max(1, mean * (2 * i + 1) // N_JUMP) for i in range(N_JUMP)]


def run(bits, m, layout, dp_bits, cap_mult=300.0, spacing_mode="tile", k=None):
    import random as _r
    k_start, k_end = 2 ** (bits - 1), 2 ** bits - 1
    if k is None:
        k = KNOWN_KEYS[bits]
    W = k_end - k_start + 1
    dists = build_dists(W)
    dp_mask = (1 << dp_bits) - 1

    W = k_end - k_start + 1
    if layout == "clustered":
        spacing, tame_base = 1, k_start + W // 2
        offs = [i + 1 for i in range(m)]
    else:
        tame_base = k_start
        if spacing_mode == "tile":
            spacing = max(1, W // m)
            offs = [(i + 1) * spacing for i in range(m)]
        elif spacing_mode == "random":
            spacing = 0
            offs = [_r.randrange(0, W) for _ in range(m)]   # random spread
        else:
            spacing = max(1, int(W ** 0.5) // m)
            offs = [(i + 1) * spacing for i in range(m)]

    # each kangaroo: [scalar, kind, init_off]  (dist = scalar-origin, but we
    # store the offset so reconstruction gets the true accumulated distance)
    kang = []
    for off in offs:
        kang.append([(tame_base + off) % ORDER, 'tame'])
        kang.append([(k + off) % ORDER, 'wild'])
        kang.append([(ORDER - k + off) % ORDER, 'neg'])

    def origin(kind):
        return {'tame': tame_base, 'wild': k, 'neg': ORDER - k}[kind]

    table = {}
    hops = 0
    coll = 0
    cap = int(cap_mult * (W ** 0.5))
    while hops < cap:
        for kg in kang:
            s, kind = kg
            r = xr(s)
            h = _mix(r)
            if (h & dp_mask) == 0:
                prev = table.get(r)
                if prev is not None and prev[1] != kind:
                    coll += 1
                    kk = _recover(prev, (s - origin(kind), kind), tame_base, k)
                    if kk == k:
                        return True, hops, coll
                elif prev is None:
                    table[r] = (s - origin(kind), kind)   # store dist
            idx = (h >> 17) % N_JUMP
            kg[0] = (s + dists[idx]) % ORDER
            hops += 1
    return False, hops, coll


def _recover(a, b, tame_base, k_true):
    """a,b = (dist, kind) → solve a1*k+b1 == ±(a2*k+b2)."""
    def aff(kind, d):
        if kind == 'tame':
            return 0, (tame_base + d) % ORDER
        if kind == 'wild':
            return 1, d % ORDER
        return ORDER - 1, d % ORDER          # neg: -k + d
    a1, b1 = aff(a[1], a[0])
    a2, b2 = aff(b[1], b[0])
    for sgn in (1, ORDER - 1):
        A = (a1 - sgn * a2) % ORDER
        B = (sgn * b2 - b1) % ORDER
        if A:
            kk = (B * pow(A, -1, ORDER)) % ORDER
            if kk == k_true:
                return kk
    return None


if __name__ == "__main__":
    import time, random, statistics
    random.seed(1)
    print("=" * 78)
    print("  Herd geometry SCALING — mean hops/sqrtW over random keys (m=512)")
    print("  If spread stays BOUNDED as bits grow -> O(sqrt(W)) -> port to GPU")
    print("=" * 78, flush=True)
    m = 512
    import math as _m
    for bits in (32, 36, 40, 44):
        W = 2 ** (bits - 1)
        s = W ** 0.5
        # Optimal DP: 2^dp ~ sqrt(W)/m  (balances collision cost vs detection tail).
        dp = max(1, int(round((bits - 1) / 2 - _m.log2(m))))
        print(f"\n--- {bits} bits (sqrtW={s:,.0f}, dp={dp}) ---", flush=True)
        for layout, mode in (("spread", "tile"), ("spread", "random"), ("clustered", "")):
            mult = []
            unsolved = 0
            t = time.time()
            for _ in range(4):
                k = random.randrange(2 ** (bits - 1), 2 ** bits)
                ok, hops, c = run(bits, m, layout, dp, cap_mult=120,
                                  spacing_mode=mode or "tile", k=k)
                if ok:
                    mult.append(hops / s)
                else:
                    unsolved += 1
                if time.time() - t > 60:      # keep each layout under ~1 min
                    break
            name = f"{layout}/{mode}" if mode else layout
            if mult:
                print(f"  {name:<16}: mean {statistics.mean(mult):5.1f}*sqrtW "
                      f"(n={len(mult)}, {unsolved} unsolved)  [{time.time()-t:.0f}s]", flush=True)
            else:
                print(f"  {name:<16}: ALL {unsolved} UNSOLVED  [{time.time()-t:.0f}s]", flush=True)
