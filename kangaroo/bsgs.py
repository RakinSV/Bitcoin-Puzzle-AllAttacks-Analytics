#!/usr/bin/env python3
"""
BSGS — Baby-step Giant-step ECDLP solver for a known public key.

Splits the unknown key into two smaller halves instead of searching it whole:

    k = lo + i*m + j        m = ceil(sqrt(W)),  0 <= i,j < m

Baby steps tabulate every j*G; giant steps walk R = Q - lo*G backwards by m*G
and look each result up in that table. A hit gives both halves at once, so the
work drops from W to ~2*sqrt(W) -- the same square-root saving Kangaroo gets.

WHERE THIS HELPS, HONESTLY
--------------------------
BSGS trades memory for time: it must STORE sqrt(W) points. That is fine for a
small interval and impossible for a large one -- puzzle #140 would need 2^69.5
table entries, more memory than exists. Kangaroo exists precisely to avoid that
(same sqrt(W) time, constant memory), which is why the big puzzles are attacked
with Kangaroo and not this.

So use BSGS when:
  * the public key is known, AND
  * sqrt(W) entries fit in RAM (roughly <= 2^24, i.e. intervals up to ~50 bits).
Otherwise use kangaroo/kangaroo_engine.py.

The x-coordinate is used as the table key, so a match identifies the point only
up to sign; both k = lo + i*m + j and lo + i*m - j are tried and verified
against the real public key, which costs nothing and halves the table.

Usage:
    from kangaroo.bsgs import solve_bsgs
    k = solve_bsgs(pubkey, k_start, k_end)

    python -m kangaroo.bsgs --puzzle 30
    python -m kangaroo.bsgs --pubkey 02... --start 0x... --end 0x...
"""
import sys
import os
import math
import time
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ecc.curve import scalar_mul, point_add, point_neg, G

# A Python dict entry for int->int costs roughly 100 bytes all-in. Refuse to
# build a table that would obviously exhaust RAM rather than thrashing to death.
BYTES_PER_ENTRY = 100
DEFAULT_MAX_TABLE = 1 << 24          # ~16.7M entries ~ 1.7 GB


def table_size_for(k_start: int, k_end: int) -> int:
    """Number of baby-step entries BSGS would need for this interval."""
    return math.isqrt(k_end - k_start + 1) + 1


def feasible(k_start: int, k_end: int, max_entries: int = DEFAULT_MAX_TABLE) -> bool:
    return table_size_for(k_start, k_end) <= max_entries


def solve_bsgs(pubkey, k_start: int, k_end: int,
               max_entries: int = DEFAULT_MAX_TABLE,
               verbose: bool = True, progress_every: int = 500_000):
    """Recover the private key in [k_start, k_end] for `pubkey`, or None.

    Raises MemoryError (before allocating anything) when the interval is too
    wide for a table to fit -- that is the honest failure mode, not a slow one.
    """
    W = k_end - k_start + 1
    m = table_size_for(k_start, k_end)
    if m > max_entries:
        need_gb = m * BYTES_PER_ENTRY / 1024**3
        raise MemoryError(
            f"BSGS needs a {m:,}-entry table (~{need_gb:,.1f} GB) for a "
            f"{W.bit_length()}-bit interval. Use Kangaroo instead — same "
            f"sqrt(W) time, constant memory.")

    Q = tuple(pubkey)
    t0 = time.time()

    # R = Q - k_start*G, so the unknown becomes d = k - k_start in [0, W).
    R = point_add(Q, point_neg(scalar_mul(k_start, G))) if k_start else Q

    if verbose:
        print(f"[BSGS] interval {W.bit_length()} bits, table {m:,} entries "
              f"(~{m * BYTES_PER_ENTRY / 1024**2:,.0f} MB)")

    # ---- baby steps: x(j*G) -> j  for j in [0, m) ----
    table = {}
    cur = None                                  # point at infinity == 0*G
    for j in range(m):
        table[cur[0] if cur else None] = j
        cur = G if cur is None else point_add(cur, G)
        if verbose and progress_every and (j + 1) % progress_every == 0:
            print(f"\r[BSGS] baby steps {j+1:,}/{m:,}", end='', flush=True)
    if verbose:
        print(f"\r[BSGS] baby steps done: {len(table):,} entries "
              f"({time.time()-t0:.1f}s)")

    # ---- giant steps: R - i*(m*G) ----
    neg_mG = point_neg(scalar_mul(m, G))
    cur = R
    for i in range(m + 2):
        x = cur[0] if cur else None
        j = table.get(x)
        if j is not None:
            # x identifies +/- j*G, so the offset is either +j or -j.
            for cand in (k_start + i * m + j, k_start + i * m - j):
                if k_start <= cand <= k_end and scalar_mul(cand, G) == Q:
                    if verbose:
                        print(f"[BSGS] FOUND after {i+1:,} giant steps "
                              f"({time.time()-t0:.1f}s): {hex(cand)}")
                    return cand
        cur = point_add(cur, neg_mG)
        if verbose and progress_every and (i + 1) % progress_every == 0:
            print(f"\r[BSGS] giant steps {i+1:,}/{m:,}", end='', flush=True)

    if verbose:
        print(f"\n[BSGS] not found in [{hex(k_start)}, {hex(k_end)}]")
    return None


def _main():
    ap = argparse.ArgumentParser(description="BSGS ECDLP solver (known pubkey)")
    ap.add_argument('--puzzle', type=int,
                    help="solve a known puzzle by number (uses its real pubkey)")
    ap.add_argument('--pubkey', help="compressed pubkey hex (02../03..) or 'x,y'")
    ap.add_argument('--start', help="range start (hex or dec)")
    ap.add_argument('--end', help="range end (hex or dec)")
    ap.add_argument('--max-entries', type=int, default=DEFAULT_MAX_TABLE)
    args = ap.parse_args()

    if args.puzzle:
        from analysis.rng_analysis import KNOWN_KEYS
        from utils.puzzle_registry import puzzle_range
        n = args.puzzle
        lo, hi = puzzle_range(n)
        if n not in KNOWN_KEYS:
            print(f"[BSGS] puzzle #{n} has no known key here — pass --pubkey "
                  f"with the target's public key instead.")
            return 1
        pub = scalar_mul(KNOWN_KEYS[n], G)
        print(f"[BSGS] puzzle #{n}: range [2^{n-1}, 2^{n})")
    else:
        if not (args.pubkey and args.start and args.end):
            ap.error("need --puzzle, or --pubkey with --start and --end")
        from kangaroo.reconstruct import decompress_pubkey
        if ',' in args.pubkey:
            pub = tuple(int(v, 0) for v in args.pubkey.split(','))
        else:
            pub = decompress_pubkey(args.pubkey)
        lo, hi = int(args.start, 0), int(args.end, 0)

    try:
        k = solve_bsgs(pub, lo, hi, max_entries=args.max_entries)
    except MemoryError as e:
        print(f"[BSGS] {e}")
        return 1
    if k is None:
        return 1
    print(f"\nPRIVATE KEY: {hex(k)}")
    return 0


if __name__ == '__main__':
    sys.exit(_main())
