"""
Kangaroo algorithm tests — CPU and GPU (optional).

Verifies correctness of Pollard's Kangaroo on small puzzles where the answer
is known, then checks the GPU engine if OpenCL is available.

Usage:
  python tests/test_kangaroo.py           # all tests
  python tests/test_kangaroo.py --cpu     # CPU-only (no GPU needed)
  python -m pytest tests/test_kangaroo.py -v
"""

import sys
import os
import time
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ecc.curve import scalar_mul, G, N, point_neg, INF
from ecc.field import P


# ==============================================================
# Helpers
# ==============================================================

def make_pubkey(k: int):
    """Compute public key for known private key k."""
    return scalar_mul(k, G)


# ==============================================================
# Test 1: DP Table
# ==============================================================

def test_dp_table():
    """DPTable: insert, collision detection, persistence."""
    from utils.dp_table import DPTable

    dp = DPTable(dp_bits=4)   # 1/16 points stored

    # is_dp: x & 0xF == 0
    assert dp.is_dp(0),   "0 should be DP"
    assert dp.is_dp(16),  "16 should be DP"
    assert not dp.is_dp(1), "1 is not DP"
    assert not dp.is_dp(15), "15 is not DP"

    # add new entry → None (no collision)
    r = dp.add(32, 100, 'tame')
    assert r is None, "First insert should return None"
    assert len(dp) == 1

    # add same kind → None (pseudo-collision, ignored)
    r = dp.add(32, 200, 'tame')
    assert r is None, "Same-kind collision should return None"

    # add different kind → collision!
    r = dp.add(32, 150, 'wild')
    assert r is not None, "Different-kind should return collision tuple"
    other_dist, other_kind = r
    assert other_dist == 100
    assert other_kind == 'tame'

    # resolve_key math
    tame_start = 1000
    k = dp.resolve_key(tame_start, tame_dist=100, wild_dist=150)
    assert k == tame_start + 100 - 150, f"resolve_key wrong: {k}"

    print("[OK] DPTable: is_dp, add, collision detection, resolve_key")


# ==============================================================
# Test 2: CPU Kangaroo — trivial range (k=1, range [1,4])
# ==============================================================

def test_cpu_kangaroo_trivial():
    """CPU Kangaroo finds k=1 in range [1,4]."""
    from kangaroo.cpu import solve

    k_known  = 1
    pubkey   = make_pubkey(k_known)
    result   = solve(pubkey, k_start=1, k_end=4,
                     dp_bits=2, negation=False,
                     max_steps=50_000, verbose=False)
    assert result == k_known, f"Expected {k_known}, got {result}"
    print(f"[OK] CPU Kangaroo trivial: found k={k_known}")


# ==============================================================
# Test 3: CPU Kangaroo — puzzle #2 (k in [2,3])
# ==============================================================

def test_cpu_kangaroo_puzzle2():
    """CPU Kangaroo on 2-bit range [2,3]."""
    from kangaroo.cpu import solve

    # Puzzle #2: k is in [2,3]
    for k_known in [2, 3]:
        pubkey = make_pubkey(k_known)
        result = solve(pubkey, k_start=2, k_end=3,
                       dp_bits=2, negation=True,
                       max_steps=100_000, verbose=False)
        assert result == k_known, f"Expected {k_known}, got {result}"
        print(f"[OK] CPU Kangaroo puzzle#2: found k={k_known}")


# ==============================================================
# Test 4: CPU Kangaroo — puzzle #5 (5-bit range [16,31])
# ==============================================================

def test_cpu_kangaroo_puzzle5():
    """CPU Kangaroo on 5-bit range [16,31]."""
    from kangaroo.cpu import solve

    k_known = 17   # arbitrary key in range
    pubkey  = make_pubkey(k_known)
    result  = solve(pubkey, k_start=16, k_end=31,
                    dp_bits=4, negation=True,
                    max_steps=500_000, verbose=False)
    assert result == k_known, f"Expected {k_known}, got {result}"
    print(f"[OK] CPU Kangaroo 5-bit: found k={k_known}")


# ==============================================================
# Test 5: CPU Kangaroo — 10-bit range
# ==============================================================

def test_cpu_kangaroo_10bit():
    """CPU Kangaroo on 10-bit range [512, 1023]."""
    from kangaroo.cpu import solve

    k_known  = 777
    k_start  = 512
    k_end    = 1023
    pubkey   = make_pubkey(k_known)

    t0     = time.perf_counter()
    result = solve(pubkey, k_start=k_start, k_end=k_end,
                   dp_bits=5, negation=True,
                   max_steps=2_000_000, verbose=False)
    elapsed = time.perf_counter() - t0

    assert result == k_known, f"Expected {k_known}, got {result}"
    print(f"[OK] CPU Kangaroo 10-bit: found k={k_known} in {elapsed:.3f}s")


