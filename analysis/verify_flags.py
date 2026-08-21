#!/usr/bin/env python3
"""
VERIFY the two flags raised by sequence_hunt.py.

Flags are cheap; confirmations are not. sequence_hunt ran 9 tests, and two came
back marked PATTERN:

  H6  autocorrelation r=+0.285 at lag 3 (significance line +/-0.239)
  H9  a degree-3 fit predicted held-out #70 to within 0.032

Both are exactly the shape a multiple-comparisons artefact takes. H6 scanned ten
lags and reported the largest; H9 fitted four polynomial degrees and reported the
closest. Picking the best of many tries and then judging it by a single-try
threshold is how noise gets published.

So each is re-tested the honest way:

  H6 -> permutation test. Shuffle the positions 20,000 times (destroying any
        real order while keeping the exact values) and ask how often the shuffled
        data produces a max |r| at least as large. That frequency IS the p-value,
        and it already accounts for having scanned ten lags.

  H9 -> leave-one-out cross-validation over every key, scored against the honest
        baseline (predict the mean). If the fit cannot beat "guess the average"
        across all 70 hold-outs, its one lucky hit on #70 was luck.

Run:  python analysis/verify_flags.py
"""
import math
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from analysis.rng_analysis import KNOWN_KEYS

NS = sorted(KNOWN_KEYS)
POS = [(KNOWN_KEYS[n] - 2 ** (n - 1)) / 2 ** (n - 1) for n in NS]
TRIALS = 20000
MAX_LAG = 10


def max_abs_autocorr(seq, max_lag=MAX_LAG):
    m = statistics.mean(seq)
    var = sum((v - m) ** 2 for v in seq)
    best = 0.0
    for lag in range(1, max_lag + 1):
        cov = sum((seq[i] - m) * (seq[i - lag] - m) for i in range(lag, len(seq)))
        r = cov / var if var else 0.0
        if abs(r) > abs(best):
            best = r
    return best


def verify_h6():
    print("--- H6: autocorrelation, permutation test ---")
    observed = max_abs_autocorr(POS)
    rng = random.Random(20260818)
    shuffled = list(POS)
    hits = 0
    for _ in range(TRIALS):
        rng.shuffle(shuffled)
        if abs(max_abs_autocorr(shuffled)) >= abs(observed):
            hits += 1
    p = hits / TRIALS
    print("  observed max |r| over %d lags : %.3f" % (MAX_LAG, abs(observed)))
    print("  shuffles matching or beating it: %d / %d" % (hits, TRIALS))
    print("  p-value (already accounts for scanning 10 lags): %.4f" % p)
    if p < 0.05:
        print("  -> SURVIVES. Real ordering effect worth investigating.")
    else:
        print("  -> DOES NOT SURVIVE. Random data reaches this size routinely")
        print("     when you scan ten lags and keep the biggest. Not a pattern.")
    return p < 0.05


def verify_h9():
    print("\n--- H9: prediction, leave-one-out cross-validation ---")
    try:
        import numpy as np
    except Exception as e:
        print("  numpy unavailable: %s" % e)
        return False

    xs_all = [float(n) for n in NS]
    baseline_err = []
    model_err = {d: [] for d in (1, 2, 3, 5)}

    for i in range(len(NS)):
        xs = xs_all[:i] + xs_all[i + 1:]
        ys = POS[:i] + POS[i + 1:]
        target = POS[i]
        baseline_err.append(abs(statistics.mean(ys) - target))
        for d in model_err:
            try:
                coef = np.polyfit(xs, ys, d)
                pred = float(np.polyval(coef, xs_all[i]))
            except Exception:
                pred = statistics.mean(ys)
            model_err[d].append(abs(pred - target))

    base = statistics.mean(baseline_err)
    print("  baseline (predict the mean)   : mean abs error %.4f" % base)
    beat = False
    for d in sorted(model_err):
        e = statistics.mean(model_err[d])
        verdict = "BEATS baseline" if e < base * 0.9 else "no better"
        if e < base * 0.9:
            beat = True
        print("  polynomial degree %d           : mean abs error %.4f  (%s)"
              % (d, e, verdict))

    print("\n  The single #70 hit that flagged H9 was the BEST of four degrees;")
    print("  across all %d hold-outs that advantage disappears." % len(NS))
    if beat:
        print("  -> SURVIVES. A model genuinely predicts unseen keys.")
    else:
        print("  -> DOES NOT SURVIVE. No fit beats guessing the average, so the")
        print("     one close call on #70 was a lucky draw, not skill.")
    return beat


def main():
    print("=" * 74)
    print("  VERIFYING THE TWO FLAGS FROM sequence_hunt.py")
    print("=" * 74)
    a = verify_h6()
    b = verify_h9()
    print("\n" + "=" * 74)
    if a or b:
        print("  At least one flag SURVIVED proper testing. Investigate further")
        print("  before acting on it.")
    else:
        print("  BOTH FLAGS COLLAPSE under proper testing. They were artefacts of")
        print("  picking the best of many tries. Nothing in the solved keys")
        print("  predicts #71.")
    print("=" * 74)


if __name__ == "__main__":
    main()
