#!/usr/bin/env python3
"""
Ghost-Solved Puzzle Check
=========================
btcpuzzle.info marks puzzles #75, 80, 85, 90, 95, 100, 105, 110, 125, 130 as
"solved" (the community pool swept them). But the SITE'S claim and the
BLOCKCHAIN'S state can disagree — a site can be stale, wrong, or counting a
partial/failed sweep as a solve. Blockchain truth always wins.

This tool cross-checks each "ghost-solved" puzzle directly against the chain:

  ACTUALLY-SOLVED   balance == 0  (funded then fully spent) -> site is right
  STILL-CLAIMABLE   balance  > 0  (prize still sitting there!) -> site is WRONG,
                                   and the money is real
  PUBKEY-EXPOSED    a spend-from exists -> pubkey is on-chain -> Kangaroo-able
                                   regardless of size, if any balance remains

The jackpot case is STILL-CLAIMABLE + PUBKEY-EXPOSED: a puzzle everyone
believes is done, that actually still holds BTC, whose pubkey is already
public so a Kangaroo can finish it. Even STILL-CLAIMABLE alone is worth
knowing — it means the prize was never collected.

Usage:
  python analysis/ghost_solved_check.py
  python analysis/ghost_solved_check.py --list 75,80,90   # custom set
  python analysis/ghost_solved_check.py --solvable-bits 80 # Kangaroo feasibility gate
"""

import sys
import os
import time
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.puzzle_registry import PUZZLE_ADDRESSES, puzzle_range, estimated_reward_btc
from analysis.puzzle_status import fetch_address_status

# The community-pool "solved" puzzles that are worth re-verifying on-chain.
GHOST_DEFAULT = [75, 80, 85, 90, 95, 100, 105, 110, 125, 130]


def _extract_pubkey(address: str):
    """Borrow the verified-pubkey extractor from the sniper (mempool + chain)."""
    from multi_sniper import extract_pubkey_for
    return extract_pubkey_for(address)


def check_one(n: int, solvable_bits: int) -> dict:
    addr = PUZZLE_ADDRESSES.get(n)
    if not addr:
        return {'n': n, 'error': 'no known address'}

    info = fetch_address_status(addr)
    if info is None:
        return {'n': n, 'addr': addr, 'error': 'network error'}

    balance = info['balance_sat']
    funded = info['funded_sat']
    claimable = balance > 0
    actually_solved = funded > 0 and balance <= 0

    pk = None
    if claimable:
        # Only bother pulling the pubkey if there's still money to claim.
        pk = _extract_pubkey(addr)

    return {
        'n': n, 'addr': addr,
        'balance_btc': balance / 1e8,
        'funded_btc': funded / 1e8,
        'reward': estimated_reward_btc(n),
        'claimable': claimable,
        'actually_solved': actually_solved,
        'pubkey': pk.hex() if pk else None,
        'kangaroo_feasible': n <= solvable_bits,
    }


def main():
    parser = argparse.ArgumentParser(description='Re-verify "ghost-solved" puzzles on-chain')
    parser.add_argument('--list', default='',
                        help='Comma-separated puzzle numbers (default: the known ghost set)')
    parser.add_argument('--solvable-bits', type=int, default=80,
                        help='Mark a Kangaroo finish "feasible" only up to this bit size '
                             '(default 80)')
    args = parser.parse_args()

    nums = ([int(x) for x in args.list.replace(' ', '').split(',') if x]
            if args.list else GHOST_DEFAULT)

    print("\n" + "=" * 70)
    print("  GHOST-SOLVED PUZZLE CHECK  (site says solved — does the chain agree?)")
    print("=" * 70)
    print(f"  Re-verifying: {nums}\n")

    jackpots, claimables, confirmed = [], [], []
    for n in nums:
        r = check_one(n, args.solvable_bits)
        if r.get('error'):
            print(f"  #{n:>3}  ERROR: {r['error']}")
            continue

        if r['actually_solved']:
            tag = 'ACTUALLY-SOLVED (site correct, spent)'
            confirmed.append(r)
        elif r['claimable']:
            if r['pubkey']:
                tag = '*** JACKPOT: STILL-CLAIMABLE + PUBKEY EXPOSED ***'
                jackpots.append(r)
            else:
                tag = '!!! STILL-CLAIMABLE (site WRONG — prize uncollected) !!!'
                claimables.append(r)
        else:
            tag = 'unfunded / no data'

        print(f"  #{n:>3}  bal={r['balance_btc']:>9.4f} BTC  "
              f"reward~{r['reward']:.1f}  {tag}")
        if r['pubkey']:
            print(f"        pubkey: {r['pubkey']}")
        time.sleep(0.25)

    # ── Action summary ────────────────────────────────────────────
    print("\n" + "=" * 70)
    if jackpots:
        print(f"  {len(jackpots)} JACKPOT(S) — claimable AND pubkey already public:")
        for r in jackpots:
            feas = "Kangaroo-feasible" if r['kangaroo_feasible'] else \
                   f"#{r['n']} bits — Kangaroo likely too slow, but pubkey is saved"
            print(f"    #{r['n']}  ({r['balance_btc']:.4f} BTC)  {feas}")
            with open(f'pubkey_puzzle{r["n"]}.txt', 'w') as f:
                lo, hi = puzzle_range(r['n'])
                f.write(f"Puzzle #{r['n']}  (GHOST-SOLVED but STILL CLAIMABLE)\n")
                f.write(f"Address: {r['addr']}\n")
                f.write(f"Pubkey:  {r['pubkey']}\n")
                f.write(f"Balance: {r['balance_btc']} BTC\n")
                f.write(f"Range:   [{hex(lo)}, {hex(hi)}]\n")
                f.write(f"\n  python main.py --puzzle {r['n']} --mode kangaroo "
                        f"--pubkey {r['pubkey']} --n-tame 16384 --n-wild 16384 --dp-bits 15\n")
            print(f"      -> saved pubkey_puzzle{r['n']}.txt")
    if claimables:
        print(f"  {len(claimables)} STILL-CLAIMABLE (no pubkey yet — needs brute force "
              f"or wait for a spend to expose the key):")
        for r in claimables:
            print(f"    #{r['n']}  ({r['balance_btc']:.4f} BTC)")
    if not jackpots and not claimables:
        print(f"  All {len(confirmed)} checked puzzles are genuinely solved on-chain "
              f"(balance 0). The site was correct — no free money here.")
    print("=" * 70)


if __name__ == '__main__':
    main()
