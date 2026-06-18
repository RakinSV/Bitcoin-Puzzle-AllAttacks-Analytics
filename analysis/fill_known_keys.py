"""
Fill KNOWN_KEYS from collected pubkeys via BSGS.

For each puzzle n with known pubkey K_n (from puzzle_pubkeys.json),
solve ECDLP: find k such that k*G = K_n, k in [2^(n-1), 2^n-1].

BSGS with Jacobian coordinates is fast for n <= 50 (~30M steps).
For n > 50 we skip (would need GPU Kangaroo).

Result: updates KNOWN_KEYS in rng_analysis.py and bip32_analysis.py.
"""

import json
import sys
import os
import time

# secp256k1
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
G  = (GX, GY)
INF = (0, 0)


def _inv(a): return pow(a, P-2, P)

def ec_add(P1, P2):
    if P1 == INF: return P2
    if P2 == INF: return P1
    x1,y1=P1; x2,y2=P2
    if x1==x2:
        if y1!=y2: return INF
        lam=(3*x1*x1*_inv(2*y1))%P
    else:
        lam=((y2-y1)*_inv(x2-x1))%P
    x3=(lam*lam-x1-x2)%P
    y3=(lam*(x1-x3)-y1)%P
    return x3,y3

def ec_neg(pt):
    if pt==INF: return INF
    x,y=pt; return x,(-y)%P

def scalar_mul(k, pt):
    if k==0: return INF
    if k<0: return scalar_mul(-k, ec_neg(pt))
    r=INF; a=pt
    while k:
        if k&1: r=ec_add(r,a)
        a=ec_add(a,a); k>>=1
    return r

# ── Jacobian coordinates for fast batch baby-steps ─────────────────
# Point (X:Y:Z) represents affine (X/Z^2, Y/Z^3)
# Infinity: Z == 0
# Avoids per-step modular inverse; requires only 1 batch inverse at end.

JINF = (0, 1, 0)  # Jacobian infinity

def j_double(jpt):
    X, Y, Z = jpt
    if Z == 0: return JINF
    # secp256k1 a=0
    Y2 = Y*Y % P
    S  = 4*X*Y2 % P
    M  = 3*X*X % P
    X3 = (M*M - 2*S) % P
    Y3 = (M*(S - X3) - 8*Y2*Y2) % P
    Z3 = 2*Y*Z % P
    return (X3, Y3, Z3)

def j_mixed_add(jpt, apt):
    """Add Jacobian jpt + affine apt."""
    X1, Y1, Z1 = jpt
    X2, Y2     = apt
    if Z1 == 0: return (X2, Y2, 1)
    Z1Z1 = Z1*Z1 % P
    U2   = X2*Z1Z1 % P
    S2   = Y2*Z1*Z1Z1 % P
    H    = (U2 - X1) % P
    R    = (S2 - Y1) % P
    if H == 0:
        if R == 0: return j_double(jpt)
        return JINF
    H2 = H*H % P
    H3 = H*H2 % P
    X3 = (R*R - H3 - 2*X1*H2) % P
    Y3 = (R*(X1*H2 - X3) - Y1*H3) % P
    Z3 = H*Z1 % P
    return (X3, Y3, Z3)

def j_neg(jpt):
    X, Y, Z = jpt
    return (X, (-Y) % P, Z)

def batch_j_to_affine_x(jpoints):
    """
    Convert list of Jacobian points to list of affine x-coordinates.
    Uses Montgomery batch inversion: 3n muls + 1 pow vs n pows.
    Returns list of x values; INF points → None.
    """
    zs = [p[2] for p in jpoints]
    n  = len(zs)

    # Separate out non-infinity indices
    nz_idx = [i for i, z in enumerate(zs) if z != 0]
    if not nz_idx:
        return [None]*n

    nz_zs = [zs[i] for i in nz_idx]
    m = len(nz_zs)

    # Forward: cumulative products of z^2 (we want 1/z^2 for x)
    # Actually we need 1/Z^2.  Batch invert Z values, then square each 1/Z.
    prods = [0]*m
    prods[0] = nz_zs[0]
    for i in range(1, m):
        prods[i] = prods[i-1] * nz_zs[i] % P

    inv_all = pow(prods[-1], P-2, P)

    inv_nz = [0]*m
    for i in range(m-1, 0, -1):
        inv_nz[i] = inv_all * prods[i-1] % P
        inv_all   = inv_all * nz_zs[i]   % P
    inv_nz[0] = inv_all

    # Build result
    xs = [None]*n
    for k, i in enumerate(nz_idx):
        X, _, Z = jpoints[i]
        inv_z  = inv_nz[k]
        inv_z2 = inv_z * inv_z % P
        xs[i]  = X * inv_z2 % P
    return xs

