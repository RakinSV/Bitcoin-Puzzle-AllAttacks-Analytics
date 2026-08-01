#!/usr/bin/env python3
"""
Guard the >64-bit interval fix.

The engine used to seed each kangaroo's distance with its starting offset, and
that offset spans the whole interval. For any interval wider than 2^64 — i.e.
every puzzle above #65, *including #71, the target this project exists for* — the
value did not fit the kernel's ulong and initialize() died with
`OverflowError: int too big to convert`. Every ladder test we had ran below 65
bits, so nothing caught it.

The offsets now live on the host as unbounded ints and reach the kernel as two
64-bit words; the GPU accumulates only the walk (~2^56 for #71, comfortably
inside a ulong) and _read_dp adds the offset back by thread id.

These tests pin both halves: that wide intervals initialise at all, and that the
positions they produce are still exactly right.
"""
import os
import random
import sys

import numpy as np
import pyopencl as cl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ecc.curve import scalar_mul, G, N
from kangaroo.kangaroo_engine import KangarooEngine, _u256_to_int


def test_initialises_above_65_bits():
    """#66 and up must initialise; #71 is the one that actually matters."""
    for bits in (65, 66, 71, 120):
        k = 2 ** (bits - 1) + 0xABCDEF
        eng = KangarooEngine(scalar_mul(k, G), 2 ** (bits - 1), 2 ** bits - 1)
        eng.initialize()
        assert len(eng._offsets) == eng.n_total
        assert max(eng._offsets) > 0
        del eng
    print("  [OK] initialises at 65 / 66 / 71 / 120 bits")


def test_offsets_actually_exceed_64_bits_at_71():
    """The regression only bites when offsets really are wider than a ulong."""
    eng = KangarooEngine(scalar_mul(2 ** 70 + 7, G), 2 ** 70, 2 ** 71 - 1)
    eng.initialize()
    big = [o for o in eng._offsets if o >= 2 ** 64]
    assert big, "no offset exceeded 2^64 — this test would pass vacuously"
    print(f"  [OK] {len(big):,}/{len(eng._offsets):,} offsets exceed 2^64 "
          f"(max {max(eng._offsets).bit_length()} bits)")
    del eng


def test_positions_are_exact_at_71_bits():
    """Every kangaroo must sit at exactly (origin + offset)*G."""
    k = 0x349B84B6431A6C4EF1ABC              # arbitrary 71-bit scalar
    lo, hi = 2 ** 70, 2 ** 71 - 1
    eng = KangarooEngine(scalar_mul(k, G), lo, hi)
    eng.initialize()

    n = eng.n_total
    px = np.zeros(n * 8, dtype=np.uint32)
    py = np.zeros(n * 8, dtype=np.uint32)
    kd = np.zeros(n, dtype=np.int32)
    cl.enqueue_copy(eng.queue, px, eng.px_buf)
    cl.enqueue_copy(eng.queue, py, eng.py_buf)
    cl.enqueue_copy(eng.queue, kd, eng.kind_buf)
    eng.queue.finish()

    bad = 0
    for tid in random.sample(range(n), 40):
        x = _u256_to_int(px[tid * 8:tid * 8 + 8])
        y = _u256_to_int(py[tid * 8:tid * 8 + 8])
        kind = int(kd[tid])
        origin = lo if kind == 0 else (k if kind == 1 else N - k)
        if (x, y) != scalar_mul((origin + eng._offsets[tid]) % N, G):
            bad += 1
    assert bad == 0, f"{bad}/40 kangaroos are at the wrong point"
    print("  [OK] 40 sampled kangaroos sit at exactly (origin + offset)*G")
    del eng


def test_small_herd_is_accepted():
    """A herd whose work-item count is not a multiple of 64 must still run.

    768 kangaroos / K_BATCH 16 = 48 work-items. This used to raise ValueError
    even though the kernel already discards surplus threads.
    """
    k = 0xCCB2F
    eng = KangarooEngine(scalar_mul(k, G), 2 ** 19, 2 ** 20 - 1,
                         n_tame=256, n_wild=256)
    assert (eng.n_total // eng._k_batch) % 64 != 0, "pick a herd that is not aligned"
    got = eng.solve(max_iter=40000, verbose=False)
    assert got == k, f"small herd solved to {got}, want {hex(k)}"
    print(f"  [OK] 768-kangaroo herd ({eng.n_total // eng._k_batch} work-items) "
          f"solved {hex(got)}")
    del eng


if __name__ == '__main__':
    print("=" * 66)
    print("  WIDE-INTERVAL / SMALL-HERD REGRESSION GUARDS")
    print("=" * 66)
    test_initialises_above_65_bits()
    test_offsets_actually_exceed_64_bits_at_71()
    test_positions_are_exact_at_71_bits()
    test_small_herd_is_accepted()
    print("=" * 66)
    print("  ALL WIDE-INTERVAL TESTS PASSED [OK]")
    print("=" * 66)
