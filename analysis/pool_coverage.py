#!/usr/bin/env python3
"""
POOL COVERAGE COLLECTOR — read what the public pools have already scanned.

Public puzzle pools publish how much of a keyspace they have swept. They sweep
SEQUENTIALLY from the start of the range, so their progress is one contiguous
block [k_start, pool_end). Our lottery picks random windows; every window that
lands inside that block re-checks keys someone already checked. Knowing pool_end
lets us confine our random draws to virgin territory.

STRICTLY READ-ONLY. This module only GETs public progress pages. It never
registers, never requests a work range, never reports a scanned range, and never
transmits our keys, progress or results anywhere. We take coordination data; we
publish nothing. (The pools' write API needs a UserToken we deliberately do not
obtain.) Requests are cached for hours so we stay a polite single page view.

Usage:
  python analysis/pool_coverage.py                  # all tracked puzzles (cached)
  python analysis/pool_coverage.py --puzzle 71      # one puzzle
  python analysis/pool_coverage.py --refresh        # force re-fetch
  python analysis/pool_coverage.py --json
"""
import sys
import os
import re
import json
import time
import argparse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.puzzle_registry import puzzle_range

CACHE_FILE = os.path.join(os.path.dirname(__file__), '..',
                          'pool_coverage_cache.json')
CACHE_TTL = 6 * 3600           # pools move slowly; 6h keeps us polite
UA = 'btc-puzzle-research/1.0 (read-only coverage reader)'
TIMEOUT = 20


# ---------------------------------------------------------------------------
# Sources. Each returns dict(ranges_done, total_ranges, keys_checked) or None.
# Add a new pool by writing a parser and appending it to SOURCES.
# ---------------------------------------------------------------------------

def _get_text(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
        return raw.decode('utf-8', errors='replace')
    except Exception:
        return None


def _nums(s: str) -> list[int]:
    """All comma-formatted integers in a string, largest-first context kept."""
    return [int(m.replace(',', '')) for m in re.findall(r'\d[\d,]{2,}', s)]


def src_btcpuzzle_info(n: int) -> dict | None:
    """btcpuzzle.info publishes 'X scanned / Y' ranges plus a keys counter."""
    html = _get_text(f'https://btcpuzzle.info/puzzle/{n}')
    if not html:
        return None
    text = re.sub(r'<[^>]+>', ' ', html)          # strip tags
    text = re.sub(r'\s+', ' ', text)

    m = re.search(r'([\d,]+)\s*scanned\s*/\s*([\d,]+)', text, re.I)
    if not m:
        return None
    done = int(m.group(1).replace(',', ''))
    total = int(m.group(2).replace(',', ''))
    if total <= 0 or done < 0 or done > total:
        return None

    # keys_checked is derived from ranges_done in get_pool_end/describe rather
    # than scraped: the page also prints the chunk size (2^45) and a raw regex
    # happily grabs that instead, which understates coverage by ~6 orders.
    return {'source': 'btcpuzzle.info', 'ranges_done': done,
            'total_ranges': total}


def src_secretscan(n: int) -> dict | None:
    """secretscan.org publishes its own sweep progress for some puzzles."""
    html = _get_text(f'https://secretscan.org/puzzle/{n}')
    if not html:
        return None
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text)
    m = re.search(r'([\d,]+)\s*(?:scanned|checked)\s*/\s*([\d,]+)', text, re.I)
    if not m:
        return None
    done = int(m.group(1).replace(',', ''))
    total = int(m.group(2).replace(',', ''))
    if total <= 0 or not (0 <= done <= total):
        return None
    return {'source': 'secretscan.org', 'ranges_done': done,
            'total_ranges': total}


# Sources are tried in order and the LARGEST coverage wins, so adding a pool can
# only ever improve how much already-swept space we skip.
SOURCES = [src_btcpuzzle_info, src_secretscan]


def fetch_all_statuses(refresh: bool = False) -> dict:
    """{puzzle_n: 'solved'|'unsolved'} decided ON-CHAIN, not from a pool page.

    Deliberately NOT scraped: the pool index renders its three "ongoing" puzzles
    in a header block with no status label, so a row-regex silently attaches the
    NEXT row's label to them — it reported #72 as solved while 7.2 BTC was
    verifiably still sitting at its address. A prize that is still unspent is the
    only trustworthy definition of unsolved, so we ask the blockchain: funded and
    non-zero balance = unsolved.
    """
    from utils.puzzle_registry import PUZZLE_ADDRESSES, all_puzzle_numbers
    from analysis.puzzle_status import load_cache as _pz_cache, refresh_status

    cache = _pz_cache() or {}
    if refresh or not cache:
        try:
            refresh_status(force=refresh)
            cache = _pz_cache() or {}
        except Exception:
            pass

    out = {}
    for n in all_puzzle_numbers():
        ent = cache.get(str(n)) or cache.get(n)
        if not isinstance(ent, dict):
            continue
        funded = ent.get('funded_sat', 0)
        bal = ent.get('balance_sat', ent.get('balance', 0))
        if funded:
            out[n] = 'solved' if not bal else 'unsolved'
    return out


