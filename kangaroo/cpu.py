"""
Pollard's Kangaroo algorithm — CPU reference implementation.

Sources synthesized:
  - Pons Kangaroo: tame/wild logic, jump table, DP detection
  - Docx ideas: negation map (x2), optimal step distribution, GLV

Requires the TARGET PUBLIC KEY (x, y) — cannot work without it.
Use for: small puzzles verification, testing before GPU port.

Algorithm summary:
  1. Build jump table: s[i] = 2^i * G  for i in 0..w-1
  2. Tame kangaroo: starts at tame_start*G, hops deterministically
  3. Wild kangaroo:  starts at Q = k*G (target pubkey), hops same rule
  4. When both hit a Distinguished Point with same x → collision → k found
  5. Negation trick: also run wild kangaroo from -Q simultaneously

Step function (Pons): step_idx = x_coord % w  →  jump by s[step_idx]
Expected steps to solution: ~2.5 * sqrt(range_size)
"""

import sys
import os
import time
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ecc.curve  import point_add, point_double, scalar_mul, point_neg, G, N, INF
from ecc.field  import P as FIELD_P
from utils.dp_table import DPTable


# ---------------------------------------------------------------------------
# Jump table construction
# ---------------------------------------------------------------------------

W_BITS = 5   # 2^5 = 32 different jump sizes


