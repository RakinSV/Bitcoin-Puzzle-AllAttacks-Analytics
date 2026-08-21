#!/usr/bin/env python3
"""
SEQUENCE HUNT — is the list of solved keys DESCRIBABLE by a formula?

key_structure_hunt.py already ruled out the structural shortcuts (a master
prefix, an affine/LCG law, compressibility, bit bias, shared low bits, a common
factor). This asks the other question people reach for first: Fibonacci, a
polynomial, the golden ratio, a modular rule, a hidden period.

Everything is tested on the NORMALISED position

    p_n = (k_n - 2^(n-1)) / 2^(n-1)      in [0, 1)

i.e. where the key sits inside its own interval. That matters: the raw keys
roughly double at every step BY CONSTRUCTION, because each puzzle's interval is
twice the previous one. Any test run on raw values therefore "discovers" a ratio
near 2 and a gorgeous exponential fit that say nothing about the creator at all.
Normalising strips out the design and leaves only the choices.

Run:  python analysis/sequence_hunt.py
"""
import math
import os
import statistics
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from analysis.rng_analysis import KNOWN_KEYS

NS = sorted(KNOWN_KEYS)
KEYS = [KNOWN_KEYS[n] for n in NS]
POS = [(KNOWN_KEYS[n] - 2 ** (n - 1)) / 2 ** (n - 1) for n in NS]

VERDICTS = []


def report(name, is_random, detail):
    VERDICTS.append(is_random)
    tag = "random " if is_random else ">>> PATTERN <<<"
    print("  [%s] %s" % (tag, name))
    print("                %s" % detail)


def h1_fibonacci():
    """k_n = k_{n-1} + k_{n-2}, and: is any key a sum of two earlier keys?"""
    exact = tested = 0
    for i in range(2, len(KEYS)):
        if KEYS[i] == KEYS[i - 1] + KEYS[i - 2]:
            exact += 1
        tested += 1
    kset = set(KEYS)
    sums = 0
    for i in range(len(KEYS)):
        for j in range(i, len(KEYS)):
            if KEYS[i] + KEYS[j] in kset:
                sums += 1
    report("H1 Fibonacci recurrence (k_n = k_n-1 + k_n-2)",
           exact == 0,
           "%d/%d consecutive triples satisfy it; %d key(s) equal a sum of two "
           "earlier keys" % (exact, tested, sums))


def h2_ratio():
    phi = (1 + 5 ** 0.5) / 2
    ratios = [POS[i] / POS[i - 1] for i in range(1, len(POS)) if POS[i - 1] > 1e-9]
    med = statistics.median(ratios)
    near_phi = sum(1 for r in ratios if abs(r - phi) < 0.05)
    near_2 = sum(1 for r in ratios if abs(r - 2.0) < 0.05)
    raw = statistics.median([KEYS[i] / KEYS[i - 1] for i in range(1, len(KEYS))])
    report("H2 ratio between successive positions (phi? 2?)",
           near_phi <= 3 and near_2 <= 3,
           "median ratio %.3f; %d near phi=1.618, %d near 2.0 "
           "(raw-key ratio is %.2f -- that IS the design, not a finding)"
           % (med, near_phi, near_2, raw))


def h3_polynomial():
    xs = [float(n) for n in NS]
    ys = POS
    out, best = [], 0.0
    try:
        import numpy as np
        for deg in (1, 2, 3, 5):
            coef = np.polyfit(xs, ys, deg)
            pred = np.polyval(coef, xs)
            ss_res = float(((np.array(ys) - pred) ** 2).sum())
            ss_tot = float(((np.array(ys) - np.mean(ys)) ** 2).sum())
            r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
            best = max(best, r2)
            out.append("deg%d R2=%.4f" % (deg, r2))
    except Exception as e:
        out.append("numpy unavailable: %s" % e)
    report("H3 polynomial in the puzzle number",
           best < 0.30,
           "%s  (R2 near 1 = predictable, near 0 = noise)" % ", ".join(out))


def h4_modular():
    worst = (0, 0.0, 0.0)
    for m in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31):
        c = Counter(k % m for k in KEYS)
        exp = len(KEYS) / m
        chi2 = sum((c.get(r, 0) - exp) ** 2 / exp for r in range(m))
        crit = 2.5 * (m - 1) + 8            # rough 1% critical value
        if chi2 / crit > worst[2]:
            worst = (m, chi2, chi2 / crit)
    report("H4 modular residues (mod 3..31)",
           worst[2] < 1.0,
           "worst is mod %d: chi2=%.1f, %.2fx its critical value (>1 = biased)"
           % (worst[0], worst[1], worst[2]))


