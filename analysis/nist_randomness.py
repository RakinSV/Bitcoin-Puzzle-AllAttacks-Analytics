#!/usr/bin/env python3
"""
NIST-style Randomness Tests on the 70 Known Puzzle Keys
=======================================================
Formal statistical confirmation of what rng_analysis.py hinted at: are the
creator's private keys actually drawn from a uniform/random source, or is
there exploitable structure?

This is the "prove it with a hypothesis test" pass. rng_analysis.py reports
descriptive stats (mean position 0.52, std 0.27); this module runs the
classic NIST SP 800-22 battery and Wald-Wolfowitz runs test and emits real
p-values, so we can say with confidence "random — stop looking for an RNG
shortcut" or "NOT random — here is the bias to exploit".

Two levels of analysis:
  1. BIT-LEVEL  — concatenate the "free" bits of every key (each key #N has
     N bits, the top one is always 1, leaving N-1 random bits). Run the NIST
     monobit, runs, block-frequency (poker), and serial tests on that stream.
     This is the strongest test: it inspects the raw generator output.
  2. POSITION-LEVEL — each key's normalized position in its range (0..1).
     If the RNG is uniform these are i.i.d. Uniform(0,1). Run a chi-square
     uniformity test and a runs-about-the-median test.

A p-value >= 0.01 = consistent with randomness (NIST's standard threshold).
p < 0.01 = statistically significant deviation -> potential exploit.

Usage:
  python analysis/nist_randomness.py
  python analysis/nist_randomness.py --quiet
"""

import sys
import os
import math
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from analysis.rng_analysis import KNOWN_KEYS, puzzle_range, puzzle_position


def _positions() -> list:
    """Normalized key positions, skipping degenerate ranges (puzzle #1: [1,1])."""
    out = []
    for n in sorted(KNOWN_KEYS):
        lo, hi = puzzle_range(n)
        if hi == lo:
            continue
        out.append(puzzle_position(n, KNOWN_KEYS[n]))
    return out


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def free_bits(n: int, k: int) -> list:
    """Return the N-1 'free' bits of puzzle #N's key, MSB first.

    Key #N lies in [2^(N-1), 2^N - 1], so bit (N-1) is ALWAYS 1 and carries
    no entropy. The remaining bits N-2 .. 0 are the random part.
    """
    return [(k >> i) & 1 for i in range(n - 2, -1, -1)]


def build_bitstream() -> list:
    """Concatenate the free bits of all known keys, in puzzle order."""
    stream = []
    for n in sorted(KNOWN_KEYS):
        stream.extend(free_bits(n, KNOWN_KEYS[n]))
    return stream


def _verdict(p: float) -> str:
    return "RANDOM (pass)" if p >= 0.01 else "*** NON-RANDOM (FAIL) ***"


# ──────────────────────────────────────────────────────────────────
# NIST SP 800-22 tests (bit level)
# ──────────────────────────────────────────────────────────────────

def monobit_test(bits: list) -> dict:
    """Frequency (Monobit) test. Are 0s and 1s balanced overall?"""
    n = len(bits)
    s = sum(2 * b - 1 for b in bits)          # +1 per 1-bit, -1 per 0-bit
    s_obs = abs(s) / math.sqrt(n)
    p = math.erfc(s_obs / math.sqrt(2))
    ones = sum(bits)
    return {'name': 'Monobit (frequency)', 'n': n, 'ones': ones,
            'zeros': n - ones, 'ratio': ones / n, 'p': p}


def runs_test(bits: list) -> dict:
    """NIST Runs test. Tests oscillation rate between runs of 0s and 1s."""
    n = len(bits)
    pi = sum(bits) / n
    # Pre-condition required by NIST before the runs test is meaningful
    if abs(pi - 0.5) >= (2.0 / math.sqrt(n)):
        return {'name': 'Runs', 'n': n, 'p': 0.0, 'runs': None,
                'note': 'monobit pre-test failed -> runs test not applicable'}
    vn = 1 + sum(1 for i in range(1, n) if bits[i] != bits[i - 1])
    num = abs(vn - 2 * n * pi * (1 - pi))
    den = 2 * math.sqrt(2 * n) * pi * (1 - pi)
    p = math.erfc(num / den)
    return {'name': 'Runs', 'n': n, 'runs': vn,
            'expected_runs': 2 * n * pi * (1 - pi), 'p': p}


