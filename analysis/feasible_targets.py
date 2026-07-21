#!/usr/bin/env python3
"""
FEASIBLE TARGET SCANNER — which puzzles can this toolkit actually win?

Pollard's Kangaroo needs the target's PUBLIC KEY. A puzzle address only reveals
its pubkey once it has SPENT something (the pubkey appears in the spending
input's scriptSig/witness). So a puzzle is realistically attackable only if:

    (1) it is UNSOLVED  (prize still sitting there), AND
    (2) its pubkey is EXPOSED (the address has an outgoing tx), AND
    (3) sqrt(interval) is small enough for our engine / a DP pool.

Without (2) the only route is brute-forcing 2^(n-1) keys, which is hopeless well
below #71. This scanner checks all three on-chain and ranks what is genuinely
winnable, so effort goes where there is a chance instead of into a 2^70 wall.

Cost model is anchored on a MEASURED run, not a guess: puzzle #58 was solved
end-to-end in 44 s on one RX 6600 (v1.0.5 per-hop-DP kernel). Kangaroo cost
scales as sqrt(W) with W = 2^(n-1), so

    t(n, gpus) = 44 s * 2^((n-58)/2) / gpus

Usage:
  python analysis/feasible_targets.py                 # scan (cached)
  python analysis/feasible_targets.py --refresh       # re-query the blockchain
  python analysis/feasible_targets.py --max 90        # only puzzles <= 90
  python analysis/feasible_targets.py --gpus 100      # what a 100-GPU pool wins
  python analysis/feasible_targets.py --json
"""
import sys
import os
import json
import time
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.puzzle_registry import (PUZZLE_ADDRESSES, puzzle_range,
                                   estimated_reward_btc, all_puzzle_numbers)
from analysis.puzzle_status import fetch_address_status
from analysis.pubkey_pattern import fetch_address_txs, extract_pubkey_from_input

CACHE_FILE = os.path.join(os.path.dirname(__file__), '..',
                          'feasible_targets_cache.json')
CACHE_TTL = 24 * 3600

# ---- cost model, anchored on a measured solve ----
ANCHOR_N       = 58
ANCHOR_SECONDS = 44.0          # verified #58 on one RX 6600 (v1.0.5)
BRUTE_KEYS_SEC = 400e6         # measured gpu-brute peak (~400 Mkeys/s)

FEASIBLE_1GPU_SEC = 24 * 3600          # "you could just run it"
FEASIBLE_POOL_SEC = 365 * 24 * 3600    # "a pool could realistically finish"


def kangaroo_seconds(n: int, gpus: int = 1) -> float:
    """Expected Kangaroo wall-clock for puzzle n on `gpus` cards."""
    return ANCHOR_SECONDS * (2.0 ** ((n - ANCHOR_N) / 2.0)) / max(1, gpus)


def brute_seconds(n: int) -> float:
    """Expected brute-force wall-clock (no pubkey) — search 2^(n-1) keys."""
    return (2.0 ** (n - 1)) / BRUTE_KEYS_SEC


def human_time(sec: float) -> str:
    if sec < 1:
        return "<1s"
    if sec < 90:
        return f"{sec:.0f}s"
    if sec < 90 * 60:
        return f"{sec/60:.0f}min"
    if sec < 48 * 3600:
        return f"{sec/3600:.1f}h"
    if sec < 400 * 86400:
        return f"{sec/86400:.0f}d"
    y = sec / (365 * 86400)
    if y < 1e4:
        return f"{y:,.0f}y"
    return f"{y:.1e}y"


def pubkey_for_address(addr: str, limit: int = 25):
    """Return the pubkey hex if this address has ever SPENT (revealing it).

    Only an input whose prevout belongs to THIS address exposes THIS key, so we
    match on prevout.scriptpubkey_address rather than taking any input's pubkey.
    """
    try:
        txs = fetch_address_txs(addr, limit=limit)
    except Exception:
        return None
    for tx in txs or []:
        for inp in tx.get('vin', []) or []:
            prevout = inp.get('prevout') or {}
            if prevout.get('scriptpubkey_address') == addr:
                try:
                    pk = extract_pubkey_from_input(inp)
                except Exception:
                    pk = None
                if pk:
                    return pk
    return None


def _load_cache() -> dict:
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict):
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=1)
    except Exception:
        pass


