#!/usr/bin/env python3
"""
K-FACTOR harness — measure K = hops / sqrt(W) and find what drives it.

RCKangaroo's SOTA method reaches K=1.15 (classic 3-way kangaroo is ~2.1). Our
engine measures K=6.5 at #58 but K=45 at #45, a 7x spread that no algorithm
constant explains — so something CONFIGURED is wrong, not just the method.

Hypothesis: K is driven by the ratio m/sqrt(W) (herd size vs the walk length the
problem actually needs). A herd of 49152 is absurd for #45 (sqrt(W)=4.2e6 means
each kangaroo takes ~85 steps -- pure overhead) but sensible for #71
(sqrt(W)=3.4e10 -> ~700k steps each). If true, K at a GIVEN ratio is what
predicts #71, and we can pick the herd that minimises K instead of guessing.

This measures K across (puzzle, herd) so we can read K as a function of the
ratio, and pick the optimum. Run:  python tests/_k_factor.py
"""
import os
import sys
import math
import time
import statistics

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ecc.curve import scalar_mul, G
from analysis.rng_analysis import KNOWN_KEYS
from kangaroo.kangaroo_engine import KangarooEngine


def measure_K(bits: int, n_tame: int, reps: int = 3, max_iter: int = 40000):
    """Solve puzzle `bits` with herd 3*n_tame; return list of K values."""
    k = KNOWN_KEYS[bits]
    pub = scalar_mul(k, G)
    lo, hi = 2 ** (bits - 1), 2 ** bits - 1
    sqrtW = math.sqrt(hi - lo + 1)
    Ks, rate = [], None
    for _ in range(reps):
        eng = KangarooEngine(pub, lo, hi, n_tame=n_tame, n_wild=n_tame,
                             use_mb=True)
        hpc = eng.hops_per_call()
        t0 = time.time()
        found = eng.solve(max_iter=max_iter, verbose=False)
        dt = time.time() - t0
        if found != k:
            del eng
            return None, None
        # hops actually executed = calls * hops_per_call; recover calls from time
        # is unreliable, so re-derive from the engine's own iteration counter.
        hops = eng._iteration * hpc
        Ks.append(hops / sqrtW)
        rate = hops / dt / 1e6
        del eng
    return Ks, rate


def main():
    print("=" * 78)
    print("  K-FACTOR — K = hops/sqrt(W).  classic=2.1   SOTA(RCKangaroo)=1.15")
    print("=" * 78)
    print(f"  {'#':>3} {'herd':>7} {'m/sqrtW':>10} {'K median':>9} "
          f"{'Mhop/s':>8}  runs")
    rows = []
    # Sweep herd size per puzzle; small herds probe the ratio #71 will live at.
    plan = [
        (45, [192, 768, 3072, 16384]),
        (50, [192, 768, 3072, 16384]),
        (55, [192, 768, 3072, 16384]),
    ]
    for bits, herds in plan:
        sqrtW = math.sqrt(2 ** (bits - 1))
        for nt in herds:
            m = 3 * nt
            try:
                Ks, rate = measure_K(bits, nt, reps=2)
            except Exception as e:
                print(f"  {bits:>3} {m:>7} -> ERROR {type(e).__name__}: {e}")
                continue
            if not Ks:
                print(f"  {bits:>3} {m:>7} -> unsolved in budget")
                continue
            med = statistics.median(Ks)
            rows.append((bits, m, m / sqrtW, med, rate))
            print(f"  {bits:>3} {m:>7} {m/sqrtW:>10.2e} {med:>9.2f} "
                  f"{rate:>8.0f}  {[round(x,1) for x in Ks]}", flush=True)

    if rows:
        print("=" * 78)
        best = min(rows, key=lambda r: r[3])
        print(f"  best K={best[3]:.2f} at #{best[0]} herd={best[1]} "
              f"(m/sqrtW={best[2]:.2e})")
        print("  -> for #71 (sqrtW=3.4e10) the same ratio means herd ~"
              f"{best[2] * 2**35:,.0f}")
    print("=" * 78)


if __name__ == '__main__':
    main()
