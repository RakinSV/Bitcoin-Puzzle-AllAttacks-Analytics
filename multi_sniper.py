#!/usr/bin/env python3
"""
Multi-Puzzle Mempool Sniper
===========================
monitor.py watches ONE address. This watches ALL unsolved puzzles at once.

WHY THIS MATTERS:
  A puzzle is only brute-forceable in human time once its PUBLIC KEY is
  exposed — and the pubkey becomes visible the moment ANYONE broadcasts a
  spending transaction (the pubkey sits in the scriptSig/witness). The
  prize then goes to whoever gets a valid higher-fee transaction confirmed
  first. That window is seconds-to-minutes (one block ≈ 10 min).

  So the edge is: detect a competitor's spend the instant it hits the
  mempool, pull the pubkey out of it, and fire a pre-warmed Kangaroo solver
  on a puzzle whose range is small enough to crack inside that window.

WHAT THIS DOES:
  1. Loads the live unsolved-puzzle list (from puzzle_status cache).
  2. Polls every unsolved address' spent_txo_count cheaply (~200 B each).
  3. On ANY change -> investigates that address, extracts the pubkey from the
     mempool/confirmed spend, verifies it against the address.
  4. If the pubkey is found AND the puzzle is within --max-bits (a range a
     GPU Kangaroo can actually finish before the next block), it saves the
     pubkey and (with --autosolve) launches the solver immediately.

This is a legitimate community race tactic (first valid confirmed tx wins),
not an attack on anyone's wallet — these are open puzzle addresses whose
keys are intentionally findable.

Usage:
  python multi_sniper.py                       # poll all unsolved, report only
  python multi_sniper.py --autosolve           # + auto-launch Kangaroo on a hit
  python multi_sniper.py --max-bits 75         # only auto-solve puzzles <= 75 bits
  python multi_sniper.py --interval 20         # poll cadence (s) per full sweep
  python multi_sniper.py --refresh-status      # re-check which puzzles are unsolved
  python multi_sniper.py --once                # one sweep and exit
  python multi_sniper.py --only 71,72,73       # restrict to specific puzzles
"""

import sys
import os
import time
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(__file__))

# Reuse the battle-tested helpers from the single-address monitor
from monitor import (get_spent_txo_count, get_address_txs, get_tx,
                     extract_pubkey_from_scriptsig, verify_pubkey)
from utils.puzzle_registry import (PUZZLE_ADDRESSES, puzzle_range,
                                   estimated_reward_btc, get_puzzle)
from analysis.puzzle_status import (load_cache, build_report, refresh_status)


# ──────────────────────────────────────────────────────────────────
# Target selection
# ──────────────────────────────────────────────────────────────────

def select_targets(only: list = None, refresh: bool = False,
                   max_bits_watch: int = 160) -> list:
    """Return list of (puzzle_num, address) to watch.

    Default: every puzzle the status cache marks UNSOLVED. We WATCH a wide
    range (even big puzzles) because a competitor's spend exposes the pubkey
    regardless of size; --max-bits only gates whether we auto-SOLVE.
    """
    if only:
        targets = []
        for n in only:
            if n in PUZZLE_ADDRESSES:
                targets.append((n, PUZZLE_ADDRESSES[n]))
            else:
                print(f"  [skip] puzzle #{n}: no known address")
        return targets

    nums = [n for n in sorted(PUZZLE_ADDRESSES) if n <= max_bits_watch]
    cache = refresh_status(nums, force=refresh, quiet=True) if refresh else load_cache()
    rows = build_report(cache)

    targets = []
    for r in rows:
        if r['n'] > max_bits_watch:
            continue
        # Watch anything not positively known-solved (unsolved OR unknown).
        if r['solved'] is True:
            continue
        targets.append((r['n'], r['addr']))
    return targets


# ──────────────────────────────────────────────────────────────────
# Pubkey extraction from a (possibly unconfirmed) spend
# ──────────────────────────────────────────────────────────────────

def extract_pubkey_for(address: str) -> bytes | None:
    """Look at the address' transactions and pull a verified pubkey if the
    address has been spent FROM (works for mempool + confirmed)."""
    txs = get_address_txs(address)
    if not txs:
        return None
    for tx in txs:
        for inp in tx.get('vin', []):
            prevout = inp.get('prevout', {})
            if prevout.get('scriptpubkey_address') != address:
                continue
            scriptsig = inp.get('scriptsig', '')
            if scriptsig:
                pk = extract_pubkey_from_scriptsig(scriptsig)
                if pk and verify_pubkey(pk, address):
                    return pk
            for item in inp.get('witness', []) or []:
                try:
                    pk_b = bytes.fromhex(item)
                    if len(pk_b) in (33, 65) and verify_pubkey(pk_b, address):
                        return pk_b
                except Exception:
                    continue
    return None


# ──────────────────────────────────────────────────────────────────
# Hit handling
# ──────────────────────────────────────────────────────────────────