# ---------------------------------------------------------------------------
# Cache + public API
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(c: dict):
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(c, f, indent=1)
    except Exception:
        pass


def fetch_coverage(n: int, refresh: bool = False) -> dict | None:
    """Best (largest) known coverage for puzzle n across all sources."""
    cache = _load_cache()
    key = str(n)
    ent = cache.get(key)
    if not refresh and ent and (time.time() - ent.get('ts', 0)) < CACHE_TTL:
        return ent.get('data')

    best = None
    for src in SOURCES:
        try:
            d = src(n)
        except Exception:
            d = None
        if d and (best is None or d['ranges_done'] / d['total_ranges']
                  > best['ranges_done'] / best['total_ranges']):
            best = d

    if best is None:
        # keep serving a stale entry rather than losing the info entirely
        return ent.get('data') if ent else None

    cache[key] = {'ts': time.time(), 'data': best}
    _save_cache(cache)
    return best


def get_pool_end(n: int, refresh: bool = False) -> int:
    """Absolute key index up to which pools have swept puzzle n (0 = unknown).

    The pools sweep from the start of the range, so everything below the
    returned value is already covered and our random draws should start above it.
    """
    d = fetch_coverage(n, refresh=refresh)
    if not d:
        return 0
    k_start, k_end = puzzle_range(n)
    span = k_end - k_start + 1
    total = d['total_ranges']
    if total <= 0:
        return 0
    # Derive the chunk size from the real keyspace, so it self-corrects if the
    # pool changes its chunking (never hardcode 2^45).
    covered = span * d['ranges_done'] // total
    return min(k_start + covered, k_end)


def describe(n: int, refresh: bool = False) -> str:
    d = fetch_coverage(n, refresh=refresh)
    if not d:
        return f"  #{n}: no pool data"
    k_start, k_end = puzzle_range(n)
    span = k_end - k_start + 1
    pct = d['ranges_done'] / d['total_ranges'] * 100
    pe = get_pool_end(n, refresh=False)
    keys = pe - k_start
    return (f"  #{n}: {d['ranges_done']:,}/{d['total_ranges']:,} ranges "
            f"= {pct:.4f}%  ({d['source']})\n"
            f"        keys already swept by the pool: {keys:,}\n"
            f"        pool_end = {hex(pe)}  -> our random draws start above it\n"
            f"        virgin space left: {(k_end - pe) / span * 100:.4f}%")


def main():
    ap = argparse.ArgumentParser(description="Read public pool coverage (read-only)")
    ap.add_argument('--puzzle', type=int, action='append',
                    help="puzzle number (repeatable); default: every unsolved one")
    ap.add_argument('--refresh', action='store_true')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--max', type=int, default=160,
                    help="highest puzzle to consider when scanning all")
    args = ap.parse_args()

    if args.puzzle:
        nums = args.puzzle
    else:
        # Every UNSOLVED puzzle, straight from the pool index (one request).
        st = fetch_all_statuses(refresh=args.refresh)
        nums = [n for n in sorted(st) if st[n] == 'unsolved' and n <= args.max]
        if not nums:
            nums = [71, 72, 73]
        print(f"  [index] {len(st)} puzzles known, "
              f"{len(nums)} unsolved <= #{args.max}")
    if args.json:
        out = {}
        for n in nums:
            d = fetch_coverage(n, refresh=args.refresh)
            if d:
                d = dict(d)
                d['pool_end'] = str(get_pool_end(n))
            out[n] = d
        print(json.dumps(out, indent=1))
        return

    print("=" * 72)
    print("  POOL COVERAGE (read-only — we take coordination data, publish nothing)")
    print("=" * 72)
    for n in nums:
        print(describe(n, refresh=args.refresh))
    print("=" * 72)
    print("  Use with the lottery:  main.py --puzzle 71 --mode gpu "
          "--pure-random --pool-avoid")
    print("=" * 72)


if __name__ == '__main__':
    main()
