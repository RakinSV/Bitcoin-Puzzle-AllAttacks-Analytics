#!/usr/bin/env python3
"""
LOTTERY MATH — can higher math improve brute-force odds?

The GPU lottery sweeps keys in [2^(n-1), 2^n). If the key is UNIFORM in that
range with no side information, then a fundamental theorem says NO search order
beats any other: P(hit in T tries) = T / 2^(n-1) for every strategy. The only
way math helps is if the known keys are NON-uniform (then we search the dense
region first) or if a target other than the smallest unsolved has better
expected value.

This tests both, rigorously, on the 70 known keys:
  A. Uniformity of each key's position within its own range
       - Kolmogorov-Smirnov vs Uniform(0,1)
       - chi-square on 10 bins
       - per-bit-position bias (is bit j fair across keys?)
  B. Expected-value target selection: argmax_n reward(n) * P(hit | budget)

Local research. Run:  python analysis/lottery_math.py
"""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from analysis.rng_analysis import KNOWN_KEYS
from utils.puzzle_registry import estimated_reward_btc

NS = sorted(KNOWN_KEYS)


def positions():
    """Each key's fractional position in [2^(n-1), 2^n)  ->  in [0,1)."""
    out = []
    for n in NS:
        lo, hi = 2 ** (n - 1), 2 ** n
        out.append((KNOWN_KEYS[n] - lo) / (hi - lo))
    return out


def ks_uniform(xs):
    """One-sample KS statistic vs Uniform(0,1) + a rough critical value."""
    xs = sorted(xs)
    m = len(xs)
    d = 0.0
    for i, x in enumerate(xs):
        d = max(d, abs((i + 1) / m - x), abs(x - i / m))
    crit = 1.36 / math.sqrt(m)          # ~5% two-sided critical value
    return d, crit


def chi2_bins(xs, bins=10):
    obs = [0] * bins
    for x in xs:
        obs[min(bins - 1, int(x * bins))] += 1
    exp = len(xs) / bins
    chi2 = sum((o - exp) ** 2 / exp for o in obs)
    # df=9 -> 5% critical ~16.92
    return chi2, 16.92, obs


def bit_bias():
    """For each within-range bit position, is it 0/1 with p~0.5 across keys?"""
    worst_z = 0.0
    worst_pos = None
    # use the lower 40 bits (present in the higher-# keys)
    for j in range(0, 40):
        ones = tot = 0
        for n in NS:
            if n - 1 > j:                # bit j is a free bit for this key
                ones += (KNOWN_KEYS[n] >> j) & 1
                tot += 1
        if tot >= 20:
            p = ones / tot
            z = abs(ones - tot / 2) / math.sqrt(tot / 4)
            if z > worst_z:
                worst_z, worst_pos = z, (j, ones, tot)
    return worst_z, worst_pos


def ev_target(budget_keys=1.3e16):
    """Expected reward per target given a fixed key budget (1 GPU-year ~1.3e16)."""
    rows = []
    for n in range(71, 90):
        space = 2 ** (n - 1)
        p_hit = min(1.0, budget_keys / space)
        ev = p_hit * estimated_reward_btc(n)
        rows.append((n, p_hit, estimated_reward_btc(n), ev))
    return rows


def main():
    print("=" * 72)
    print("  LOTTERY MATH — is there any edge over uniform brute force?")
    print("=" * 72)
    xs = positions()

    d, crit = ks_uniform(xs)
    print(f"\n  A1 Kolmogorov-Smirnov vs Uniform(0,1):")
    print(f"     D={d:.4f}  critical(5%)={crit:.4f}  -> "
          f"{'UNIFORM (no edge)' if d < crit else 'NON-UNIFORM (!!) edge possible'}")

    chi2, ccrit, obs = chi2_bins(xs)
    print(f"\n  A2 chi-square, 10 bins:")
    print(f"     chi2={chi2:.2f}  critical(5%,df9)={ccrit}  bins={obs}")
    print(f"     -> {'UNIFORM' if chi2 < ccrit else 'NON-UNIFORM (!!)'}")

    z, pos = bit_bias()
    print(f"\n  A3 per-bit-position bias (worst of 40 positions):")
    print(f"     max|z|={z:.2f} at {pos}  -> "
          f"{'all fair (no edge)' if z < 3 else 'BIASED BIT (!!)'}")

    print(f"\n  B  Expected-value target (1 GPU-year budget ~1.3e16 keys):")
    print(f"     {'#':>3} {'P(hit)':>12} {'reward':>8} {'E[BTC]':>12}")
    best = None
    for n, p, r, ev in ev_target():
        mark = ''
        if best is None or ev > best[3]:
            best = (n, p, r, ev)
        print(f"     {n:>3} {p:>12.2e} {r:>8.2f} {ev:>12.2e}")
    print(f"     -> best expected value: puzzle #{best[0]} "
          f"(E[{best[3]:.2e} BTC]/GPU-year)")

    print("\n" + "=" * 72)
    edge = (d >= crit) or (chi2 >= ccrit) or (z >= 3)
    if edge:
        print("  A statistical edge was found — search the dense region first.")
    else:
        print("  VERDICT: positions are uniform + no bit bias. Theorem applies:")
        print("  no search order beats uniform. The ONLY levers are (1) target the")
        print("  smallest unsolved (#71 = best E[value]) and (2) throw more compute")
        print("  with DISJOINT ranges so a group never wastes overlap.")
    print("=" * 72)


if __name__ == '__main__':
    main()
