#!/usr/bin/env python3
"""
REGISTRY VERIFIER — check every puzzle address against the chain, by reward.

Puzzle N's address is funded with exactly N * 0.1 BTC. That makes the on-chain
balance a self-verifying label: round(balance_BTC * 10) IS the puzzle number.

Why this exists: utils/puzzle_registry.py built its 71-150 table from keyhunt's
`unsolvedpuzzles.txt` assuming "line N -> puzzle N+66". But that file lists only
the puzzles that were UNSOLVED when it was written, so every already-solved
multiple of 5 (75, 80, ... 120) is missing from it and the numbering silently
drifts. Proof: the article-published private key for #135 is 135 bits, lies in
#135's range, and derives to the address our registry labels #125 -- a +10 shift.
Every conclusion we drew about high puzzles was therefore attached to the wrong
puzzle number.

Run:  python analysis/verify_registry.py            # check + report
      python analysis/verify_registry.py --json     # machine-readable
"""
import sys
import os
import json
import time
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.puzzle_registry import PUZZLE_ADDRESSES
from analysis.puzzle_status import fetch_address_status


def verify(max_n: int = 160, delay: float = 0.12, verbose: bool = True) -> list:
    """Return per-entry verdicts comparing registry number vs on-chain reward."""
    rows = []
    nums = [n for n in sorted(PUZZLE_ADDRESSES) if n <= max_n]
    for i, n in enumerate(nums):
        addr = PUZZLE_ADDRESSES[n]
        st = fetch_address_status(addr)
        time.sleep(delay)
        if not st:
            rows.append({'registry_n': n, 'addr': addr, 'status': 'no data'})
            continue
        funded = st['funded_sat'] / 1e8
        bal = st['balance_sat'] / 1e8
        # The FUNDED amount encodes the puzzle number even after a solve empties
        # the balance, so use funded (not balance) as the label.
        true_n = round(funded * 10) if funded else None
        rows.append({
            'registry_n': n, 'addr': addr, 'funded_btc': funded,
            'balance_btc': bal, 'true_n': true_n,
            'solved': bool(funded and not bal),
            'ok': (true_n == n),
        })
        if verbose and (i + 1) % 10 == 0:
            print(f"\r  [verify] {i+1}/{len(nums)}", end='', flush=True)
    if verbose:
        print("\r" + " " * 30 + "\r", end='')
    return rows


def main():
    ap = argparse.ArgumentParser(description="Verify puzzle registry vs chain")
    ap.add_argument('--max', type=int, default=160)
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    rows = verify(max_n=args.max, verbose=not args.json)
    if args.json:
        print(json.dumps(rows, indent=1))
        return

    good = [r for r in rows if r.get('ok')]
    bad = [r for r in rows if r.get('true_n') and not r.get('ok')]
    unknown = [r for r in rows if not r.get('true_n')]

    print("=" * 78)
    print("  REGISTRY VERIFICATION  (puzzle N is funded with exactly N * 0.1 BTC)")
    print("=" * 78)
    print(f"  correct : {len(good)}")
    print(f"  WRONG   : {len(bad)}")
    print(f"  no data : {len(unknown)}")

    if bad:
        print("\n  Mislabelled entries (registry_n -> true_n by reward):")
        print(f"  {'registry':>9} {'true':>6} {'funded':>9} {'state':>9}  address")
        for r in sorted(bad, key=lambda r: r['registry_n']):
            print(f"  {r['registry_n']:>9} {r['true_n']:>6} "
                  f"{r['funded_btc']:>9.2f} "
                  f"{'solved' if r['solved'] else 'UNSOLVED':>9}  {r['addr']}")
        shifts = {r['true_n'] - r['registry_n'] for r in bad}
        print(f"\n  offsets present: {sorted(shifts)}")

    live = [r for r in rows if r.get('true_n') and not r.get('solved')]
    if live:
        smallest = min(live, key=lambda r: r['true_n'])
        print(f"\n  smallest UNSOLVED puzzle by true number: #{smallest['true_n']} "
              f"({smallest['funded_btc']:.2f} BTC)  {smallest['addr']}")
    print("=" * 78)


if __name__ == '__main__':
    main()