def poker_test(bits: list, m: int = 4) -> dict:
    """Poker / block-frequency test (FIPS 140-2 style chi-square on m-bit groups).

    Splits the stream into non-overlapping m-bit blocks and checks that all
    2^m patterns appear with the frequency expected under randomness.
    """
    n = len(bits)
    k = n // m                               # number of full blocks
    if k < 5 * (1 << m):
        # Not enough data for a reliable chi-square at this block size
        pass
    counts = {}
    for i in range(k):
        block = bits[i * m:(i + 1) * m]
        val = 0
        for b in block:
            val = (val << 1) | b
        counts[val] = counts.get(val, 0) + 1
    expected = k / (1 << m)
    chi2 = sum((counts.get(v, 0) - expected) ** 2 / expected
               for v in range(1 << m))
    df = (1 << m) - 1
    p = _chi2_sf(chi2, df)
    return {'name': f'Poker (block={m})', 'blocks': k, 'chi2': chi2,
            'df': df, 'p': p}


def serial_autocorr_test(bits: list, lag: int = 1) -> dict:
    """Lag-k autocorrelation test. Adjacent bits should be uncorrelated."""
    n = len(bits)
    matches = sum(1 for i in range(n - lag) if bits[i] == bits[i + lag])
    total = n - lag
    # Under H0 each pair matches with prob 0.5
    z = abs(matches - total / 2) / (math.sqrt(total) / 2)
    p = math.erfc(z / math.sqrt(2))
    return {'name': f'Autocorrelation (lag={lag})', 'matches': matches,
            'total': total, 'ratio': matches / total, 'p': p}


# ──────────────────────────────────────────────────────────────────
# Position-level tests
# ──────────────────────────────────────────────────────────────────

def position_uniformity_test(bins: int = 10) -> dict:
    """Chi-square test that normalized key positions are Uniform(0,1)."""
    positions = _positions()
    counts = [0] * bins
    for p in positions:
        idx = min(int(p * bins), bins - 1)
        counts[idx] += 1
    expected = len(positions) / bins
    chi2 = sum((c - expected) ** 2 / expected for c in counts)
    df = bins - 1
    pval = _chi2_sf(chi2, df)
    return {'name': f'Position uniformity (chi2, {bins} bins)',
            'n': len(positions), 'counts': counts, 'chi2': chi2,
            'df': df, 'p': pval}


def position_runs_about_median_test() -> dict:
    """Wald-Wolfowitz runs test on positions above/below the median."""
    positions = _positions()
    med = sorted(positions)[len(positions) // 2]
    seq = [1 if p >= med else 0 for p in positions if p != med]
    n1 = sum(seq)
    n0 = len(seq) - n1
    if n1 == 0 or n0 == 0:
        return {'name': 'Position runs-about-median', 'p': 1.0,
                'note': 'degenerate'}
    runs = 1 + sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])
    mean = 1 + (2 * n1 * n0) / (n1 + n0)
    var = (2 * n1 * n0 * (2 * n1 * n0 - n1 - n0)) / \
          ((n1 + n0) ** 2 * (n1 + n0 - 1))
    if var <= 0:
        return {'name': 'Position runs-about-median', 'p': 1.0,
                'note': 'zero variance'}
    z = (runs - mean) / math.sqrt(var)
    p = math.erfc(abs(z) / math.sqrt(2))
    return {'name': 'Position runs-about-median', 'runs': runs,
            'expected': mean, 'z': z, 'p': p}


# ──────────────────────────────────────────────────────────────────
# chi-square survival function (no scipy dependency)
# ──────────────────────────────────────────────────────────────────

