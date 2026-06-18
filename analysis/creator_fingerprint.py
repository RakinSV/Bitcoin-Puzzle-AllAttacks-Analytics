#!/usr/bin/env python3
"""
Creator / Solver Fingerprinting — Bitcoin Puzzle
===================================================
Methodology borrowed from cyber-threat-intelligence practice: cluster
on-chain activity by behavioral signal (fee strategy, timing, script
choices, destination-address reuse, common-input-ownership) instead of
trusting any single indicator. Every finding gets a confidence grade
(HIGH/MEDIUM/LOW) — corroborated across multiple signals before being
called a cluster.

TWO QUESTIONS THIS ANSWERS:

  1. CREATOR FINGERPRINT — does the original funding transaction leak
     anything about who set up the puzzle (wallet era, script types,
     other on-chain activity from the same source)?

  2. SOLVER CLUSTERING — are the 72 already-solved puzzles being claimed
     by a handful of well-resourced operators (pools/farms running
     sequential or parallel brute force), or by many independent actors?
     If a small cluster solves puzzles on a predictable cadence, THAT is
     the real competition for #71 — not "someone gets lucky" but
     "a farm is grinding and will get there eventually." Knowing the
     cadence also calibrates realistic expectations for our own lottery.

Clustering signals (each individually weak, corroboration raises confidence):
  - Exact destination-address reuse across solves (HIGH on its own)
  - Common-input-ownership: two solve payouts later spent together in
    one transaction proves the same wallet controls both (HIGH)
  - Fee-rate fingerprint: many wallets/bots use a fixed or
    narrow-banded fee rate (MEDIUM, needs corroboration)
  - Timing fingerprint: modal hour-of-day / day-of-week clustering
    suggests a cron-scheduled bot with a guessable timezone (LOW/MEDIUM)
  - Destination script-type: consistent P2PKH/P2WPKH/P2TR choice hints
    at consistent wallet software (LOW, supporting signal only)

Usage:
  python analysis/creator_fingerprint.py                # full report (cached)
  python analysis/creator_fingerprint.py --refresh        # force re-fetch
  python analysis/creator_fingerprint.py --deep            # + common-input-ownership pass
  python analysis/creator_fingerprint.py --funding-only    # just the creator's funding tx
"""

import sys
import os
import json
import time
import argparse
from collections import defaultdict, Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.puzzle_registry import PUZZLE_ADDRESSES
from analysis.puzzle_status import load_cache as load_status_cache, _get_json

FUNDING_TX = '08389f34c98c606322740c0be6a7125d9860bb8d5cb182c02f98461e5fa6cd15'
CACHE_FILE = os.path.join(os.path.dirname(__file__), '..', 'fingerprint_cache.json')
CACHE_TTL  = 30 * 24 * 3600  # solved puzzles don't change again — cache long


# ──────────────────────────────────────────────────────────────────
# Blockchain fetch helpers
# ──────────────────────────────────────────────────────────────────

def fetch_tx(txid: str) -> dict | None:
    return _get_json(f'https://blockstream.info/api/tx/{txid}')


def fetch_address_txs(addr: str, max_pages: int = 5) -> list:
    """
    First page returns up to 50 txs. Famous puzzle addresses can attract
    decades of dust spam on top of the real solve, easily exceeding 50 —
    paginate via the last txid so an old, real prize claim doesn't get
    pushed out of the window by newer junk transactions.
    """
    txs = _get_json(f'https://blockstream.info/api/address/{addr}/txs') or []
    all_txs = list(txs)
    page = 0
    while txs and len(txs) >= 25 and page < max_pages:
        last_txid = txs[-1].get('txid')
        if not last_txid:
            break
        txs = _get_json(f'https://blockstream.info/api/address/{addr}/txs/chain/{last_txid}') or []
        all_txs.extend(txs)
        page += 1
        time.sleep(0.15)
    return all_txs