def scan(max_n: int = 160, gpus: int = 1, refresh: bool = False,
         verbose: bool = True, delay: float = 0.12) -> list:
    """Check every puzzle <= max_n on-chain and classify what is winnable."""
    cache = {} if refresh else _load_cache()
    now = time.time()
    rows = []
    nums = [n for n in all_puzzle_numbers() if n <= max_n]

    if verbose:
        print(f"[scan] checking {len(nums)} puzzles (<= #{max_n}) "
              f"{'(forced refresh)' if refresh else '(cached where fresh)'}",
              flush=True)

    for i, n in enumerate(nums):
        addr = PUZZLE_ADDRESSES.get(n)
        if not addr:
            continue
        key = str(n)
        ent = cache.get(key)
        if ent and (now - ent.get('ts', 0)) < CACHE_TTL:
            status, pubkey = ent.get('status'), ent.get('pubkey')
        else:
            status = fetch_address_status(addr)
            time.sleep(delay)
            # A pubkey can only be exposed by a spend, so skip the extra call for
            # addresses that have never spent anything.
            pubkey = None
            if status and status.get('spent_sat', 0) > 0:
                pubkey = pubkey_for_address(addr)
                time.sleep(delay)
            cache[key] = {'ts': now, 'status': status, 'pubkey': pubkey}
            if verbose and (i + 1) % 10 == 0:
                print(f"\r[scan] {i+1}/{len(nums)} ...", end='', flush=True)

        if not status:
            rows.append({'n': n, 'addr': addr, 'verdict': 'UNKNOWN (no data)',
                         'solved': None, 'pubkey': None, 'reward': 0.0,
                         'eta': None, 'eta_s': float('inf')})
            continue

        funded  = status.get('funded_sat', 0)
        balance = status.get('balance_sat', 0)
        solved  = funded > 0 and balance == 0
        reward  = balance / 1e8 if balance else 0.0

        if solved:
            verdict, eta_s = 'SOLVED (prize gone)', float('inf')
        elif funded == 0:
            verdict, eta_s = 'UNFUNDED', float('inf')
        elif not pubkey:
            eta_s = brute_seconds(n)
            verdict = f'NO PUBKEY -> brute force only ({human_time(eta_s)})'
        else:
            eta_s = kangaroo_seconds(n, gpus)
            if eta_s <= FEASIBLE_1GPU_SEC:
                verdict = f'*** WINNABLE on {gpus} GPU(s): {human_time(eta_s)} ***'
            elif eta_s <= FEASIBLE_POOL_SEC:
                verdict = f'pool-feasible grind: {human_time(eta_s)} on {gpus} GPU(s)'
            else:
                verdict = f'pubkey known but too big ({human_time(eta_s)})'

        rows.append({'n': n, 'addr': addr, 'solved': solved, 'pubkey': pubkey,
                     'reward': reward, 'verdict': verdict,
                     'eta': human_time(eta_s) if eta_s != float('inf') else None,
                     'eta_s': eta_s})

    _save_cache(cache)
    if verbose:
        print("\r" + " " * 40 + "\r", end='')
    return rows


def print_report(rows: list, gpus: int = 1):
    live = [r for r in rows if r.get('solved') is False and r.get('reward', 0) > 0]
    exposed = [r for r in live if r.get('pubkey')]
    winnable = sorted([r for r in exposed if r['eta_s'] <= FEASIBLE_1GPU_SEC],
                      key=lambda r: r['eta_s'])

    print("=" * 78)
    print(f"  FEASIBLE TARGETS  (cost model anchored on measured #58 = 44 s, "
          f"{gpus} GPU(s))")
    print("=" * 78)
    print(f"  unsolved with prize : {len(live)}")
    print(f"  of those, pubkey EXPOSED : {len(exposed)}")
    print(f"  of those, winnable now   : {len(winnable)}")
    print()

    if winnable:
        print("  >>> ACTIONABLE TARGETS <<<")
        print(f"  {'#':>4} {'reward BTC':>11} {'ETA':>10}  address")
        for r in winnable:
            print(f"  {r['n']:>4} {r['reward']:>11.3f} {r['eta']:>10}  {r['addr']}")
        print()
    else:
        print("  >>> NO puzzle is winnable right now. <<<")
        print("  Every unsolved puzzle either hides its public key (so only a")
        print("  hopeless brute force applies) or its interval is far too large.")
        print()

    if exposed:
        print("  Unsolved puzzles WITH an exposed pubkey (Kangaroo applies):")
        print(f"  {'#':>4} {'reward BTC':>11} {'ETA':>10}  verdict")
        for r in sorted(exposed, key=lambda r: r['eta_s'])[:15]:
            print(f"  {r['n']:>4} {r['reward']:>11.3f} {str(r['eta']):>10}  "
                  f"{r['verdict']}")
        print()

    nearest = sorted([r for r in live if not r.get('pubkey')],
                     key=lambda r: r['n'])[:5]
    if nearest:
        print("  Smallest unsolved puzzles WITHOUT a pubkey (need a mempool snipe):")
        for r in nearest:
            print(f"  {r['n']:>4} {r['reward']:>11.3f} BTC  {r['addr']}  "
                  f"-> if its pubkey ever appears: "
                  f"{human_time(kangaroo_seconds(r['n'], gpus))} on {gpus} GPU(s)")
    print("=" * 78)


def main():
    ap = argparse.ArgumentParser(description="Scan for winnable puzzles")
    ap.add_argument('--max', type=int, default=160, help="only puzzles <= N")
    ap.add_argument('--gpus', type=int, default=1, help="size of your DP pool")
    ap.add_argument('--refresh', action='store_true', help="re-query blockchain")
    ap.add_argument('--json', action='store_true', help="machine-readable output")
    args = ap.parse_args()

    rows = scan(max_n=args.max, gpus=args.gpus, refresh=args.refresh,
                verbose=not args.json)
    if args.json:
        print(json.dumps(rows, indent=1))
    else:
        print_report(rows, gpus=args.gpus)


if __name__ == '__main__':
    main()