def build_jump_table(w: int = W_BITS,
                     k_start: int = 0, k_end: int = 0):
    """
    Build jump table with distances scaled to sqrt(range).

    Theory (Pollard Kangaroo):
      Optimal mean jump ≈ sqrt(range) / 2
      W = 2^w evenly-spaced distances in [mean/W … 2*mean - mean/W]
      → mean is exactly sqrt(range)/2  ✓

    Returns (jumps, dists):
      jumps[i] = dists[i] * G  (EC point)
      dists[i] = scalar distance
    """
    n   = 1 << w
    rng = (k_end - k_start + 1) if k_end > k_start else (1 << 64)
    # mean ≈ sqrt(range)/2  (floor, but at least n to avoid tiny jumps)
    mean = max(n, int(rng ** 0.5) // 2)
    # W evenly-spaced distances; smallest = mean/W, largest ≈ 2*mean - mean/W
    dists = [max(1, mean * (2 * i + 1) // n) for i in range(n)]
    jumps = [scalar_mul(d, G) for d in dists]
    return jumps, dists


# ---------------------------------------------------------------------------
# Core Kangaroo step
# ---------------------------------------------------------------------------

def _step_idx(pt, w: int = W_BITS) -> int:
    """Choose jump index deterministically from point's x-coordinate."""
    return pt[0] % (1 << w)


def _hop(pt, jumps: list, dists: list) -> tuple:
    """One kangaroo hop: returns (new_point, step_distance)."""
    idx  = _step_idx(pt)
    return point_add(pt, jumps[idx]), dists[idx]


# ---------------------------------------------------------------------------
# Main solver
# ---------------------------------------------------------------------------

def solve(pubkey: tuple, k_start: int, k_end: int,
          dp_bits: int = 14,
          negation: bool = True,
          max_steps: int = 0,
          verbose: bool = True) -> int | None:
    """
    Find k such that k*G == pubkey, k in [k_start, k_end].

    pubkey   : (x, y) EC point — the TARGET (must be known!)
    k_start  : lower bound of search range
    k_end    : upper bound of search range
    dp_bits  : DP filter (store 1/2^dp_bits points), default 14
    negation : also run wild kangaroo from -pubkey (doubles speed)
    max_steps: safety limit (0 = unlimited)

    Returns k (int) or None if not found within max_steps.
    """
    rng_size  = k_end - k_start + 1
    jumps, dists = build_jump_table(k_start=k_start, k_end=k_end)

    # Expected tame start: middle of range
    tame_start = k_start + rng_size // 2
    tame_pt    = scalar_mul(tame_start, G)

    # Wild kangaroo starts at the unknown target Q
    wild_pt    = pubkey
    wild_dist  = 0

    # Negation: second wild from -Q, corresponds to key N-k
    neg_pt     = point_neg(pubkey)
    neg_dist   = 0

    dp = DPTable(dp_bits=dp_bits)

    if max_steps == 0:
        max_steps = int(4 * (rng_size ** 0.5)) + 10_000_000

    if verbose:
        print(f"[Kangaroo] Range: 2^{rng_size.bit_length()-1}  "
              f"dp_bits={dp_bits}  negation={negation}")
        print(f"[Kangaroo] Tame start: {hex(tame_start)}")
        print(f"[Kangaroo] Expected steps: ~{int(2.5*(rng_size**0.5)):,}")

    tame_dist = 0
    t0 = time.time()

    for step in range(max_steps):
        # --- Tame kangaroo step ---
        tame_pt, td = _hop(tame_pt, jumps, dists)
        tame_dist  += td

        if dp.is_dp(tame_pt[0]):
            col = dp.add(tame_pt[0], tame_dist, 'tame')
            if col:
                other_dist, other_kind = col
                k = _recover_key(tame_start, tame_dist, other_dist,
                                 other_kind, rng_size, k_start, k_end, pubkey, N)
                if k is not None:
                    if verbose:
                        _print_found(k, step, time.time()-t0, dp)
                    return k

        # --- Wild kangaroo step ---
        wild_pt, wd = _hop(wild_pt, jumps, dists)
        wild_dist  += wd

        if dp.is_dp(wild_pt[0]):
            col = dp.add(wild_pt[0], wild_dist, 'wild')
            if col:
                other_dist, other_kind = col
                k = _recover_key(tame_start, other_dist if other_kind=='tame' else wild_dist,
                                 wild_dist if other_kind=='tame' else other_dist,
                                 'wild', rng_size, k_start, k_end, pubkey, N)
                if k is not None:
                    if verbose:
                        _print_found(k, step, time.time()-t0, dp)
                    return k

        # --- Negation wild step ---
        if negation:
            neg_pt, nd = _hop(neg_pt, jumps, dists)
            neg_dist  += nd

            if dp.is_dp(neg_pt[0]):
                col = dp.add(neg_pt[0], neg_dist, 'neg')
                if col:
                    other_dist, other_kind = col
                    if other_kind == 'tame':
                        # neg wild starts at -Q = (N-k)*G
                        # tame_pos = tame_start + tame_dist
                        # neg_pos  = (N-k) + neg_dist
                        # At collision: N-k = tame_start + other_dist - neg_dist
                        k_neg = (tame_start + other_dist - neg_dist) % N
                        k_candidate = (N - k_neg) % N
                        if _verify(k_candidate, pubkey, k_start, k_end):
                            if verbose:
                                _print_found(k_candidate, step, time.time()-t0, dp)
                            return k_candidate

        if verbose and step % 100_000 == 0 and step > 0:
            elapsed = time.time() - t0
            speed   = step / elapsed / 1e6
            print(f"\r  step={step:,}  speed={speed:.2f}Mstep/s  "
                  f"dp={len(dp)}  ", end='', flush=True)

    if verbose:
        print(f"\n[Kangaroo] Not found in {max_steps:,} steps.")
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _recover_key(tame_start, tame_dist, wild_dist, wild_kind,
                 rng_size, k_start, k_end, pubkey, n) -> int | None:
    """Try k = tame_start + tame_dist - wild_dist, verify."""
    k = (tame_start + tame_dist - wild_dist) % n
    if _verify(k, pubkey, k_start, k_end):
        return k
    return None


def _verify(k: int, pubkey: tuple, k_start: int, k_end: int) -> bool:
    if not (k_start <= k <= k_end):
        return False
    return scalar_mul(k, G) == pubkey


def _print_found(k, steps, elapsed, dp):
    print(f"\n[Kangaroo] FOUND k = {k} = {hex(k)}")
    print(f"  Steps:   {steps:,}")
    print(f"  Time:    {elapsed:.2f}s")
    print(f"  DP hits: {len(dp)}")


# ---------------------------------------------------------------------------
# CLI quick-test
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    # Test on puzzle #20: known key
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from ecc.curve import scalar_mul, G
    from main import PUZZLES

    pz = PUZZLES[20]
    # Puzzle #20 key is in [2^19, 2^20-1] — we need to know the actual key
    # For testing, compute pubkey from a known key in range
    k_test   = (2**19 + 2**18)   # mid-range test
    pk_test  = scalar_mul(k_test, G)

    print(f"Testing Kangaroo on k={k_test} (pubkey known)")
    result = solve(pk_test, 2**19, 2**20 - 1, dp_bits=10, verbose=True, max_steps=5_000_000)
    if result == k_test:
        print("[OK] Kangaroo CPU test PASSED")
    else:
        print(f"[FAIL] Expected {k_test}, got {result}")