def h5_benford():
    lead = Counter(int(str(k)[0]) for k in KEYS)
    n = len(KEYS)
    dev = 0.0
    for d in range(1, 10):
        exp = n * math.log10(1 + 1.0 / d)
        dev = max(dev, abs(lead.get(d, 0) - exp) / max(exp, 1e-9))
    report("H5 leading-digit (Benford) profile",
           True,
           "max relative deviation %.2f -- informational only: uniform keys of "
           "mixed magnitude are NOT expected to obey Benford" % dev)


def h6_autocorr():
    m = statistics.mean(POS)
    var = sum((p - m) ** 2 for p in POS)
    worst_lag, worst_r = 0, 0.0
    for lag in range(1, 11):
        cov = sum((POS[i] - m) * (POS[i - lag] - m) for i in range(lag, len(POS)))
        r = cov / var if var else 0.0
        if abs(r) > abs(worst_r):
            worst_lag, worst_r = lag, r
    line = 2 / math.sqrt(len(POS))
    report("H6 autocorrelation of positions (lags 1-10)",
           abs(worst_r) < line,
           "strongest lag %d: r=%+.3f, significance line +/-%.3f"
           % (worst_lag, worst_r, line))


def h7_spectrum():
    N = len(POS)
    m = statistics.mean(POS)
    x = [p - m for p in POS]
    best_k, best_p, total = 0, 0.0, 0.0
    for k in range(1, N // 2):
        re = sum(x[t] * math.cos(2 * math.pi * k * t / N) for t in range(N))
        im = sum(x[t] * math.sin(2 * math.pi * k * t / N) for t in range(N))
        p = re * re + im * im
        total += p
        if p > best_p:
            best_k, best_p = k, p
    share = best_p / total if total else 0.0
    expected = 4.0 / (N // 2)
    report("H7 spectral peak (hidden periodicity)",
           share < 3 * expected,
           "strongest period ~%.1f steps holds %.1f%% of power "
           "(white noise expects ~%.1f%%)"
           % (N / best_k if best_k else 0, share * 100, expected * 100))


def h8_hexrepeat():
    grams = Counter()
    for n in NS:
        h = format(KNOWN_KEYS[n], "x")
        for i in range(len(h) - 3):
            grams[h[i:i + 4]] += 1
    top, cnt = grams.most_common(1)[0]
    total = sum(grams.values())
    exp = total / 65536.0
    report("H8 repeated 4-hex-digit patterns",
           cnt <= max(3, exp * 8),
           "most common nibble-quad %r appears %dx (uniform expectation %.2f)"
           % (top, cnt, exp))


def h9_predict_71():
    """The only test that matters: do the fits actually predict a known key?

    Hold out #70, fit on #1..#69, predict, and compare with the truth. A model
    that cannot recover a key it was not shown has no business predicting #71.
    """
    try:
        import numpy as np
    except Exception:
        report("H9 hold-out prediction of #70", True, "numpy unavailable")
        return
    xs = [float(n) for n in NS[:-1]]
    ys = POS[:-1]
    truth = POS[-1]
    lines = []
    best_err = 1.0
    for deg in (1, 2, 3, 5):
        coef = np.polyfit(xs, ys, deg)
        pred = float(np.polyval(coef, float(NS[-1])))
        err = abs(pred - truth)
        best_err = min(best_err, err)
        lines.append("deg%d pred=%.3f" % (deg, pred))
    # A blind guess of 0.5 is wrong by 0.25 on average; beating that materially
    # would be the first real sign of predictability.
    report("H9 hold-out prediction of #70 (fit on #1..#69)",
           best_err > 0.15,
           "%s vs truth %.3f -- best error %.3f (a blind 0.5 guess averages 0.25)"
           % (", ".join(lines), truth, best_err))


def main():
    print("=" * 74)
    print("  SEQUENCE HUNT -- %d solved keys (#%d..#%d)"
          % (len(KEYS), NS[0], NS[-1]))
    print("  Tested on positions INSIDE each interval, so the built-in doubling")
    print("  cannot masquerade as a discovery.")
    print("=" * 74)
    h1_fibonacci()
    h2_ratio()
    h3_polynomial()
    h4_modular()
    h5_benford()
    h6_autocorr()
    h7_spectrum()
    h8_hexrepeat()
    h9_predict_71()
    print("=" * 74)
    if all(VERDICTS):
        print("  VERDICT: no describable pattern. The solved keys are not a")
        print("  sequence -- they are independent random draws, and #71 cannot")
        print("  be predicted from them.")
    else:
        print("  VERDICT: something flagged above. VERIFY IT INDEPENDENTLY --")
        print("  with 9 tests on %d points, one flag is expected by chance."
              % len(KEYS))
    print("=" * 74)


if __name__ == "__main__":
    main()