def handle_hit(n: int, address: str, pk: bytes, max_bits: int,
               autosolve: bool):
    pk_hex = pk.hex()
    lo, hi = puzzle_range(n)
    print(f"\n{'!'*64}")
    print(f"  PUBKEY EXPOSED — puzzle #{n} ({estimated_reward_btc(n)} BTC)")
    print(f"  Address: {address}")
    print(f"  Pubkey:  {pk_hex}")
    print(f"{'!'*64}")

    fname = f'pubkey_puzzle{n}.txt'
    with open(fname, 'w') as f:
        f.write(f"Puzzle #{n}\n")
        f.write(f"Address: {address}\n")
        f.write(f"Pubkey:  {pk_hex}\n")
        f.write(f"Range:   [{hex(lo)}, {hex(hi)}]\n")
        f.write(f"Found:   {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"\nKangaroo command:\n")
        f.write(f"  python main.py --puzzle {n} --mode kangaroo "
                f"--pubkey {pk_hex} --n-tame 16384 --n-wild 16384 --dp-bits 15\n")
    print(f"  Saved -> {fname}")

    if n > max_bits:
        print(f"\n  [HOLD] Puzzle #{n} is {n} bits > --max-bits {max_bits}.")
        print(f"         Kangaroo would take O(sqrt(2^{n})) = ~2^{n//2} hops —")
        print(f"         too slow to win the block race. Pubkey saved for the record.")
        return

    print(f"\n  [GO] #{n} is within solvable range ({n} <= {max_bits} bits).")
    cmd = [sys.executable,
           os.path.join(os.path.dirname(__file__), 'main.py'),
           '--puzzle', str(n), '--mode', 'kangaroo', '--pubkey', pk_hex,
           '--n-tame', '16384', '--n-wild', '16384', '--dp-bits', '15']
    if autosolve:
        print(f"  [AUTO] Launching Kangaroo now:\n    {' '.join(cmd)}\n")
        subprocess.run(cmd)
    else:
        print(f"  Run (or use --autosolve to fire automatically):")
        print(f"    {' '.join(cmd)}")


# ──────────────────────────────────────────────────────────────────
# Main sweep loop
# ──────────────────────────────────────────────────────────────────

def run(targets: list, interval: int, max_bits: int, autosolve: bool,
        once: bool):
    print(f"Multi-Puzzle Mempool Sniper")
    print(f"Watching {len(targets)} address(es); auto-solve gate = <= {max_bits} bits; "
          f"autosolve={'ON' if autosolve else 'OFF'}")
    solvable = [n for n, _ in targets if n <= max_bits]
    if solvable:
        print(f"In-range (auto-solvable on exposure): {solvable}")
    print(f"Sweep interval ~{interval}s. Ctrl+C to stop.\n")

    # Seed baseline counts so we only react to CHANGES, not historical dust.
    last = {}
    for n, addr in targets:
        last[n] = get_spent_txo_count(addr)
        time.sleep(0.2)

    sweep = 0
    while True:
        sweep += 1
        t0 = time.time()
        for n, addr in targets:
            spent = get_spent_txo_count(addr)
            if spent < 0:
                continue                          # transient API error
            if spent > last.get(n, 0):
                print(f"\n[{time.strftime('%H:%M:%S')}] #{n} spent_txo_count "
                      f"{last.get(n)} -> {spent} — investigating...")
                pk = extract_pubkey_for(addr)
                if pk:
                    handle_hit(n, addr, pk, max_bits, autosolve)
                    if autosolve and n <= max_bits:
                        return                    # solver took over
                else:
                    print(f"  #{n}: change seen but no spend-from-this-address "
                          f"yet (likely an incoming/dust tx).")
                last[n] = spent
            time.sleep(0.2)                       # polite to the free API

        print(f"\r[{time.strftime('%H:%M:%S')}] sweep #{sweep} clean "
              f"({len(targets)} addrs in {time.time()-t0:.0f}s). Next in {interval}s...",
              end='', flush=True)
        if once:
            print()
            break
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description='Multi-puzzle mempool sniper')
    parser.add_argument('--interval', type=int, default=20,
                        help='Seconds to wait between full sweeps (default 20)')
    parser.add_argument('--max-bits', type=int, default=75,
                        help='Auto-solve only puzzles <= this bit size (default 75). '
                             'Bigger puzzles are still watched and their pubkeys '
                             'saved, but Kangaroo would be too slow to win.')
    parser.add_argument('--max-watch-bits', type=int, default=110,
                        help='Do not even watch puzzles above this size (default 110)')
    parser.add_argument('--autosolve', action='store_true',
                        help='Auto-launch Kangaroo when an in-range pubkey appears')
    parser.add_argument('--once', action='store_true',
                        help='Run a single sweep and exit')
    parser.add_argument('--refresh-status', action='store_true',
                        help='Re-check the blockchain for which puzzles are unsolved')
    parser.add_argument('--only', default='',
                        help='Comma-separated puzzle numbers to restrict to '
                             '(e.g. 71,72,73)')
    args = parser.parse_args()

    only = None
    if args.only:
        only = [int(x) for x in args.only.replace(' ', '').split(',') if x]

    targets = select_targets(only=only, refresh=args.refresh_status,
                             max_bits_watch=args.max_watch_bits)
    if not targets:
        print("No unsolved targets found. Try --refresh-status, or "
              "run analysis/puzzle_status.py first to populate the cache.")
        sys.exit(1)

    run(targets, args.interval, args.max_bits, args.autosolve, args.once)


if __name__ == '__main__':
    main()
