#!/usr/bin/env python3
"""
Regression tests for Kangaroo key reconstruction.

The bug: a DP records only the x-coordinate, and x is shared by a point and its
negation, so a collision means the two discrete logs match *up to sign*. The old
code tried exactly one formula per herd pair and threw wild/neg pairs away, so
real collisions produced garbage keys (256-bit values for a 40-bit puzzle), the
candidate failed verification, and the search ran forever without reporting.

Why the existing suite missed it: tests/test_kangaroo.py only covers 15/20-bit
puzzles, where 24576 kangaroos saturate the whole interval by brute force. The
sqrt-scaling collision/reconstruction path is never exercised there.

These tests check the reconstruction algebra directly (no GPU needed).

Run:  python tests/test_kangaroo_recovery.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ecc.curve import scalar_mul, G, N as ORDER      # noqa: E402
from kangaroo.kangaroo_engine import KangarooEngine   # noqa: E402

FAILS = []


def check(name, cond):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILS.append(name)


class _Recon:
    """Reconstruction logic under test, without touching the GPU."""

    def __init__(self, k_true, k_start, k_end, tame_base):
        self.pubkey = scalar_mul(k_true, G)
        self.k_start, self.k_end = k_start, k_end
        self._tame_base = tame_base

    _herd_affine = KangarooEngine._herd_affine
    _try_recover = KangarooEngine._try_recover


def _hit(kind_int, dist):
    return {'kind': kind_int, 'dist': dist}


def run_case(name, k_true, this_kind, other_kind, mk_this, mk_other):
    """Build a genuine collision and assert k is recovered."""
    k_start, k_end = 2 ** 39, 2 ** 40 - 1
    tame_base = k_start + (k_end - k_start) // 2
    r = _Recon(k_true, k_start, k_end, tame_base)
    d_this = mk_this(k_true, tame_base)
    d_other = mk_other(k_true, tame_base)
    got = r._try_recover(_hit(this_kind, d_this), (d_other, other_kind), None)
    check(f"{name}: recovers k", got == k_true)


if __name__ == "__main__":
    print("=" * 62)
    print("  Kangaroo key-reconstruction regression tests")
    print("=" * 62)
    K = 0xE9AE4933D6                      # real puzzle #40 key
    KS, KE = 2 ** 39, 2 ** 40 - 1
    TB = KS + (KE - KS) // 2

    print("\n--- tame x wild, same sign  (T = k + wd) ---")
    # tame value  T = TB + td ; wild value W = K + wd ; make them equal
    td = 1_000_000
    run_case("tame/wild +", K, 0, 'wild',
             lambda k, tb: td, lambda k, tb: (tb + td) - k)

    print("\n--- tame x neg, opposite sign  (T = k - nd) ---")
    # neg value Ng = -k + nd ; x-collision with T means T = -Ng  => T = k - nd
    run_case("tame/neg -", K, 0, 'neg',
             lambda k, tb: td, lambda k, tb: k - (tb + td))

    print("\n--- tame x neg, same sign  (T = -k + nd) ---")
    run_case("tame/neg +", K, 0, 'neg',
             lambda k, tb: td, lambda k, tb: (tb + td) + k)

    print("\n--- wild x neg  (the negation map's own collision) ---")
    # W = k + wd, Ng = -k + nd ; equal => nd = 2k + wd
    wd = 12345
    r = _Recon(K, KS, KE, TB)
    got = r._try_recover(_hit(1, wd), (2 * K + wd, 'neg'), None)
    check("wild/neg: recovers k", got == K)

    print("\n--- a bogus collision must be rejected, not returned ---")
    r = _Recon(K, KS, KE, TB)
    check("garbage pair -> None", r._try_recover(_hit(0, 7), (999_999, 'wild'), None) is None)

    print("\n--- herd algebra ---")
    r = _Recon(K, KS, KE, TB)
    check("tame is 0*k + (tame_base+dist)", r._herd_affine('tame', 5) == (0, (TB + 5) % ORDER))
    check("wild is 1*k + dist", r._herd_affine('wild', 5) == (1, 5))
    check("neg is -1*k + dist", r._herd_affine('neg', 5) == (ORDER - 1, 5))

    print("\n" + "=" * 62)
    if FAILS:
        print(f"  {len(FAILS)} FAILED: {FAILS}")
        sys.exit(1)
    print("  ALL KANGAROO RECOVERY TESTS PASSED [OK]")
