#!/usr/bin/env python3
"""
Puzzle Status Checker
======================
Live blockchain check for all known Bitcoin puzzles (#1-150): solved or
not, current balance, BTC reward, bit-difficulty. Used to pick which
unsolved puzzle to attack and to feed the interactive launcher menu.

Status is determined directly from the blockchain (blockstream.info /
mempool.space), NOT by scraping btcpuzzle.info — addresses are
public/static but "solved" changes over time, so blockchain truth wins:

  SOLVED    = address was funded AND fully spent (key found, prize moved)
  UNSOLVED  = address funded AND balance > 0  (prize still sitting there)
  UNFUNDED  = address never received anything (no data yet)

Results are cached (default 6h) so repeated bat-file runs don't hammer
the API. ~80-150 addresses at one request every 0.25s = ~20-40s first run.

Usage:
  python analysis/puzzle_status.py                  # full table (cached)
  python analysis/puzzle_status.py --refresh         # force re-check blockchain
  python analysis/puzzle_status.py --unsolved        # only unsolved, ascending #
  python analysis/puzzle_status.py --json            # machine-readable
  python analysis/puzzle_status.py --max 100         # only check puzzles <= 100
                                                       # (anything above ~80 bits
                                                       #  is realistically unreachable)
"""

import sys
import os
import json
import time
import argparse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.puzzle_registry import (PUZZLE_ADDRESSES, puzzle_range,
                                    estimated_reward_btc, all_puzzle_numbers)

CACHE_FILE = os.path.join(os.path.dirname(__file__), '..', 'puzzle_status_cache.json')
CACHE_TTL  = 6 * 3600  # seconds


# ──────────────────────────────────────────────────────────────────
# Blockchain queries
# ──────────────────────────────────────────────────────────────────

def _get_json(url: str, timeout: int = 15):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'btc-puzzle-status/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def fetch_address_status(addr: str) -> dict | None:
    """Query chain_stats for an address. Tries blockstream then mempool.space."""
    data = _get_json(f'https://blockstream.info/api/address/{addr}')
    if data is None:
        data = _get_json(f'https://mempool.space/api/address/{addr}')
    if data is None:
        return None
    cs = data.get('chain_stats', {})
    funded = cs.get('funded_txo_sum', 0)
    spent  = cs.get('spent_txo_sum', 0)
    return {
        'funded_sat':  funded,
        'spent_sat':   spent,
        'balance_sat': funded - spent,
        'n_tx':        cs.get('tx_count', 0),
    }


# ──────────────────────────────────────────────────────────────────
# Cache
# ──────────────────────────────────────────────────────────────────

def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache: dict):
    tmp = CACHE_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, CACHE_FILE)


def refresh_status(puzzle_nums: list = None, force: bool = False,
                    quiet: bool = False) -> dict:
    """Updates (and returns) the cache with live blockchain data."""
    cache = load_cache()
    now   = time.time()
    nums  = puzzle_nums or all_puzzle_numbers()
    checked, skipped = 0, 0

    for n in nums:
        key    = str(n)
        cached = cache.get(key)
        if not force and cached and (now - cached.get('checked_at', 0)) < CACHE_TTL:
            skipped += 1
            continue

        addr = PUZZLE_ADDRESSES.get(n)
        if not addr:
            continue
        info = fetch_address_status(addr)
        if info is None:
            if not quiet:
                print(f"  #{n}: network error, skipping (will retry next run)")
            continue

        solved = info['balance_sat'] <= 0 and info['funded_sat'] > 0
        cache[key] = {
            'addr':        addr,
            'funded_sat':  info['funded_sat'],
            'balance_sat': info['balance_sat'],
            'solved':      solved,
            'checked_at':  now,
        }
        checked += 1
        if not quiet:
            status = 'SOLVED  ' if solved else ('UNSOLVED' if info['funded_sat'] > 0 else 'UNFUNDED')
            btc = info['balance_sat'] / 1e8
            print(f"  #{n:3d}  {status}  balance={btc:10.4f} BTC  {addr}")
        time.sleep(0.25)  # be polite to the free API

    save_cache(cache)
    if not quiet:
        print(f"\n[refresh] Checked {checked} live, {skipped} from cache "
              f"(cache TTL={CACHE_TTL//3600}h)")
    return cache


