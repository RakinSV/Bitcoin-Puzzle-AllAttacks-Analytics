#!/usr/bin/env python3
"""
BIG-KEY known-answer test for the GPU lottery kernel.

Why this exists: the published AMD/OpenCL benchmarks report that BitCrack's
OpenCL path "does not find keys (arithmetic bug)" on Radeon hardware. Our lottery
runs that vendored kernel, on OpenCL, on an AMD RX 6600 — and has been running
for days. The existing GPU tests only prove k=1 and k=777, i.e. values that touch
a single 32-bit word. A carry/propagation bug in 256-bit arithmetic would be
invisible there and fatal here.

So: plant REAL puzzle keys (60..70 bits, all 8 words live) inside the scanned
window and demand the engine actually reports them. If this fails, every hour the
lottery has spent is wasted and the whole approach must stop.

Run:  python tests/test_gpu_bigkey_kat.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.rng_analysis import KNOWN_KEYS
from ecc.curve import scalar_mul, G
from kangaroo.gpu_search import GPUSearchEngine
from utils.address import point_to_address, get_target_for_kernel


def _addr_for(k: int) -> str:
    x, y = scalar_mul(k, G)
    return point_to_address(x, y)


def kat_for_bits(bits: int, offset: int = 12345) -> bool:
    """Plant puzzle `bits`'s real key just inside the window and demand a hit."""
    k = KNOWN_KEYS[bits]
    addr = _addr_for(k)

    engine = GPUSearchEngine(device_idx=0, threads=64, blocks=128,
                             points_per_thread=8)
    engine.set_target(get_target_for_kernel(addr))

    # Start slightly BELOW the key so it lands inside the swept block.
    k_start = k - offset
    engine.initialize(k_start)
    span = engine.total_points

    found = None
    # The key sits at index `offset`, so it is hit within the first few steps.
    steps = max(2, offset // max(1, span) + 3)
    for _ in range(steps):
        for r in engine.step() or []:
            if r.get('k') == k:
                found = r
                break
        if found:
            break

    ok = found is not None
    print(f"  #{bits:>2} k={hex(k)} ({k.bit_length()} bits)  addr={addr[:12]}...  "
          f"-> {'FOUND [OK]' if ok else 'NOT FOUND  <<< ARITHMETIC BUG'}")
    del engine
    return ok


def main():
    print("=" * 74)
    print("  GPU LOTTERY — BIG-KEY known-answer test (256-bit arithmetic)")
    print("  Proves the kernel can actually report a real multi-word key.")
    print("=" * 74)
    results = {}
    for bits in (60, 65, 70):
        try:
            results[bits] = kat_for_bits(bits)
        except Exception as e:
            print(f"  #{bits}: ERROR {type(e).__name__}: {e}")
            results[bits] = False

    print("=" * 74)
    if all(results.values()):
        print("  ALL BIG-KEY KATs PASSED — the lottery kernel finds real keys on")
        print("  this AMD/OpenCL device. Time spent searching is genuinely working.")
    else:
        bad = [b for b, ok in results.items() if not ok]
        print(f"  FAILED at {bad} — the kernel does NOT report keys of this size.")
        print("  The lottery cannot win; stop it and fix the kernel arithmetic.")
    print("=" * 74)
    return 0 if all(results.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
