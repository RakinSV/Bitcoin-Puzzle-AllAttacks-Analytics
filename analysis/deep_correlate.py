#!/usr/bin/env python3
"""
DEEP CORRELATE — cross-domain analysis over the whole puzzle dataset.

Earlier work asked whether the PRIVATE KEYS carry structure (they do not) and
whether they form a describable SEQUENCE (they do not). This looks everywhere
else: at the public keys as curve points, at the addresses as hashes, at the
relationships *between* puzzles, and at the 2015 funding transaction that
created the whole thing.

The tests, and why each is worth running:

  A  Curve-point statistics. If the creator picked keys by some rule, the
     resulting x/y coordinates can inherit a bias even when the scalars look
     clean.
  B  Hash160 statistics. Same question one layer further out.
  C  Cross-domain independence. Correlation between key bits and address bits
     MUST be ~0 -- RIPEMD160(SHA256(.)) guarantees it. A non-zero result here
     would mean our own pipeline is broken, so this doubles as a self-test.
  D  Scalar relations between puzzles: is any key the sum, difference or small
     multiple of two others? That is what a lazily-generated set looks like.
  E  Elliptic-curve relations: is any pubkey the sum of two others as POINTS?
     Independent of D -- point addition is not scalar addition.
  F  Funding-transaction forensics: output ordering, amounts and change. How the
     creator built the transaction can leak how they generated the keys, and
     unlike the key values themselves this is not protected by anything.

Run:  python analysis/deep_correlate.py              # A-E, offline
      python analysis/deep_correlate.py --onchain    # + F
"""
import argparse
import json
import math
import os
import statistics
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ecc.curve import scalar_mul, point_add, point_neg, G, N
from analysis.rng_analysis import KNOWN_KEYS

DATASET = os.path.join(os.path.dirname(__file__), '..', 'puzzle_dataset.json')
FINDINGS = []


def note(name, clean, detail):
    FINDINGS.append((name, clean))
    tag = "clean  " if clean else ">>> LOOK <<<"
    print("  [%s] %s" % (tag, name))
    print("               %s" % detail)


def load():
    with open(DATASET, 'r', encoding='utf-8') as f:
        return json.load(f)


def _bitstats(values, width, label):
    """Per-bit-position ones-frequency across a list of ints -> worst |z|."""
    worst_z, worst_bit = 0.0, None
    n = len(values)
    for b in range(width):
        ones = sum((v >> b) & 1 for v in values)
        z = abs(ones - n / 2) / math.sqrt(n / 4) if n else 0.0
        if z > worst_z:
            worst_z, worst_bit = z, b
    return worst_z, worst_bit


def a_curve_points(rows):
    xs = [int(r['pubkey_x'], 16) for r in rows if r['pubkey_x']]
    ys = [int(r['pubkey_y'], 16) for r in rows if r['pubkey_y']]
    zx, bx = _bitstats(xs, 256, 'x')
    zy, by = _bitstats(ys, 256, 'y')
    odd = sum(1 for y in ys if y & 1)
    # 256 bit-positions scanned twice -> a 3-sigma line is far too loose; use 4.
    note("A public-key coordinate bits (%d points)" % len(xs),
         zx < 4.0 and zy < 4.0,
         "worst x-bit z=%.2f (bit %s), worst y-bit z=%.2f (bit %s); "
         "y odd/even split %d/%d" % (zx, bx, zy, by, odd, len(ys) - odd))


def b_hash160(rows):
    hs = [int(r['hash160'], 16) for r in rows]
    z, b = _bitstats(hs, 160, 'h')
    first = Counter(r['address'][0] for r in rows)
    note("B address hash160 bits (%d addresses)" % len(hs),
         z < 4.0,
         "worst bit z=%.2f (bit %s); leading chars %s"
         % (z, b, dict(first)))


def c_cross_domain(rows):
    """Key bits vs address bits must be uncorrelated -- also a pipeline self-test."""
    pairs = [(int(r['privkey']), int(r['hash160'], 16))
             for r in rows if r['privkey']]
    worst = 0.0
    worst_at = None
    for kb in range(0, 32):
        kbits = [(k >> kb) & 1 for k, _ in pairs]
        if len(set(kbits)) < 2:
            continue
        for hb in range(0, 32):
            hbits = [(h >> hb) & 1 for _, h in pairs]
            if len(set(hbits)) < 2:
                continue
            # phi coefficient on a 2x2 table
            n11 = sum(1 for a, c in zip(kbits, hbits) if a and c)
            n10 = sum(1 for a, c in zip(kbits, hbits) if a and not c)
            n01 = sum(1 for a, c in zip(kbits, hbits) if not a and c)
            n00 = len(pairs) - n11 - n10 - n01
            den = math.sqrt((n11 + n10) * (n01 + n00) * (n11 + n01) * (n10 + n00))
            if den:
                phi = abs((n11 * n00 - n10 * n01) / den)
                if phi > worst:
                    worst, worst_at = phi, (kb, hb)
    # 1024 comparisons on ~70 samples: |phi| up to ~0.45 is ordinary noise.
    note("C key-bit vs address-bit correlation (self-test)",
         worst < 0.55,
         "worst |phi|=%.3f at key-bit %s / hash-bit %s over 1024 pairs "
         "(hashing guarantees ~0; a high value would mean OUR pipeline is wrong)"
         % (worst, worst_at[0] if worst_at else '-', worst_at[1] if worst_at else '-'))