def find_spend_and_fund_tx(addr: str, txs: list) -> tuple:
    """
    From all txs touching addr, split into (funding_tx, spending_tx).

    A famous puzzle address can receive unrelated dust/spam deposits over
    the years on top of its real prize — each creating a separate UTXO,
    each spendable only by the actual key-holder, but NOT all of them
    representing "the solve." When addr appears as an input in more than
    one tx, pick the one where addr's OWN contributed value is LARGEST —
    that is overwhelmingly likely to be the real prize claim rather than
    an incidental dust sweep.
    """
    fund_tx = None
    best_spend_tx = None
    best_spend_value = -1
    for tx in txs:
        for vin in tx.get('vin', []):
            if vin.get('prevout', {}).get('scriptpubkey_address') == addr:
                value = vin.get('prevout', {}).get('value', 0)
                if value > best_spend_value:
                    best_spend_value = value
                    best_spend_tx = tx
        for vout in tx.get('vout', []):
            if vout.get('scriptpubkey_address') == addr:
                fund_tx = tx
    return fund_tx, best_spend_tx


def script_type_of(vout: dict) -> str:
    return vout.get('scriptpubkey_type', 'unknown')


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


# ──────────────────────────────────────────────────────────────────
# Per-puzzle solve-event extraction
# ──────────────────────────────────────────────────────────────────

def extract_solve_event(n: int, addr: str, spend_tx: dict) -> dict:
    """Pull every behavioral signal out of a single spending transaction."""
    fee = spend_tx.get('fee', 0)
    vsize = spend_tx.get('weight', 0) / 4 if spend_tx.get('weight') else spend_tx.get('size', 1)
    vsize = max(vsize, 1)
    block_time = spend_tx.get('status', {}).get('block_time')

    dt = datetime.fromtimestamp(block_time, tz=timezone.utc) if block_time else None

    # How much was actually IN this puzzle's own address when spent —
    # critical to distinguish a real prize claim from a dust/test deposit
    # that happens to reuse the puzzle address as one of many co-inputs.
    input_value = 0
    for vin in spend_tx.get('vin', []):
        if vin.get('prevout', {}).get('scriptpubkey_address') == addr:
            input_value = vin.get('prevout', {}).get('value', 0)
            break

    from utils.puzzle_registry import estimated_reward_btc
    expected_sat = estimated_reward_btc(n) * 1e8
    # Real puzzle rewards are BTC-scale; anything under ~1% of the
    # expected reward (and an absolute floor) is a dust/test artifact,
    # not someone claiming the actual prize.
    is_dust = input_value < max(50_000, expected_sat * 0.01)

    dest = []
    for vout in spend_tx.get('vout', []):
        out_addr = vout.get('scriptpubkey_address')
        value = vout.get('value', 0)
        if out_addr and value > 0:   # skip OP_RETURN / dust-zero outputs
            dest.append({'addr': out_addr, 'value': value,
                        'type': script_type_of(vout)})

    rbf = any(vin.get('sequence', 0xffffffff) < 0xfffffffe
              for vin in spend_tx.get('vin', []))

    return {
        'n': n,
        'addr': addr,
        'spend_txid': spend_tx.get('txid'),
        'input_value': input_value,
        'is_dust': is_dust,
        'fee_sat': fee,
        'vsize': vsize,
        'fee_rate': round(fee / vsize, 2) if vsize else 0,
        'block_time': block_time,
        'iso_time': dt.isoformat() if dt else None,
        'hour_utc': dt.hour if dt else None,
        'dow': dt.weekday() if dt else None,   # 0=Monday
        'n_inputs': len(spend_tx.get('vin', [])),
        'n_outputs': len(spend_tx.get('vout', [])),
        'dest': dest,
        'rbf': rbf,
        'locktime': spend_tx.get('locktime', 0),
        'version': spend_tx.get('version', 1),
    }