def pubkey_from_hex(pk_hex):
    try:
        b=bytes.fromhex(pk_hex)
        if len(b)==65 and b[0]==4:
            return int.from_bytes(b[1:33],'big'), int.from_bytes(b[33:],'big')
        elif len(b)==33 and b[0] in (2,3):
            x=int.from_bytes(b[1:],'big')
            y_sq=(pow(x,3,P)+7)%P
            y=pow(y_sq,(P+1)//4,P)
            if (y%2)!=(b[0]&1): y=(-y)%P
            return x,y
    except: pass
    return None


def bsgs(target_pt, k_start, k_end, verbose=True, giant_batch=2048):
    """
    Baby-step Giant-step using Jacobian coordinates for speed.

    Baby steps use batch Jacobian→affine conversion (1 batch inversion
    instead of t individual pow calls).  Giant steps use Jacobian
    arithmetic with batched affine conversion every `giant_batch` steps.

    Memory: O(sqrt(range))
    Time:   O(sqrt(range))   — ~5-10x faster than pure-affine version
    Max range: ~2^50 with t <= 30M
    """
    rng = k_end - k_start + 1
    if rng <= 0:
        return None

    # Special case: range of 1
    if rng == 1:
        if scalar_mul(k_start, G) == target_pt:
            return k_start
        return None

    t = int(rng**0.5) + 2  # step size; +2 for boundary safety

    if t > 30_000_000:
        if verbose:
            print(f"  Range too large for BSGS (t={t:,} > 30M). Skip.")
        return None

    if verbose:
        print(f"  BSGS: range={rng:,}, t={t:,} ...", end='', flush=True)

    # ── Shift target ─────────────────────────────────────────────────
    # Solve for k' in [0, rng-1]: (k'+k_start)*G = target_pt
    # → k'*G = target_pt - k_start*G
    shifted = ec_add(target_pt, ec_neg(scalar_mul(k_start, G)))
    if shifted == INF:           # k_start is the answer
        if verbose: print()
        return k_start

    # ── Baby steps via Jacobian (no per-step inversion) ─────────────
    # Accumulate t+1 points in Jacobian, then batch-convert to affine x.
    # Build in chunks to bound peak memory (each chunk is a list of tuples).
    CHUNK = 131072   # 128k points per chunk ≈ affordable
    baby  = {}       # affine x → smallest j

    jcur = JINF      # j=0 → point at INF (x not stored)
    baby['INF'] = 0

    j_base = 0
    while j_base <= t:
        chunk_size = min(CHUNK, t + 1 - j_base)
        # Collect chunk_size points starting at j_base+1 (j_base is already jcur)
        jpts = []
        for _ in range(chunk_size):
            jcur = j_mixed_add(jcur, G) if jcur != JINF else (GX, GY, 1)
            jpts.append(jcur)

        # Batch convert x-coordinates
        xs = batch_j_to_affine_x(jpts)
        for local_j, x in enumerate(xs):
            j = j_base + 1 + local_j
            if x is not None and x not in baby:
                baby[x] = j
        j_base += chunk_size

    if verbose:
        print(f" baby={len(baby):,}", end='', flush=True)

    # ── Giant steps ───────────────────────────────────────────────────
    # Compute tG once (affine), then subtract it in Jacobian each step.
    tG_aff  = scalar_mul(t, G)
    neg_tG  = ec_neg(tG_aff)

    # shifted in Jacobian form (start of giant walk)
    # We walk: curr_j = shifted - i*tG, checking x against baby dict.
    # Use batched Jacobian→affine every `giant_batch` steps.
    n_giant = (rng + t - 1) // t + 2

    # Convert shifted to Jacobian
    curr_j  = (shifted[0], shifted[1], 1)
    found   = None

    i = 0
    while i < n_giant and found is None:
        batch_end = min(i + giant_batch, n_giant)
        batch_n   = batch_end - i

        # Accumulate batch_n Jacobian points
        jbatch = []
        tmp_j  = curr_j
        for _ in range(batch_n):
            jbatch.append(tmp_j)
            tmp_j = j_mixed_add(tmp_j, neg_tG)

        # Batch-convert x-coords
        xs = batch_j_to_affine_x(jbatch)

        for bi, x in enumerate(xs):
            gi = i + bi
            if x is None:
                # giant step hit INF → k' = gi*t
                k_prime = gi * t
                if 0 <= k_prime < rng:
                    k = k_start + k_prime
                    if scalar_mul(k, G) == target_pt:
                        found = k; break
            elif x in baby:
                j = baby[x]
                for k_prime in (gi*t + j, gi*t - j):
                    if 0 <= k_prime < rng:
                        k = k_start + k_prime
                        if scalar_mul(k, G) == target_pt:
                            found = k; break
                if found is not None:
                    break

        # Advance curr_j by giant_batch steps
        curr_j = tmp_j
        i = batch_end

    if verbose:
        print()
    return found


def solve_all_known(pubkeys_file='puzzle_pubkeys.json',
                    max_bits=50, max_gpu_bits=60) -> dict:
    """
    Solve DLP for each collected pubkey in its known range.

    Returns: {puzzle_n: private_key_int}
    """
    if not os.path.exists(pubkeys_file):
        print(f"[!] {pubkeys_file} not found. Run pubkey_pattern.py --collect first.")
        return {}

    with open(pubkeys_file) as f:
        pubkeys = json.load(f)

    print(f"\n[FillKeys] Solving DLP for {len(pubkeys)} pubkeys (up to {max_bits}-bit)...")
    print(f"  This may take a few minutes for larger puzzles.\n")

    known_keys = {}

    for rank_str in sorted(pubkeys.keys(), key=int):
        rank = int(rank_str)
        entry = pubkeys[rank_str]
        pk_hex = entry['pubkey']

        # Puzzle n = rank: range [2^(n-1), 2^n-1]
        if rank == 1:
            k_start, k_end = 1, 1
        else:
            k_start = 1 << (rank - 1)
            k_end   = (1 << rank) - 1

        bits = rank
        if bits > max_bits:
            print(f"  Puzzle #{rank:2d}: skipping ({bits}-bit range, need GPU)")
            continue

        K = pubkey_from_hex(pk_hex)
        if K is None:
            print(f"  Puzzle #{rank:2d}: invalid pubkey, skip")
            continue

        t0 = time.time()
        print(f"  Puzzle #{rank:2d}: range [2^{rank-1}, 2^{rank}-1] ... ", end='', flush=True)
        k = bsgs(K, k_start, k_end, verbose=False)
        elapsed = time.time() - t0

        if k is not None:
            known_keys[rank] = k
            print(f"k = {hex(k)}  ({elapsed:.2f}s)")
        else:
            print(f"NOT FOUND in {elapsed:.2f}s (possible range mismatch)")

    return known_keys


def update_rng_analysis(known_keys: dict, rng_file: str) -> None:
    """Update KNOWN_KEYS in rng_analysis.py with newly found keys."""
    if not os.path.exists(rng_file):
        print(f"[!] {rng_file} not found")
        return

    with open(rng_file, encoding='utf-8') as f:
        content = f.read()

    # Build replacement KNOWN_KEYS dict
    # Find the existing dict and replace
    import re
    old_dict_pattern = r'KNOWN_KEYS\s*=\s*\{[^}]+\}'

    lines = []
    lines.append("KNOWN_KEYS = {")
    for n, k in sorted(known_keys.items()):
        lines.append(f"    {n:2d}: {hex(k)},  # {k}")
    lines.append("}")
    new_dict = "\n".join(lines)

    new_content = re.sub(old_dict_pattern, new_dict, content, flags=re.DOTALL)
    if new_content != content:
        with open(rng_file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"[UpdatedRNG] Wrote {len(known_keys)} keys to {rng_file}")
    else:
        print(f"[!] Could not find KNOWN_KEYS pattern in {rng_file}")
        print(f"    New KNOWN_KEYS dict:\n{new_dict}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Fill KNOWN_KEYS from pubkeys via BSGS')
    parser.add_argument('--pubkeys', default='puzzle_pubkeys.json')
    parser.add_argument('--max-bits', type=int, default=50,
                        help='Max puzzle size in bits (default 50, uses Jacobian BSGS)')
    parser.add_argument('--update-rng', action='store_true',
                        help='Update rng_analysis.py with found keys')
    parser.add_argument('--rng-file', default='analysis/rng_analysis.py')
    parser.add_argument('--bip32-file', default='analysis/bip32_analysis.py',
                        help='Also update bip32_analysis.py KNOWN_KEYS')
    args = parser.parse_args()

    known = solve_all_known(args.pubkeys, max_bits=args.max_bits)

    print(f"\n[Summary] Found {len(known)} keys:")
    for n, k in sorted(known.items()):
        print(f"  Puzzle #{n:2d}: k = {hex(k)}")

    if args.update_rng and known:
        update_rng_analysis(known, args.rng_file)
        # Also update bip32_analysis.py with the same keys
        if os.path.exists(args.bip32_file):
            update_rng_analysis(known, args.bip32_file)
            print(f"[UpdatedBIP32] Wrote {len(known)} keys to {args.bip32_file}")

    # Save to JSON
    with open('known_keys.json', 'w') as f:
        json.dump({str(n): hex(k) for n,k in known.items()}, f, indent=2)
    print(f"\n[Save] known_keys.json written")


if __name__ == '__main__':
    main()