# ==============================================================
# Test 6: CPU Kangaroo — 20-bit range
# ==============================================================

def test_cpu_kangaroo_20bit():
    """CPU Kangaroo on 20-bit range [2^19, 2^20-1]. ~150K steps."""
    from kangaroo.cpu import solve

    k_known  = 2**19 + 2**18 + 12345
    k_start  = 2**19
    k_end    = 2**20 - 1
    pubkey   = make_pubkey(k_known)

    t0     = time.perf_counter()
    result = solve(pubkey, k_start=k_start, k_end=k_end,
                   dp_bits=8, negation=True,
                   max_steps=10_000_000, verbose=False)
    elapsed = time.perf_counter() - t0

    assert result == k_known, f"Expected {k_known}, got {result}"
    speed  = int(2.5 * (k_end - k_start + 1) ** 0.5) / elapsed
    print(f"[OK] CPU Kangaroo 20-bit: found k={k_known} in {elapsed:.2f}s "
          f"(~{speed/1000:.0f}K steps/sec)")


# ==============================================================
# Test 7: Key recovery math
# ==============================================================

def test_key_recovery_math():
    """Verify the Kangaroo key recovery formula directly."""
    from kangaroo.cpu import _recover_key, _verify

    # Choose a known key and simulate a tame/wild collision
    k_real   = 123456789
    k_start  = 100_000_000
    k_end    = 200_000_000
    pubkey   = make_pubkey(k_real)

    # Simulate: tame starts at tame_start, wild starts at k_real
    # They meet after tame_dist and wild_dist hops
    tame_start = k_start + (k_end - k_start) // 2

    # Choose distances such that tame_start + tame_dist = k_real + wild_dist
    # => wild_dist = tame_dist + tame_start - k_real
    tame_dist  = 50_000
    wild_dist  = tame_dist + tame_start - k_real

    k = _recover_key(tame_start, tame_dist, wild_dist, 'wild',
                     k_end - k_start + 1, k_start, k_end, pubkey, N)
    assert k == k_real, f"Key recovery failed: got {k}, expected {k_real}"
    print(f"[OK] Key recovery math: k={k_real} recovered correctly")

    # Verify function
    assert _verify(k_real, pubkey, k_start, k_end), "_verify should return True"
    assert not _verify(k_real + 1, pubkey, k_start, k_end), "_verify should return False for wrong k"
    print("[OK] _verify: True for correct k, False for wrong k")


# ==============================================================
# Test 8: Negation trick math
# ==============================================================

def test_negation_math():
    """Verify that negation kangaroo recovers k from -Q."""
    k_real  = 999_888_777
    pubkey  = make_pubkey(k_real)
    neg_pub = point_neg(pubkey)

    # -Q = (N-k)*G, so neg_wild starts at (N-k)*G
    # At collision: tame_start + tame_dist == (N-k) + neg_dist
    # => N-k = tame_start + tame_dist - neg_dist
    # => k   = N - (tame_start + tame_dist - neg_dist)
    k_start    = 900_000_000
    k_end      = 1_100_000_000
    tame_start = k_start + (k_end - k_start) // 2
    neg_k      = (N - k_real) % N

    # Simulate distances so tame_pos = neg_pos
    tame_dist = 1_000_000
    neg_dist  = tame_dist + tame_start - neg_k

    k_neg = (tame_start + tame_dist - neg_dist) % N
    k_candidate = (N - k_neg) % N

    assert k_candidate == k_real, (
        f"Negation recovery failed: got {k_candidate}, expected {k_real}")
    print(f"[OK] Negation math: k={k_real} recovered from -Q")


# ==============================================================
# Test 9: GPU Kangaroo — trivial range (if OpenCL available)
# ==============================================================

def test_gpu_kangaroo_trivial():
    """GPU KangarooEngine finds k in 15-bit range [2^14, 2^15-1].

    Note: 5-bit range (32 keys) is too small for GPU Kangaroo because the
    mean jump distance (~sqrt(32)/2 ~= 2) is comparable to the range itself,
    and n_tame=64 > range_size=32 causes repeated starting positions.
    15-bit range gives a well-conditioned test that runs in < 1 second.
    """
    try:
        import pyopencl as cl
        platforms = cl.get_platforms()
        devices   = [d for p in platforms for d in p.get_devices(cl.device_type.GPU)]
        if not devices:
            print("[SKIP] GPU Kangaroo trivial: no OpenCL GPU found")
            return
    except ImportError:
        print("[SKIP] GPU Kangaroo trivial: pyopencl not installed")
        return

    from kangaroo.kangaroo_engine import KangarooEngine

    k_known = 2**14 + 4200    # 20584, well inside [16384, 32767]
    k_start = 2**14
    k_end   = 2**15 - 1
    pubkey  = make_pubkey(k_known)

    engine = KangarooEngine(
        pubkey  = pubkey,
        k_start = k_start,
        k_end   = k_end,
        n_tame  = 64,
        n_wild  = 64,
        dp_bits = 6,
    )
    t0     = time.perf_counter()
    result = engine.solve(verbose=True)
    elapsed = time.perf_counter() - t0

    assert result == k_known, f"GPU Kangaroo: expected {k_known}, got {result}"
    print(f"[OK] GPU Kangaroo 15-bit: found k={k_known} in {elapsed:.3f}s")


