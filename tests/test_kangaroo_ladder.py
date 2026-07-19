#!/usr/bin/env python3
"""
Ladder regression test — the engine must solve REAL mid-size puzzles.

Before the random-spread fix the GPU Kangaroo stalled above ~40 bits: the herds
were clustered at two points, so work grew as n_total*sqrt(W) instead of
~sqrt(W), and the solver gave up before the collision. The fix spreads both
herds randomly across the interval (validated in tests/_herd_model.py: bounded
~10*sqrt(W)), which makes 40-50 bit puzzles solvable on one RX 6600.

This guards against regressing back to the clustered layout. It solves real
puzzle keys (30/38/42 bit) against their true public keys with the default
production config. Kangaroo is a Las Vegas algorithm, so a generous budget is
used; these sizes solve in seconds.

Run:  python tests/test_kangaroo_ladder.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.rng_analysis import KNOWN_KEYS          # noqa: E402
from ecc.curve import scalar_mul, G                    # noqa: E402
from kangaroo.kangaroo_engine import KangarooEngine    # noqa: E402

FAILS = []


def solve_bits(bits):
    k = KNOWN_KEYS[bits]
    Q = scalar_mul(k, G)
    e = KangarooEngine(pubkey=Q, k_start=2 ** (bits - 1), k_end=2 ** bits - 1)
    e.initialize()
    t = time.time()
    r = e.solve(verbose=False)
    dt = time.time() - t
    ok = (r == k)
    print(f"  [{'OK' if ok else 'FAIL'}] #{bits}: "
          f"{('recovered ' + hex(r)) if ok else 'NOT FOUND'}  ({dt:.0f}s)")
    if not ok:
        FAILS.append(bits)


if __name__ == "__main__":
    print("=" * 62)
    print("  Kangaroo ladder — solves real puzzles past the old 40-bit wall")
    print("=" * 62)
    for bits in (30, 38, 42):
        solve_bits(bits)
    print("=" * 62)
    if FAILS:
        # Las Vegas: a single unlucky run can miss. Retry the failures once.
        print(f"  retrying unlucky run(s): {FAILS}")
        retry, FAILS = FAILS, []
        for bits in retry:
            solve_bits(bits)
    if FAILS:
        print(f"  {len(FAILS)} FAILED after retry: {FAILS}")
        sys.exit(1)
    print("  ALL LADDER PUZZLES SOLVED [OK]")
