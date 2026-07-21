#!/usr/bin/env python3
"""
KEY STRUCTURE HUNT — the only class of attack that can beat sqrt(N).

If the 70 known puzzle keys share hidden structure (one master seed, a PRNG, an
LCG, correlated bits), then #71+ is derivable for free and no GPU is needed. This
runs a BATTERY of independent hypotheses on the known keys; each is checked
several ways so a single false positive can't fool us. If everything comes back
"random", that is itself a hard, data-backed result: there is no shortcut, and
effort must go to the pool / a snipe.

Local research on our own data. Run:  python analysis/key_structure_hunt.py
"""
import sys, os, math, zlib, lzma, statistics
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from analysis.rng_analysis import KNOWN_KEYS
from ecc.curve import N

KEYS = {n: KNOWN_KEYS[n] for n in sorted(KNOWN_KEYS)}
NS = sorted(KEYS)


def _free_bits(n):
    """The (n-1) 'random' bits of key n, below its fixed top bit."""
    return KEYS[n] - 2 ** (n - 1)


# ---- H1: master-number prefix (keys are one number revealed bit by bit) ----
def h1_prefix():
    deltas = [KEYS[n] - 2 * KEYS[n - 1] for n in NS if n - 1 in KEYS]
    ok = sum(1 for d in deltas if d in (0, 1))
    structure = (ok == len(deltas))          # prefix only if EVERY delta is a bit
    return (not structure), f"{ok}/{len(deltas)} consecutive deltas are a single bit"


# ---- H2: affine / LCG relation k_{n+1} = a*k_n + c (mod M) ----
def h2_lcg():
    # Try several moduli; solve a,c from two pairs, verify on a third+.
    hits = []
    for M in (2**64, 2**32, N, 2**70, 2**128):
        cons = [n for n in NS if n - 1 in KEYS]
        good = 0
        tried = 0
        for i in range(len(cons) - 2):
            n0, n1, n2 = cons[i], cons[i] + 1, cons[i] + 2
            if n1 not in KEYS or n2 not in KEYS:
                continue
            x0, x1, x2 = KEYS[n0] % M, KEYS[n1] % M, KEYS[n2] % M
            denom = (x1 - x0) % M
            try:
                a = ((x2 - x1) * pow(denom, -1, M)) % M
            except ValueError:
                continue
            c = (x1 - a * x0) % M
            tried += 1
            # verify on the NEXT element
            if n2 + 1 in KEYS:
                pred = (a * x2 + c) % M
                if pred == KEYS[n2 + 1] % M:
                    good += 1
        if tried and good > 0:
            hits.append((M, good, tried))
    verdict = len(hits) == 0
    return verdict, ("no affine law holds" if verdict
                     else f"POSSIBLE LCG hits: {hits}")


# ---- H3: free-bit stream is compressible (any structure at all) ----
def h3_compress():
    # Concatenate each key's free bits (MSB-first, exact width) into one blob.
    bits = []
    total_bits = 0
    for n in NS:
        w = n - 1
        if w <= 0:
            continue
        v = _free_bits(n)
        for j in range(w - 1, -1, -1):
            bits.append((v >> j) & 1)
        total_bits += w
    # pack to bytes
    ba = bytearray()
    for i in range(0, len(bits) - 7, 8):
        b = 0
        for k in range(8):
            b = (b << 1) | bits[i + k]
        ba.append(b)
    raw = bytes(ba)
    if not raw:
        return True, "no data"
    zl = len(zlib.compress(raw, 9))
    xz = len(lzma.compress(raw, preset=9))
    ratio = min(zl, xz) / len(raw)
    # true-random -> compressors can't beat ~1.0 (a little overhead either way)
    verdict = ratio >= 0.98
    return verdict, (f"{total_bits} free bits -> {len(raw)}B, best compressed "
                     f"{min(zl,xz)}B (ratio {ratio:.3f}; <0.98 = structure)")


# ---- H4: monobit + runs on the free-bit stream (NIST-lite, self-contained) ----
def h4_bitstats():
    ones = zeros = 0
    seq = []
    for n in NS:
        w = n - 1
        v = _free_bits(n)
        for j in range(w - 1, -1, -1):
            bit = (v >> j) & 1
            seq.append(bit)
            ones += bit
            zeros += 1 - bit
    total = ones + zeros
    p = ones / total
    # monobit z-score
    z = abs(ones - zeros) / math.sqrt(total)
    # runs
    runs = 1 + sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])
    exp_runs = 2 * total * p * (1 - p) + 1
    sd_runs = math.sqrt(2 * total * p * (1 - p) * (2 * p * (1 - p) * total - 1)
                        / max(1, total)) if 0 < p < 1 else 0
    z_runs = abs(runs - exp_runs) / sd_runs if sd_runs else 0
    verdict = z < 3 and z_runs < 3      # both within 3 sigma -> looks random
    return verdict, (f"monobit z={z:.2f} (p1={p:.4f}), runs z={z_runs:.2f} "
                     f"[both <3 = random]")


# ---- H5: shared low bits across keys (fixed-seed residue) ----
def h5_low_bits():
    # For m in a few widths, do many keys share the same low-m-bit residue?
    flags = []
    for m in (4, 8, 12, 16):
        res = [KEYS[n] & ((1 << m) - 1) for n in NS]
        # most common residue frequency vs expected uniform
        from collections import Counter
        c = Counter(res)
        top, cnt = c.most_common(1)[0]
        exp = len(res) / (1 << m)
        flags.append((m, cnt, round(exp, 2)))
    # structure would show one residue wildly over-represented
    verdict = all(cnt <= max(3, exp * 4) for _, cnt, exp in flags)
    return verdict, f"low-bit residue peaks {flags} (peak >> expected = structure)"


# ---- H6: pairwise GCD / small-factor structure ----
def h6_gcd():
    g = 0
    for n in NS:
        g = math.gcd(g, KEYS[n])
    # also count small prime factors shared
    small = [2, 3, 5, 7, 11, 13]
    shares = {p: sum(1 for n in NS if KEYS[n] % p == 0) for p in small}
    verdict = g == 1
    return verdict, f"gcd(all keys)={g}, small-prime divisibility {shares}"


def main():
    print("=" * 74)
    print("  KEY STRUCTURE HUNT — 70 known keys, multi-hypothesis")
    print("=" * 74)
    tests = [("H1 master-prefix (bit-by-bit)", h1_prefix),
             ("H2 affine/LCG relation",         h2_lcg),
             ("H3 free-bit compressibility",    h3_compress),
             ("H4 monobit + runs (NIST-lite)",  h4_bitstats),
             ("H5 shared low bits",             h5_low_bits),
             ("H6 gcd / small factors",         h6_gcd)]
    all_random = True
    for name, fn in tests:
        random_looking, detail = fn()
        tag = "random  " if random_looking else ">>> STRUCTURE <<<"
        all_random &= random_looking
        print(f"  [{tag}] {name}")
        print(f"             {detail}")
    print("=" * 74)
    if all_random:
        print("  VERDICT: every hypothesis says RANDOM. No derivable structure in")
        print("  the known keys -> #71 cannot be shortcut. (Hard, data-backed result.)")
    else:
        print("  VERDICT: a hypothesis flagged STRUCTURE — investigate above, it may")
        print("  make #71 derivable. VERIFY it independently before trusting it.")
    print("=" * 74)


if __name__ == '__main__':
    main()