# ==============================================================
# Test 10: GPU Kangaroo — 20-bit range (if OpenCL available)
# ==============================================================

def test_gpu_kangaroo_20bit():
    """GPU KangarooEngine finds k in 20-bit range [2^19, 2^20-1]."""
    try:
        import pyopencl as cl
        platforms = cl.get_platforms()
        devices   = [d for p in platforms for d in p.get_devices(cl.device_type.GPU)]
        if not devices:
            print("[SKIP] GPU Kangaroo 20-bit: no OpenCL GPU found")
            return
    except ImportError:
        print("[SKIP] GPU Kangaroo 20-bit: pyopencl not installed")
        return

    from kangaroo.kangaroo_engine import KangarooEngine

    k_known  = 2**19 + 314159
    k_start  = 2**19
    k_end    = 2**20 - 1
    pubkey   = make_pubkey(k_known)

    engine = KangarooEngine(
        pubkey  = pubkey,
        k_start = k_start,
        k_end   = k_end,
        n_tame  = 1024,
        n_wild  = 1024,
        dp_bits = 8,
    )
    t0     = time.perf_counter()
    result = engine.solve(verbose=True)
    elapsed = time.perf_counter() - t0

    assert result == k_known, f"GPU Kangaroo 20-bit: expected {k_known}, got {result}"
    print(f"[OK] GPU Kangaroo 20-bit: found k={k_known} in {elapsed:.3f}s")


# ==============================================================
# Test 11: main.py _parse_pubkey_hex roundtrip
# ==============================================================

def test_parse_pubkey_hex():
    """_parse_pubkey_hex correctly decodes compressed and uncompressed pubkeys."""
    from main import _parse_pubkey_hex

    test_keys = [1, 2, 3, 42, 2**19 + 1, 2**70 + 12345]

    for k in test_keys:
        pt = make_pubkey(k)
        x, y = pt

        # Compressed (even y → 02, odd y → 03)
        prefix = 0x02 if y % 2 == 0 else 0x03
        comp   = bytes([prefix]) + x.to_bytes(32, 'big')
        px, py = _parse_pubkey_hex(comp.hex())
        assert (px, py) == (x, y), f"Compressed roundtrip failed for k={k}"

        # Uncompressed (04 prefix)
        uncomp = b'\x04' + x.to_bytes(32, 'big') + y.to_bytes(32, 'big')
        px, py = _parse_pubkey_hex(uncomp.hex())
        assert (px, py) == (x, y), f"Uncompressed roundtrip failed for k={k}"

    print(f"[OK] _parse_pubkey_hex: compressed & uncompressed ({len(test_keys)} keys)")


# ==============================================================
# Runner
# ==============================================================

CPU_TESTS = [
    ('DP Table',                   test_dp_table),
    ('CPU Kangaroo trivial [1,4]', test_cpu_kangaroo_trivial),
    ('CPU Kangaroo puzzle#2 [2,3]',test_cpu_kangaroo_puzzle2),
    ('CPU Kangaroo 5-bit [16,31]', test_cpu_kangaroo_puzzle5),
    ('CPU Kangaroo 10-bit',        test_cpu_kangaroo_10bit),
    ('CPU Kangaroo 20-bit',        test_cpu_kangaroo_20bit),
    ('Key recovery math',          test_key_recovery_math),
    ('Negation trick math',        test_negation_math),
    ('Parse pubkey hex',           test_parse_pubkey_hex),
]

GPU_TESTS = [
    ('GPU Kangaroo 15-bit',  test_gpu_kangaroo_trivial),
    ('GPU Kangaroo 20-bit',  test_gpu_kangaroo_20bit),
]

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cpu', action='store_true', help='Run CPU-only tests')
    args = parser.parse_args()

    tests = CPU_TESTS if args.cpu else CPU_TESTS + GPU_TESTS

    print("=" * 60)
    print("Kangaroo Tests")
    print("=" * 60)

    failed = []
    for name, fn in tests:
        print(f"\n--- {name} ---")
        try:
            fn()
        except Exception as e:
            import traceback
            print(f"[FAIL] {e}")
            traceback.print_exc()
            failed.append(name)

    print("\n" + "=" * 60)
    if not failed:
        print(f"ALL {len(tests)} TESTS PASSED [OK]")
    else:
        print(f"FAILED ({len(failed)}):")
        for t in failed:
            print(f"  - {t}")
    sys.exit(len(failed))