def collect_solve_events(puzzle_numbers: list, force: bool = False,
                         quiet: bool = False) -> dict:
    """Fetch (or load from cache) the spending tx + extracted signals
    for every solved puzzle in puzzle_numbers."""
    cache = load_cache()
    events = cache.get('events', {})
    now = time.time()

    for n in puzzle_numbers:
        key = str(n)
        cached = events.get(key)
        if not force and cached and (now - cached.get('_cached_at', 0)) < CACHE_TTL:
            continue

        addr = PUZZLE_ADDRESSES.get(n)
        if not addr:
            continue

        txs = fetch_address_txs(addr)
        _fund_tx, spend_tx = find_spend_and_fund_tx(addr, txs)
        if spend_tx is None:
            if not quiet:
                print(f"  #{n}: no spending tx found yet (still unsolved or not indexed)")
            time.sleep(0.2)
            continue

        ev = extract_solve_event(n, addr, spend_tx)
        ev['_cached_at'] = now
        events[key] = ev
        if not quiet:
            print(f"  #{n:>3}: spend={ev['spend_txid'][:12]}...  "
                  f"fee_rate={ev['fee_rate']:.1f} sat/vB  "
                  f"hour_utc={ev['hour_utc']}  dest_n={len(ev['dest'])}")
        time.sleep(0.25)

    cache['events'] = events
    save_cache(cache)
    return events


# ──────────────────────────────────────────────────────────────────
# Funding TX (creator) analysis
# ──────────────────────────────────────────────────────────────────

def analyze_funding_tx(txid: str = FUNDING_TX) -> dict:
    print(f"\n{'='*70}")
    print(f"  CREATOR FINGERPRINT — funding transaction")
    print(f"{'='*70}")

    tx = fetch_tx(txid)
    if not tx:
        print("  [!] Could not fetch funding TX")
        return {}

    block_time = tx.get('status', {}).get('block_time')
    dt = datetime.fromtimestamp(block_time, tz=timezone.utc) if block_time else None

    inputs = tx.get('vin', [])
    in_addrs = sorted(set(
        vin.get('prevout', {}).get('scriptpubkey_address')
        for vin in inputs if vin.get('prevout', {}).get('scriptpubkey_address')
    ))
    in_types = Counter(script_type_of(vin.get('prevout', {})) for vin in inputs)
    out_types = Counter(script_type_of(v) for v in tx.get('vout', []))

    fee = tx.get('fee', 0)
    vsize = tx.get('weight', 0) / 4 if tx.get('weight') else tx.get('size', 1)

    print(f"  Date:           {dt.isoformat() if dt else 'unknown'}")
    print(f"  Block height:   {tx.get('status', {}).get('block_height')}")
    print(f"  Creator wallet: {len(in_addrs)} input address(es)")
    for a in in_addrs[:5]:
        print(f"    {a}")
    print(f"  Input script types:  {dict(in_types)}")
    print(f"  Output script types: {dict(out_types)}  (160 puzzle outputs + maybe change)")
    print(f"  Fee paid:       {fee:,} sat  ({fee/vsize:.1f} sat/vB)")
    print(f"  Total outputs:  {len(tx.get('vout', []))}")

    print(f"\n  [Confidence: HIGH on these facts — they are read directly from")
    print(f"   the blockchain. Identity attribution beyond this requires")
    print(f"   external OSINT (forum posts, exchange KYC leaks, etc.) which")
    print(f"   this script does not attempt.]")

    return {
        'txid': txid, 'block_time': block_time, 'in_addrs': in_addrs,
        'in_types': dict(in_types), 'out_types': dict(out_types),
        'fee': fee, 'fee_rate': fee / vsize if vsize else 0,
    }


# ──────────────────────────────────────────────────────────────────
# Solver clustering
# ──────────────────────────────────────────────────────────────────