def _chi2_sf(x: float, df: int) -> float:
    """P(Chi2_df > x). Uses the regularized upper incomplete gamma Q(df/2, x/2)."""
    if x <= 0:
        return 1.0
    return _gammaincc(df / 2.0, x / 2.0)


def _gammaincc(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a,x) = 1 - P(a,x)."""
    if x < 0 or a <= 0:
        return 1.0
    if x < a + 1.0:
        return 1.0 - _gamma_series(a, x)
    return _gamma_cf(a, x)


def _gamma_series(a: float, x: float) -> float:
    """Lower regularized incomplete gamma P(a,x) via series expansion."""
    gln = math.lgamma(a)
    if x == 0:
        return 0.0
    ap = a
    s = 1.0 / a
    delta = s
    for _ in range(1000):
        ap += 1
        delta *= x / ap
        s += delta
        if abs(delta) < abs(s) * 1e-15:
            break
    return s * math.exp(-x + a * math.log(x) - gln)


def _gamma_cf(a: float, x: float) -> float:
    """Upper regularized incomplete gamma Q(a,x) via continued fraction."""
    gln = math.lgamma(a)
    tiny = 1e-30
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return math.exp(-x + a * math.log(x) - gln) * h


# ──────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────

def run_all(quiet: bool = False) -> dict:
    bits = build_bitstream()

    print("\n" + "=" * 64)
    print("  NIST-STYLE RANDOMNESS BATTERY")
    print(f"  Source: {len(KNOWN_KEYS)} known puzzle keys (#"
          f"{min(KNOWN_KEYS)}-#{max(KNOWN_KEYS)})")
    print(f"  Bit-level stream: {len(bits):,} free bits "
          f"(top bit of each key excluded — always 1)")
    print("=" * 64)

    results = []

    print("\n--- BIT-LEVEL TESTS (raw generator output) ---")
    for test in (monobit_test(bits),
                 runs_test(bits),
                 poker_test(bits, m=4),
                 poker_test(bits, m=8),
                 serial_autocorr_test(bits, lag=1),
                 serial_autocorr_test(bits, lag=2),
                 serial_autocorr_test(bits, lag=8)):
        results.append(test)
        _print_result(test, quiet)

    print("\n--- POSITION-LEVEL TESTS (key placement within each range) ---")
    for test in (position_uniformity_test(bins=10),
                 position_runs_about_median_test()):
        results.append(test)
        _print_result(test, quiet)

    # Summary
    fails = [r for r in results if r.get('p', 1.0) < 0.01]
    print("\n" + "=" * 64)
    if fails:
        print(f"  VERDICT: {len(fails)} of {len(results)} tests FAILED (p < 0.01).")
        print("  Statistically significant structure detected — worth a closer")
        print("  look. Failed tests:")
        for r in fails:
            print(f"    - {r['name']}: p = {r['p']:.5f}")
        print("\n  NOTE: with only ~2,400 bits, a single marginal fail is often")
        print("  noise. Two or more independent fails is the real signal.")
    else:
        print(f"  VERDICT: all {len(results)} tests PASS (p >= 0.01).")
        print("  The creator's keys are statistically indistinguishable from a")
        print("  uniform random source. No RNG shortcut to exploit — brute force")
        print("  (GPU lottery / Kangaroo-on-pubkey) is the correct strategy.")
    print("=" * 64)

    return {'bits': len(bits), 'results': results, 'fails': len(fails)}


def _print_result(r: dict, quiet: bool):
    p = r.get('p', 1.0)
    print(f"\n  [{r['name']}]")
    if not quiet:
        for k, v in r.items():
            if k in ('name', 'p'):
                continue
            if isinstance(v, float):
                print(f"      {k:14s}: {v:.6f}")
            else:
                print(f"      {k:14s}: {v}")
    print(f"      p-value       : {p:.6f}  ->  {_verdict(p)}")


def main():
    parser = argparse.ArgumentParser(
        description='NIST-style randomness tests on known puzzle keys')
    parser.add_argument('--quiet', action='store_true',
                        help='Print only test names and p-values')
    args = parser.parse_args()
    run_all(quiet=args.quiet)


if __name__ == '__main__':
    main()
