#!/usr/bin/env python3
"""
ARITHMETIC HUNT — pairwise operations, each judged against a null model.

Earlier work asked whether a sum or difference of two keys LANDS ON another key.
That is the weak form. The strong form is what this asks: across all 2,415 pairs,
does any difference, ratio or divisor occur more often than chance allows, and do
the keys carry arithmetic fingerprints (smoothness, Hamming weight, digital
roots) that a random draw would not?

THE METHOD MATTERS MORE THAN THE TESTS. Nine operations over 2,415 pairs is tens
of thousands of comparisons; run naively, it is guaranteed to produce
"discoveries". So every statistic here is computed twice: once on the real keys,
and once on TRIALS sets of fake keys drawn uniformly from the exact same
intervals. The verdict is the fraction of fake runs that match or beat the real
one -- an empirical p-value that already prices in however many pairs were
scanned. A real pattern must beat keys that are random *by construction*.

Run:  python analysis/arithmetic_hunt.py [--trials 300]
"""
import argparse
import math
import os
import random
import statistics
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from analysis.rng_analysis import KNOWN_KEYS

NS = sorted(KNOWN_KEYS)
KEYS = [KNOWN_KEYS[n] for n in NS]
RESULTS = []


def fake_keys(rng):
    """One synthetic puzzle set: uniform in each real interval."""
    return [rng.randrange(2 ** (n - 1), 2 ** n) for n in NS]


def verdict(name, real, nulls, higher_is_suspicious=True):
    """Empirical p-value: how often does random data match or beat reality?"""
    if higher_is_suspicious:
        hits = sum(1 for v in nulls if v >= real)
    else:
        hits = sum(1 for v in nulls if v <= real)
    p = hits / len(nulls) if nulls else 1.0
    clean = p >= 0.05
    RESULTS.append(clean)
    tag = "clean " if clean else ">>> p<0.05 <<<"
    med = statistics.median(nulls) if nulls else 0
    print("  [%s] %s" % (tag, name))
    print("            real=%.4g   random median=%.4g   p=%.3f"
          % (real, med, p))
    return p


# ---------------------------------------------------------------------------

def stat_repeated_differences(keys):
    """Largest count of any repeated pairwise difference."""
    c = Counter()
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            c[abs(keys[i] - keys[j])] += 1
    return max(c.values()) if c else 0


def stat_ratio_near_simple(keys):
    """How many pairwise ratios sit within 0.1% of a simple fraction p/q."""
    simple = []
    for q in range(1, 11):
        for p in range(1, 4 * q + 1):
            simple.append(p / q)
    simple = sorted(set(simple))
    hits = 0
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if keys[i] == 0:
                continue
            r = keys[j] / keys[i]
            if r > 45:
                continue
            for s in simple:
                if abs(r - s) < s * 0.001:
                    hits += 1
                    break
    return hits


def stat_pairwise_gcd(keys):
    """Mean log2 of gcd over all pairs -- structure inflates shared factors."""
    tot, cnt = 0.0, 0
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            g = math.gcd(keys[i], keys[j])
            tot += math.log2(g) if g > 1 else 0.0
            cnt += 1
    return tot / cnt if cnt else 0.0


def stat_smoothness(keys):
    """Count of keys divisible by any prime < 100 -- 'lazy' keys are smooth."""
    primes = [p for p in range(2, 100)
              if all(p % d for d in range(2, int(p ** 0.5) + 1))]
    return sum(1 for k in keys if any(k % p == 0 for p in primes))


def stat_hamming_deviation(keys):
    """Max |z| of popcount vs its expected value for that bit-width."""
    worst = 0.0
    for n, k in zip(NS, keys):
        w = n - 1                       # free bits below the fixed top bit
        if w < 8:
            continue
        ones = bin(k - 2 ** (n - 1)).count('1')
        z = abs(ones - w / 2) / math.sqrt(w / 4)
        worst = max(worst, z)
    return worst


def stat_digital_root(keys):
    """Chi-square of digital roots (1..9) -- a classic 'numerology' check."""
    c = Counter((k - 1) % 9 + 1 for k in keys)
    exp = len(keys) / 9
    return sum((c.get(d, 0) - exp) ** 2 / exp for d in range(1, 10))


def stat_hex_containment(keys):
    """How many keys appear as a hex substring of a larger key."""
    hexes = [format(k, 'x') for k in keys]
    hits = 0
    for i, a in enumerate(hexes):
        if len(a) < 4:
            continue
        for j, b in enumerate(hexes):
            if i != j and len(b) > len(a) and a in b:
                hits += 1
    return hits


def stat_low_bits_entropy(keys):
    """Chi-square of the low 6 bits -- a generator that rounds shows up here."""
    c = Counter(k & 63 for k in keys)
    exp = len(keys) / 64
    return sum((c.get(v, 0) - exp) ** 2 / exp for v in range(64))


def stat_position_parity_gap(keys):
    """|mean position of even-numbered puzzles - odd-numbered|."""
    ev, od = [], []
    for n, k in zip(NS, keys):
        pos = (k - 2 ** (n - 1)) / 2 ** (n - 1)
        (ev if n % 2 == 0 else od).append(pos)
    return abs(statistics.mean(ev) - statistics.mean(od)) if ev and od else 0.0


TESTS = [
    ("A most-repeated pairwise difference", stat_repeated_differences, True),
    ("B ratios near a simple fraction p/q", stat_ratio_near_simple, True),
    ("C mean log2(gcd) over all pairs", stat_pairwise_gcd, True),
    ("D smoothness (divisible by a prime<100)", stat_smoothness, True),
    ("E worst Hamming-weight deviation", stat_hamming_deviation, True),
    ("F digital-root chi-square", stat_digital_root, True),
    ("G key contained in another key (hex)", stat_hex_containment, True),
    ("H low-6-bit chi-square", stat_low_bits_entropy, True),
    ("I even-vs-odd puzzle position gap", stat_position_parity_gap, True),
]


def main():
    ap = argparse.ArgumentParser(description="Pairwise arithmetic hunt")
    ap.add_argument('--trials', type=int, default=300,
                    help="synthetic key sets for the null model (default 300)")
    args = ap.parse_args()

    rng = random.Random(20260818)
    print("=" * 74)
    print("  ARITHMETIC HUNT -- %d keys, %d pairs, %d null trials"
          % (len(KEYS), len(KEYS) * (len(KEYS) - 1) // 2, args.trials))
    print("  Every statistic is compared against keys drawn UNIFORMLY from the")
    print("  same intervals, so the p-value already prices in the pair count.")
    print("=" * 74)

    print("  building %d synthetic key sets..." % args.trials, flush=True)
    fakes = [fake_keys(rng) for _ in range(args.trials)]

    for name, fn, hi in TESTS:
        real = fn(KEYS)
        nulls = [fn(f) for f in fakes]
        verdict(name, real, nulls, hi)

    print("=" * 74)
    bad = sum(1 for ok in RESULTS if not ok)
    if bad == 0:
        print("  Nothing beats random. Every arithmetic property of the solved")
        print("  keys is reproduced by keys drawn uniformly at random -- which is")
        print("  what 'no pattern' actually looks like when tested properly.")
    else:
        print("  %d test(s) came in under p=0.05." % bad)
        print("  With %d tests, ~%.1f false positive(s) are EXPECTED. Re-test any")
        print("  survivor on its own before believing it."
              % (len(TESTS), 0.05 * len(TESTS)))
    print("=" * 74)


if __name__ == '__main__':
    main()