def cluster_by_dest_reuse(events: dict) -> list:
    """
    Exact same destination address claiming multiple solves = HIGH
    confidence cluster — BUT corroborate before calling it a "solver":
    if the puzzle's own input value was dust (see is_dust), this is NOT
    someone claiming the prize, it's the key-holder (likely the creator
    or an insider — they are the only one who CAN spend an unsolved
    puzzle's output) doing unrelated housekeeping. Label these separately.
    """
    addr_to_puzzles = defaultdict(list)
    addr_to_dust = defaultdict(set)
    for ev in events.values():
        for d in ev['dest']:
            addr_to_puzzles[d['addr']].append(ev['n'])
            if ev.get('is_dust'):
                addr_to_dust[d['addr']].add(ev['n'])

    clusters = []
    for a, ps in addr_to_puzzles.items():
        puzzles = sorted(set(ps))
        if len(puzzles) <= 1:
            continue
        if addr_to_dust[a]:
            clusters.append({
                'addrs': [a], 'puzzles': puzzles, 'confidence': 'HIGH',
                'kind': 'insider-housekeeping',
                'reason': f'identical destination address, but input value(s) for '
                          f'{sorted(addr_to_dust[a])} were dust (well below expected '
                          f'reward) — this is the KEY-HOLDER moving small test amounts, '
                          f'NOT a prize claim. Only someone who already has the private '
                          f'key can spend from an address at all, so this still proves '
                          f'common control — just not "solving" anything.',
            })
        else:
            clusters.append({
                'addrs': [a], 'puzzles': puzzles, 'confidence': 'HIGH',
                'kind': 'solver',
                'reason': 'identical destination address, real BTC-scale reward amounts '
                          '— consistent with one solver consolidating multiple wins',
            })
    return clusters


