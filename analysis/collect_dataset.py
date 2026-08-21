#!/usr/bin/env python3
"""
COLLECT DATASET — every fact we hold about every puzzle, in one file.

Analyses kept re-deriving the same things from four scattered sources, which is
how a stale copy sneaks in. This builds one authoritative table so every later
script reads identical inputs:

    n, bits, range_start/end, address, hash160,
    privkey (where known), pubkey x/y (derived, not trusted from cache),
    position-in-range, funded/balance, solved, pubkey_exposed

Derivation beats caching wherever possible: if the private key is known the
public key is COMPUTED from it rather than read from puzzle_pubkeys.json, so a
corrupted cache cannot quietly poison an analysis. Cached pubkeys are used only
for puzzles whose private key we do not have, and are then verified to lie on
the curve.

Offline by default. Pass --onchain to add live balance/spend data (slower, and
the only part that needs network).

Usage:
  python analysis/collect_dataset.py                 # offline, writes dataset
  python analysis/collect_dataset.py --onchain       # + live chain state
  python analysis/collect_dataset.py --csv           # also write a CSV
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ecc.curve import scalar_mul, G, P
from utils.address import point_to_address, decode_address_hash160
from utils.puzzle_registry import PUZZLE_ADDRESSES, puzzle_range
from analysis.rng_analysis import KNOWN_KEYS

OUT_JSON = os.path.join(os.path.dirname(__file__), '..', 'puzzle_dataset.json')
OUT_CSV = os.path.join(os.path.dirname(__file__), '..', 'puzzle_dataset.csv')
PUBKEY_CACHE = os.path.join(os.path.dirname(__file__), '..', 'puzzle_pubkeys.json')

# Public pools coordinate only on the smallest unsolved puzzles; everything else
# has no coverage data to fetch. Widen this if a pool ever opens another target.
POOLED_CANDIDATES = (71, 72, 73, 74, 75)


def _on_curve(x, y):
    return (y * y - x * x * x - 7) % P == 0


def _cached_pubkeys():
    """{n: (x, y)} from puzzle_pubkeys.json, skipping anything off-curve."""
    try:
        with open(PUBKEY_CACHE, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception:
        return {}
    out = {}
    for k, v in raw.items():
        try:
            n = int(k)
            h = (v.get('pubkey') if isinstance(v, dict) else v) or ''
            h = h.strip().lower()
            if len(h) == 130 and h.startswith('04'):
                x, y = int(h[2:66], 16), int(h[66:], 16)
            elif len(h) == 66 and h[:2] in ('02', '03'):
                from kangaroo.reconstruct import decompress_pubkey
                x, y = decompress_pubkey(h)
            else:
                continue
            if _on_curve(x, y):
                out[n] = (x, y)
        except Exception:
            continue
    return out


def _spend_facts(addr: str) -> dict:
    """Facts that only a SPEND reveals: the public key, and when it happened.

    An address gives up nothing until it spends. The moment it does, the signing
    input carries the public key in clear and the block carries a timestamp.
    That is exactly why the high multiples of five are attackable at all, and it
    is the only way to date a solve.

    The pubkey is taken from an input whose PREVOUT belongs to THIS address: a
    spending transaction usually has several inputs, and taking the first one
    would attribute somebody else's key to this puzzle.
    """
    out = {}
    try:
        from analysis.pubkey_pattern import (fetch_address_txs,
                                             extract_pubkey_from_input)
    except Exception:
        return out
    try:
        txs = fetch_address_txs(addr, limit=25) or []
    except Exception:
        return out

    best_time = None
    for tx in txs:
        for inp in tx.get('vin', []) or []:
            prev = inp.get('prevout') or {}
            if prev.get('scriptpubkey_address') != addr:
                continue
            if 'pubkey_exposed' not in out:
                try:
                    pk = extract_pubkey_from_input(inp)
                except Exception:
                    pk = None
                if pk:
                    out['pubkey_exposed'] = pk
                    out['pubkey_exposed_txid'] = tx.get('txid')
            stt = tx.get('status') or {}
            t, h = stt.get('block_time'), stt.get('block_height')
            # Earliest spend = when the prize was actually taken.
            if t and (best_time is None or t < best_time):
                best_time = t
                out['spent_at_unix'] = t
                out['spent_at'] = time.strftime('%Y-%m-%d %H:%M:%S',
                                                time.gmtime(t))
                out['spent_block'] = h
                out['spent_txid'] = tx.get('txid')
    return out


def build(onchain=False, pools=False, verbose=True):
    cached = _cached_pubkeys()
    rows = []
    status_cache = {}
    if onchain:
        from analysis.puzzle_status import fetch_address_status

    for n in sorted(PUZZLE_ADDRESSES):
        addr = PUZZLE_ADDRESSES[n]
        lo, hi = puzzle_range(n)
        row = {
            'n': n,
            'bits': n,
            'range_start': hex(lo),
            'range_end': hex(hi),
            'address': addr,
            'hash160': decode_address_hash160(addr).hex(),
            'privkey': None,
            'privkey_hex': None,
            'pubkey_x': None,
            'pubkey_y': None,
            'pubkey_source': None,
            'position': None,          # where the key sits in [0,1) of its range
        }

        k = KNOWN_KEYS.get(n)
        if k is not None:
            x, y = scalar_mul(k, G)
            # A key that does not reproduce its own address means the registry
            # and the key list disagree — record it rather than averaging over it.
            row['address_matches_key'] = (point_to_address(x, y) == addr)
            row['privkey'] = str(k)
            row['privkey_hex'] = hex(k)
            row['pubkey_x'] = hex(x)
            row['pubkey_y'] = hex(y)
            row['pubkey_source'] = 'derived-from-privkey'
            row['position'] = (k - lo) / (hi - lo + 1)
        elif n in cached:
            x, y = cached[n]
            row['pubkey_x'] = hex(x)
            row['pubkey_y'] = hex(y)
            row['pubkey_source'] = 'cache(on-curve verified)'

        if onchain:
            st = fetch_address_status(addr)
            time.sleep(0.1)
            if st:
                row['funded_sat'] = st['funded_sat']
                row['balance_sat'] = st['balance_sat']
                row['spent_sat'] = st['spent_sat']
                row['n_tx'] = st['n_tx']
                row['solved'] = bool(st['funded_sat'] and not st['balance_sat'])
                # reward encodes the puzzle number for #71+ (N * 0.1 BTC)
                row['reward_btc'] = st['funded_sat'] / 1e8
            # Only an address that has SPENT can reveal a pubkey or a date, so
            # skip the network round trip for the ones that never moved.
            if st and st.get('spent_sat'):
                row.update(_spend_facts(addr))
                time.sleep(0.1)
            if verbose and n % 10 == 0:
                print("\r  [chain] #%d ..." % n, end='', flush=True)

        # Only the actively-pooled puzzles are worth a lookup: the pools work on
        # #71-73 and nothing else, so querying all 150 was 150 network round
        # trips to learn "no data" 147 times.
        if pools and n in POOLED_CANDIDATES:
            # Two DIFFERENT things, deliberately kept apart. `pool_end` is a
            # contiguous frontier we may skip; `community_keys` is volume some
            # pool burned through at unknown positions. Merging them would make
            # us skip keys nobody checked.
            try:
                from analysis.pool_coverage import (get_pool_end, fetch_coverage,
                                                    community_stats)
                cov = fetch_coverage(n)
                if cov:
                    pe = get_pool_end(n)
                    row['pool_frontier'] = hex(pe) if pe else None
                    row['pool_ranges_done'] = cov.get('ranges_done')
                    row['pool_ranges_total'] = cov.get('total_ranges')
                    row['pool_source'] = cov.get('source')
                    row['pool_skippable_keys'] = (pe - lo) if pe else 0
                st = community_stats(n)
                if st:
                    row['community_keys'] = sum(d.get('keys_done') or 0
                                                for d in st)
                    row['community_sources'] = [d['source'] for d in st]
            except Exception:
                pass

        rows.append(row)

    if verbose and onchain:
        print("\r" + " " * 30 + "\r", end='')
    return rows


def main():
    ap = argparse.ArgumentParser(description="Build the unified puzzle dataset")
    ap.add_argument('--onchain', action='store_true', help="add live chain state")
    ap.add_argument('--csv', action='store_true', help="also write CSV")
    ap.add_argument('--pools', action='store_true',
                    help="add public-pool coverage (frontier + aggregate stats)")
    args = ap.parse_args()

    print("=" * 70)
    print("  COLLECTING PUZZLE DATASET")
    print("=" * 70)
    rows = build(onchain=args.onchain, pools=args.pools)

    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(rows, f, indent=1)

    have_priv = sum(1 for r in rows if r['privkey'])
    have_pub = sum(1 for r in rows if r['pubkey_x'])
    mism = [r['n'] for r in rows if r.get('address_matches_key') is False]

    print("  puzzles            : %d" % len(rows))
    print("  with private key   : %d" % have_priv)
    print("  with public key    : %d  (%d derived, %d from cache)"
          % (have_pub,
             sum(1 for r in rows if r['pubkey_source'] == 'derived-from-privkey'),
             sum(1 for r in rows if r['pubkey_source'] and 'cache' in r['pubkey_source'])))
    print("  key->address check : %s"
          % ("all %d consistent" % have_priv if not mism
             else "MISMATCH at %s" % mism))
    if args.pools:
        pooled = [r for r in rows if r.get('pool_frontier')]
        print("  with pool coverage : %d  (%s)"
              % (len(pooled),
                 ", ".join("#%d" % r['n'] for r in pooled) or "none"))
        comm = [r for r in rows if r.get('community_keys')]
        if comm:
            print("  aggregate-only     : %s"
                  % ", ".join("#%d %s keys" % (r['n'], f"{r['community_keys']:,}")
                              for r in comm))
    if args.onchain:
        exposed = [r for r in rows if r.get('pubkey_exposed')]
        dated = [r for r in rows if r.get('spent_at')]
        print("  pubkeys exposed    : %d  (%s)"
              % (len(exposed),
                 ", ".join("#%d" % r['n'] for r in exposed[:14]) or "none"))
        # `spent_at` is the FIRST spend, which is not the same as a solve: the
        # creator's own 2019-06-01 transaction spent from several puzzles purely
        # to publish their public keys. Label it for what it is.
        print("  first-spend dates  : %d  (creator's 2019 reveal counts here "
              "too, so this is not a solve date)" % len(dated))
        live = [r for r in exposed if not r.get('solved')]
        if live:
            print("  UNSOLVED + exposed : %s"
                  % ", ".join("#%d" % r['n'] for r in live))
        print("  solved (on-chain)  : %d"
              % sum(1 for r in rows if r.get('solved')))
    print("  written            : %s" % os.path.relpath(OUT_JSON))

    if args.csv:
        import csv
        cols = sorted({c for r in rows for c in r})
        with open(OUT_CSV, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        print("  written            : %s" % os.path.relpath(OUT_CSV))
    print("=" * 70)


if __name__ == '__main__':
    main()
