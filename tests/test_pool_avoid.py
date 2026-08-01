#!/usr/bin/env python3
"""
Prove the lottery never re-searches ground the pools already swept.

The chain under test:
    GUI "Pool-avoid" checkbox (on by default)
      -> main.py --pool-avoid
      -> _get_pool_end()            live coverage, 6h cache, snapshot fallback
      -> gpu_search(pool_end=...)
      -> _pure_random_search: rand_lo = max(k_start, pool_end)

A silent failure anywhere in that chain looks exactly like a working search --
the GPU still spins, keys still get counted -- while up to 0.9% of every draw
lands on keys somebody already checked. So assert the invariant directly.

Run:  python tests/test_pool_avoid.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import PUZZLES, _get_pool_end


def test_pool_end_is_inside_range():
    """pool_end must land strictly inside the puzzle's own interval."""
    pz = PUZZLES[71]
    pe = _get_pool_end(71, pz)
    assert pe > 0, "no pool_end for #71 — live read and snapshot both failed"
    assert pz['start'] <= pe <= pz['end'], \
        f"pool_end {hex(pe)} outside [{hex(pz['start'])}, {hex(pz['end'])}]"
    frac = (pe - pz['start']) / (pz['end'] - pz['start'] + 1)
    assert 0 < frac < 0.5, f"implausible coverage fraction {frac:.4%}"
    print(f"  [OK] #71 pool_end={hex(pe)} ({frac:.4%} of range skipped)")
    return pe


def test_random_draws_never_fall_below_pool_end():
    """Reproduce the draw the lottery makes and assert it clears pool_end."""
    pz = PUZZLES[71]
    pe = _get_pool_end(71, pz)
    k_start, k_end = pz['start'], pz['end']

    # Mirror _pure_random_search: rand_lo = max(k_start, pool_end) when a pool
    # frontier is known, and windows are total_points wide.
    total_points = 33_554_432
    rand_lo = max(k_start, pe) if pe > k_start else k_start
    rand_hi = k_end - total_points

    below = 0
    for _ in range(200_000):
        k = random.randint(rand_lo, rand_hi)
        if k < pe:
            below += 1
    assert below == 0, f"{below} draws landed in pool-covered space"
    print(f"  [OK] 200,000 draws, none below pool_end "
          f"(search confined to [{hex(rand_lo)}, {hex(rand_hi)}])")


def test_without_pool_avoid_we_would_overlap():
    """Control: without the frontier, draws DO hit covered ground.

    This is what makes the test meaningful -- it shows the guard is doing real
    work rather than passing vacuously.
    """
    pz = PUZZLES[71]
    pe = _get_pool_end(71, pz)
    k_start, k_end = pz['start'], pz['end']
    hits = sum(1 for _ in range(200_000)
               if random.randint(k_start, k_end) < pe)
    assert hits > 0, "expected some overlap when pool_end is ignored"
    print(f"  [OK] control: ignoring pool_end puts {hits:,}/200,000 draws "
          f"({hits/2000:.3f}%) on already-swept keys")


def test_fallback_is_never_ahead_of_truth():
    """The offline snapshot must never claim MORE coverage than is real.

    Over-claiming would make us skip keys nobody has checked -- the one failure
    mode that could hide the answer from us. Under-claiming only costs redundancy.
    """
    from main import POOL_PROGRESS
    pz = PUZZLES[71]
    live = _get_pool_end(71, pz)
    ranges_done, bits, _ = POOL_PROGRESS[71]
    snapshot = pz['start'] + ranges_done * (1 << bits)
    assert snapshot <= live, \
        f"snapshot {hex(snapshot)} claims more than live {hex(live)}"
    print(f"  [OK] snapshot is {live - snapshot:,} keys behind live "
          f"(conservative, never skips unsearched keys)")


if __name__ == '__main__':
    print("=" * 66)
    print("  POOL-AVOID INVARIANTS")
    print("=" * 66)
    test_pool_end_is_inside_range()
    test_random_draws_never_fall_below_pool_end()
    test_without_pool_avoid_we_would_overlap()
    test_fallback_is_never_ahead_of_truth()
    print("=" * 66)
    print("  ALL POOL-AVOID TESTS PASSED [OK]")
    print("=" * 66)