# ──────────────────────────────────────────────────────────────────
# Reporting
# ──────────────────────────────────────────────────────────────────

def build_report(cache: dict) -> list:
    """Combine registry + cache into a sorted list of puzzle status dicts."""
    rows = []
    for n in all_puzzle_numbers():
        c = cache.get(str(n))
        lo, hi = puzzle_range(n)
        rows.append({
            'n':        n,
            'addr':     PUZZLE_ADDRESSES[n],
            'bits':     n,
            'reward':   estimated_reward_btc(n),
            'solved':   c['solved'] if c else None,
            'balance':  c['balance_sat'] / 1e8 if c else None,
            'checked':  c is not None,
        })
    return rows


def print_table(rows: list, unsolved_only: bool = False):
    if unsolved_only:
        rows = [r for r in rows if r['solved'] is False]
        rows.sort(key=lambda r: r['n'])  # easiest (lowest bit count) first

    print(f"\n{'#':>4}  {'Status':>9}  {'Reward~BTC':>10}  {'Balance':>12}  {'Address'}")
    print("-" * 80)
    for r in rows:
        if r['solved'] is None:
            status = 'unknown'
        elif r['solved']:
            status = 'SOLVED'
        else:
            status = 'UNSOLVED'
        bal = f"{r['balance']:.4f}" if r['balance'] is not None else '?'
        print(f"{r['n']:>4}  {status:>9}  {r['reward']:>10.2f}  {bal:>12}  {r['addr']}")

    n_unsolved = sum(1 for r in rows if r['solved'] is False)
    n_solved   = sum(1 for r in rows if r['solved'] is True)
    n_unknown  = sum(1 for r in rows if r['solved'] is None)
    print("-" * 80)
    print(f"Solved: {n_solved}   Unsolved: {n_unsolved}   Unknown(not checked): {n_unknown}")


def print_attack_priority(rows: list, top: int = 15):
    """Unsolved puzzles ranked by realistic attackability (lowest bits first)."""
    unsolved = [r for r in rows if r['solved'] is False]
    unsolved.sort(key=lambda r: r['n'])

    print(f"\n{'='*70}")
    print(f"  ATTACK PRIORITY - lowest difficulty first (most realistic odds)")
    print(f"{'='*70}")
    print(f"  {'#':>4}  {'Reward':>8}  {'Keyspace':>12}  {'Address'}")
    for r in unsolved[:top]:
        keyspace = f"2^{r['n']-1}"
        print(f"  {r['n']:>4}  {r['reward']:>6.2f} BTC  {keyspace:>12}  {r['addr']}")
    if len(unsolved) > top:
        print(f"  ... and {len(unsolved)-top} more (use --unsolved --json for full list)")


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Bitcoin Puzzle Status Checker')
    parser.add_argument('--refresh', action='store_true',
                        help='Force re-check blockchain (ignore cache)')
    parser.add_argument('--unsolved', action='store_true',
                        help='Show only unsolved puzzles')
    parser.add_argument('--json', action='store_true',
                        help='Machine-readable JSON output')
    parser.add_argument('--max', type=int, default=0,
                        help='Only check puzzles <= this number (0 = all known)')
    parser.add_argument('--quiet', action='store_true',
                        help='Suppress per-puzzle progress lines during refresh')
    parser.add_argument('--top', type=int, default=15,
                        help='How many top-priority unsolved puzzles to show (default 15)')
    args = parser.parse_args()

    nums = all_puzzle_numbers()
    if args.max:
        nums = [n for n in nums if n <= args.max]

    if not args.json:
        print("\n" + "=" * 60)
        print("  BITCOIN PUZZLE STATUS CHECKER")
        print("  Source: blockchain (blockstream.info / mempool.space)")
        print("=" * 60)

    cache = refresh_status(nums, force=args.refresh, quiet=args.quiet or args.json)
    rows  = build_report(cache)
    rows  = [r for r in rows if r['n'] in nums]

    if args.json:
        print(json.dumps(rows, indent=2))
        return

    if args.unsolved:
        print_table(rows, unsolved_only=True)
    else:
        print_table(rows, unsolved_only=False)

    print_attack_priority(rows, top=args.top)


if __name__ == '__main__':
    main()
