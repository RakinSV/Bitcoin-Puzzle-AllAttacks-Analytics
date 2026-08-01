#!/usr/bin/env python3
"""BSGS tests: it recovers real puzzle keys, and refuses impossible intervals."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ecc.curve import scalar_mul, G
from analysis.rng_analysis import KNOWN_KEYS
from utils.puzzle_registry import puzzle_range
from kangaroo.bsgs import solve_bsgs, feasible, table_size_for


def test_recovers_real_keys():
    for bits in (20, 25, 30):
        k = KNOWN_KEYS[bits]
        lo, hi = puzzle_range(bits)
        got = solve_bsgs(scalar_mul(k, G), lo, hi, verbose=False)
        assert got == k, f"#{bits}: got {got}, want {k}"
        print(f"  [OK] #{bits} recovered {hex(got)}")


def test_sign_ambiguity_is_handled():
    """The table is keyed by x, so both +j and -j must be tried.

    A key sitting in the upper half of a giant step is only found via the -j
    branch; without it the solver silently misses those keys.
    """
    lo, hi = puzzle_range(24)
    hits = 0
    for k in (KNOWN_KEYS[24], lo + 1, hi - 1, (lo + hi) // 2):
        got = solve_bsgs(scalar_mul(k, G), lo, hi, verbose=False)
        assert got == k, f"k={hex(k)} -> {got}"
        hits += 1
    print(f"  [OK] {hits} keys across the interval, including both ends")


def test_refuses_infeasible_interval():
    """A 140-bit interval must fail fast with MemoryError, not thrash."""
    lo, hi = puzzle_range(140)
    assert not feasible(lo, hi), "140-bit interval must be infeasible"
    try:
        solve_bsgs((1, 2), lo, hi, verbose=False)
    except MemoryError as e:
        assert 'Kangaroo' in str(e), "should point the user at Kangaroo"
        print(f"  [OK] #140 refused up front: needs "
              f"{table_size_for(lo, hi):.3e} entries")
        return
    raise AssertionError("expected MemoryError for a 140-bit interval")


def test_matches_kangaroo_on_the_same_target():
    """Cross-check: BSGS and the GPU engine must agree on the same key."""
    bits = 30
    k = KNOWN_KEYS[bits]
    lo, hi = puzzle_range(bits)
    pub = scalar_mul(k, G)
    bsgs_k = solve_bsgs(pub, lo, hi, verbose=False)
    try:
        from kangaroo.kangaroo_engine import KangarooEngine
        eng = KangarooEngine(pub, lo, hi)
        kang_k = eng.solve(max_iter=20000, verbose=False)
        del eng
    except Exception as e:                     # no GPU in this environment
        print(f"  [skip] Kangaroo unavailable ({type(e).__name__})")
        return
    assert bsgs_k == kang_k == k, f"BSGS {bsgs_k} vs Kangaroo {kang_k}"
    print(f"  [OK] BSGS and Kangaroo agree on #{bits}: {hex(k)}")


if __name__ == '__main__':
    print("=" * 62)
    print("  BSGS TESTS")
    print("=" * 62)
    test_recovers_real_keys()
    test_sign_ambiguity_is_handled()
    test_refuses_infeasible_interval()
    test_matches_kangaroo_on_the_same_target()
    print("=" * 62)
    print("  ALL BSGS TESTS PASSED [OK]")
    print("=" * 62)