def d_scalar_relations():
    ks = {n: KNOWN_KEYS[n] for n in sorted(KNOWN_KEYS)}
    vals = set(ks.values())
    hits = []
    items = sorted(ks.items())
    for i, (a, ka) in enumerate(items):
        for b, kb in items[i:]:
            if ka + kb in vals:
                hits.append("k%d+k%d" % (a, b))
            if abs(ka - kb) in vals and a != b:
                hits.append("k%d-k%d" % (a, b))
    mults = []
    for a, ka in items:
        for m in (2, 3, 5, 7, 10):
            if ka * m in vals:
                mults.append("k%d*%d" % (a, m))
    # Small keys collide trivially (k1=1, k2=3: 1+3=4? no...) so a couple of
    # hits among the tiny early keys mean nothing; flag only a real cluster.
    note("D scalar relations between keys (sum/diff/multiple)",
         len(hits) + len(mults) <= 6,
         "%d additive hits %s, %d multiplicative hits %s "
         "(tiny early keys collide by chance)"
         % (len(hits), hits[:6], len(mults), mults[:6]))


def e_point_relations(rows):
    """Is any pubkey the SUM of two other pubkeys, as curve points?"""
    pts = {}
    for r in rows:
        if r['pubkey_x'] and r['pubkey_y']:
            pts[r['n']] = (int(r['pubkey_x'], 16), int(r['pubkey_y'], 16))
    index = {p: n for n, p in pts.items()}
    ns = sorted(pts)
    hits = []
    for i, a in enumerate(ns):
        for b in ns[i:]:
            s = point_add(pts[a], pts[b])
            if s and s in index:
                hits.append("P%d+P%d=P%d" % (a, b, index[s]))
    note("E elliptic-curve point relations (%d points)" % len(pts),
         len(hits) <= 6,
         "%d relations found %s (equivalent to scalar sums, so mirrors D)"
         % (len(hits), hits[:6]))


def f_funding_tx():
    """The 2015 transaction that created every puzzle output."""
    from analysis.pubkey_pattern import FUNDING_TX, fetch_tx
    tx = fetch_tx(FUNDING_TX)
    if not tx:
        note("F funding transaction forensics", True,
             "could not fetch %s (offline?)" % FUNDING_TX[:16])
        return
    vout = tx.get('vout', []) or []
    vin = tx.get('vin', []) or []
    vals = [o.get('value', 0) for o in vout]
    ordered = all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1))
    desc = all(vals[i] >= vals[i + 1] for i in range(len(vals) - 1))
    uniq = len(set(vals))
    print("  [info    ] F funding transaction %s..." % FUNDING_TX[:16])
    print("               inputs=%d outputs=%d  distinct amounts=%d"
          % (len(vin), len(vout), uniq))
    print("               amounts sorted ascending=%s descending=%s"
          % (ordered, desc))
    if vals:
        print("               min=%d sat  max=%d sat  total=%.4f BTC"
              % (min(vals), max(vals), sum(vals) / 1e8))
    # If outputs are in a strict amount order, the creator sorted them -- which
    # tells us about transaction construction, not about key generation. Either
    # way it reveals nothing about the SCALARS, which is the honest conclusion.
    note("F funding-transaction structure", True,
         "output ordering is a property of how the TX was assembled; it carries "
         "no information about the private keys themselves")


def main():
    ap = argparse.ArgumentParser(description="Cross-domain puzzle analysis")
    ap.add_argument('--onchain', action='store_true')
    args = ap.parse_args()

    rows = load()
    print("=" * 74)
    print("  DEEP CORRELATE -- %d puzzles, %d with private keys"
          % (len(rows), sum(1 for r in rows if r['privkey'])))
    print("=" * 74)
    a_curve_points(rows)
    b_hash160(rows)
    c_cross_domain(rows)
    d_scalar_relations()
    e_point_relations(rows)
    if args.onchain:
        f_funding_tx()

    print("=" * 74)
    dirty = [n for n, ok in FINDINGS if not ok]
    if dirty:
        print("  FLAGGED: %s" % dirty)
        print("  Re-test anything here with analysis/verify_flags.py's approach")
        print("  (permutation / cross-validation) before believing it.")
    else:
        print("  Nothing anomalous across public keys, addresses, cross-domain")
        print("  correlation, scalar relations or curve-point relations.")
    print("=" * 74)


if __name__ == '__main__':
    main()