def cluster_by_common_input_ownership(events: dict, quiet: bool = False) -> list:
    """
    Deep pass: for every destination address from a solve, fetch ITS
    later transactions and check whether it ever appears as a co-input
    alongside a destination address from a DIFFERENT solve. If two
    addresses are spent together as inputs in the same tx, the same
    wallet controls both — classic blockchain clustering heuristic.
    """
    print(f"\n[Deep] Common-input-ownership pass (extra API calls)...")
    dest_to_puzzle = {}
    for ev in events.values():
        for d in ev['dest']:
            dest_to_puzzle[d['addr']] = ev['n']

    union_find = {a: a for a in dest_to_puzzle}

    def find(a):
        while union_find[a] != a:
            a = union_find[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            union_find[ra] = rb

    checked = 0
    for addr in list(dest_to_puzzle.keys()):
        txs = fetch_address_txs(addr)
        for tx in txs:
            in_addrs_here = set(
                vin.get('prevout', {}).get('scriptpubkey_address')
                for vin in tx.get('vin', [])
            )
            tracked_in_this_tx = in_addrs_here & dest_to_puzzle.keys()
            if len(tracked_in_this_tx) > 1:
                tracked = list(tracked_in_this_tx)
                for other in tracked[1:]:
                    union(tracked[0], other)
        checked += 1
        if not quiet and checked % 10 == 0:
            print(f"  ...checked {checked}/{len(dest_to_puzzle)} destination addresses")
        time.sleep(0.2)

    groups = defaultdict(list)
    for addr, puzzle_n in dest_to_puzzle.items():
        groups[find(addr)].append((addr, puzzle_n))

    clusters = []
    for root, members in groups.items():
        puzzles = sorted(set(p for _, p in members))
        if len(puzzles) > 1:
            clusters.append({
                'addrs': [a for a, _ in members], 'puzzles': puzzles,
                'confidence': 'HIGH',
                'reason': 'co-spent as inputs in a later transaction (proven common ownership)',
            })
    return clusters


def cluster_by_fee_rate(events: dict) -> list:
    """Group solves with near-identical fee rate — many bots/wallets use a fixed rate."""
    by_rate = defaultdict(list)
    for ev in events.values():
        bucket = round(ev['fee_rate'])
        by_rate[bucket].append(ev['n'])

    clusters = []
    for rate, puzzles in by_rate.items():
        if len(puzzles) >= 3:   # 3+ solves at the exact same fee rate is notable
            clusters.append({
                'fee_rate_bucket': rate, 'puzzles': sorted(puzzles),
                'confidence': 'MEDIUM',
                'reason': f'{len(puzzles)} solves all paid ~{rate} sat/vB '
                          f'(weak signal alone, supports other clusters if they overlap)',
            })
    return clusters


def analyze_timing(events: dict) -> dict:
    """Hour-of-day / day-of-week distribution — reveals bot cadence, not identity.
    Dust/housekeeping events excluded — they're not real prize claims."""
    real = [ev for ev in events.values() if not ev.get('is_dust')]
    hours = Counter(ev['hour_utc'] for ev in real if ev['hour_utc'] is not None)
    dows  = Counter(ev['dow'] for ev in real if ev['dow'] is not None)

    n = sum(hours.values())
    if n == 0:
        return {}

    top_hour, top_hour_n = hours.most_common(1)[0]
    expected_per_hour = n / 24
    hour_skew = top_hour_n / expected_per_hour if expected_per_hour else 0

    return {
        'n_events': n,
        'hour_histogram': dict(sorted(hours.items())),
        'dow_histogram': dict(sorted(dows.items())),
        'top_hour_utc': top_hour,
        'top_hour_count': top_hour_n,
        'top_hour_skew': round(hour_skew, 2),
    }


def analyze_progress_rate(events: dict) -> None:
    """How has the community's brute-force frontier advanced over time?
    Useful to calibrate realistic expectations for puzzle #71, not for
    identity — pure competitive-landscape context. Dust/housekeeping
    events excluded — they reflect the key-holder's own activity, not
    when the difficulty level was actually cracked by a solver."""
    timed = sorted(
        [(ev['n'], ev['block_time']) for ev in events.values()
         if ev['block_time'] and not ev.get('is_dust')],
        key=lambda x: x[0]
    )
    if len(timed) < 2:
        return

    print(f"\n{'='*70}")
    print(f"  PROGRESS RATE — when did each bit-difficulty level fall?")
    print(f"{'='*70}")
    print(f"  {'#':>4}  {'Solved (UTC)':>20}  {'Days since prev solve'}")
    prev_t = None
    for n, t in timed:
        dt = datetime.fromtimestamp(t, tz=timezone.utc)
        gap = f"{(t - prev_t)/86400:.1f}" if prev_t else "-"
        print(f"  {n:>4}  {dt.strftime('%Y-%m-%d %H:%M'):>20}  {gap}")
        prev_t = t

    recent = timed[-10:]
    if len(recent) >= 2:
        span_days = (recent[-1][1] - recent[0][1]) / 86400
        bits_covered = recent[-1][0] - recent[0][0]
        if span_days > 0 and bits_covered > 0:
            print(f"\n  Last {len(recent)} solves: {bits_covered} bits of difficulty "
                  f"in {span_days:.0f} days")
            print(f"  -> roughly {span_days/bits_covered:.1f} days per extra bit "
                  f"of community-wide brute-force progress")
            print(f"  -> puzzle #71 is {71 - recent[-1][0]} bits beyond the most "
                  f"recent solve in this sample (rough, not a prediction)")


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Creator/solver fingerprinting via on-chain clustering')
    parser.add_argument('--refresh', action='store_true',
                        help='Force re-fetch all solve events (ignore cache)')
    parser.add_argument('--deep', action='store_true',
                        help='Also run the common-input-ownership pass '
                             '(more API calls, stronger clusters)')
    parser.add_argument('--funding-only', action='store_true',
                        help='Only analyze the funding TX, skip solver clustering')
    parser.add_argument('--quiet', action='store_true',
                        help='Suppress per-puzzle fetch progress lines')
    args = parser.parse_args()

    funding_info = analyze_funding_tx()

    if args.funding_only:
        return

    status_cache = load_status_cache()
    solved = sorted(int(k) for k, v in status_cache.items() if v.get('solved'))
    if not solved:
        print("\n[!] No solved-puzzle status found. Run "
              "'python analysis/puzzle_status.py --refresh' first.")
        return

    print(f"\n{'='*70}")
    print(f"  SOLVER CLUSTERING — {len(solved)} solved puzzles")
    print(f"{'='*70}\n")
    events = collect_solve_events(solved, force=args.refresh, quiet=args.quiet)

    if not events:
        print("\n[!] No spending transactions collected.")
        return

    n_dust = sum(1 for ev in events.values() if ev.get('is_dust'))
    print(f"\n[Collected] {len(events)} solve events with on-chain data "
          f"({n_dust} flagged as dust/housekeeping, not real prize claims)")

    # --- Clustering passes ---
    clusters = []
    clusters += cluster_by_dest_reuse(events)
    clusters += cluster_by_fee_rate(events)
    if args.deep:
        clusters += cluster_by_common_input_ownership(events, quiet=args.quiet)

    print(f"\n{'='*70}")
    print(f"  CLUSTERS FOUND")
    print(f"{'='*70}")
    if not clusters:
        print("  No multi-puzzle clusters detected with current signals.")
        print("  (Try --deep for the common-input-ownership pass — stronger but slower.)")
    else:
        for c in clusters:
            kind = c.get('kind', 'fee-pattern')
            tag = {'solver': 'SOLVER', 'insider-housekeeping': 'INSIDER/CREATOR',
                  'fee-pattern': 'FEE-PATTERN'}.get(kind, kind.upper())
            print(f"\n  [{c['confidence']}] [{tag}] puzzles {c['puzzles']}")
            print(f"    reason: {c['reason']}")

    # --- Timing fingerprint ---
    timing = analyze_timing(events)
    if timing:
        print(f"\n{'='*70}")
        print(f"  TIMING FINGERPRINT")
        print(f"{'='*70}")
        print(f"  Hour-of-day (UTC) histogram: {timing['hour_histogram']}")
        print(f"  Day-of-week histogram (0=Mon): {timing['dow_histogram']}")
        if timing['top_hour_skew'] > 2.0:
            print(f"  [MEDIUM confidence] Hour {timing['top_hour_utc']} UTC is "
                  f"{timing['top_hour_skew']:.1f}x more common than a uniform "
                  f"distribution would predict ({timing['top_hour_count']} of "
                  f"{timing['n_events']} solves) — suggests a scheduled/bot claim "
                  f"process running in a consistent timezone window.")
        else:
            print(f"  [LOW confidence] No strong time-of-day clustering — "
                  f"claims look spread across many independent actors/times.")

    # --- Progress rate (competitive landscape context) ---
    analyze_progress_rate(events)

    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    solver_clusters = [c for c in clusters if c.get('kind') != 'insider-housekeeping']
    insider_clusters = [c for c in clusters if c.get('kind') == 'insider-housekeeping']
    n_solver_puzzles = len(set(p for c in solver_clusters for p in c['puzzles']))
    print(f"  {len(events)} solved puzzles analyzed ({n_dust} dust/housekeeping), "
          f"{n_solver_puzzles} appear in a SOLVER cluster.")
    if n_solver_puzzles:
        print(f"  Practical takeaway: some solves are NOT independent random luck —")
        print(f"  a smaller number of operators account for a chunk of the easy solves.")
        print(f"  This doesn't change our strategy (still a lottery for #71), but it")
        print(f"  recalibrates expectations: organized capacity exists and is active.")
    if insider_clusters:
        insider_puzzles = sorted(set(p for c in insider_clusters for p in c['puzzles']))
        print(f"\n  [!] {len(insider_puzzles)} puzzles ({insider_puzzles}) were touched by")
        print(f"  the actual KEY-HOLDER in a dust/housekeeping transaction — meaning")
        print(f"  someone (likely the creator) provably still controls those private")
        print(f"  keys and chose NOT to claim the real reward. This doesn't help crack")
        print(f"  anything cryptographically, but confirms those puzzles are genuinely")
        print(f"  intentional, not abandoned/lost coins.")
    if not n_solver_puzzles and not insider_clusters:
        print(f"  No strong evidence of a dominant solver cluster — consistent with")
        print(f"  many independent actors solving puzzles as they become reachable.")


if __name__ == '__main__':
    main()
