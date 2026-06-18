#!/usr/bin/env python3
"""
ECDSA Nonce Reuse & Bias Attack — Bitcoin Puzzle Creator
=========================================================

СТРАТЕГИЯ:
  Когда создатель пазла финансировал адреса — он подписал транзакции
  своим приватным ключом m0.  ECDSA-подпись содержит секретный нонс k.
  Если k повторился в любых двух подписях — ключ m0 восстанавливается
  мгновенно, одной формулой.

  Если m0 — мастер-ключ HD-кошелька (BIP32 без hardened деривации),
  то из m0 вычисляются ключи ВСЕХ 256 пазлов одной операцией.

МАТЕМАТИКА:
  ECDSA подпись: s = (z + r*privkey) / k  mod N
  При нонс-реюзе (k одинаков, r одинаков):
    k   = (z1 - z2) * modinv(s1 - s2)  mod N
    prv = (s1*k - z1) * modinv(r)       mod N

LLL-атака (нонс с нулевыми битами):
  Если нонс k имеет t нулевых старших бит (k < 2^(256-t)):
    → Задача HNP (Hidden Number Problem)
    → Решается редукцией решётки LLL/BKZ
    → Нужно ~ceil(256/t) подписей

Запуск:
  python analysis/nonce_attack.py                        # анализ ключа создателя
                                                            # (применимо к ЛЮБОМУ пазлу)
  python analysis/nonce_attack.py --txid <TX_ID>        # кастомная TX
  python analysis/nonce_attack.py --depth 3             # глубина трассировки
  python analysis/nonce_attack.py --lll                 # + LLL атака
"""

import sys
import os
import json
import time
import hashlib
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from analysis.tx_parser import (
    extract_sigs_from_tx, parse_der_sig, parse_scriptsig_p2pkh
)

# ──────────────────────────────────────────────────────────────────
# secp256k1
# ──────────────────────────────────────────────────────────────────

N  = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
P  = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
G  = (GX, GY)

def modinv(a: int, m: int = N) -> int:
    return pow(a, m - 2, m)

def pt_add(P1, P2):
    if P1 is None: return P2
    if P2 is None: return P1
    x1, y1 = P1; x2, y2 = P2
    if x1 == x2:
        if y1 != y2: return None
        lam = (3*x1*x1 * modinv(2*y1, P)) % P
    else:
        lam = ((y2-y1) * modinv(x2-x1, P)) % P
    x3 = (lam*lam - x1 - x2) % P
    y3 = (lam*(x1-x3) - y1) % P
    return (x3, y3)

def scalar_mul(k: int, pt) -> tuple:
    r = None; add = pt
    while k:
        if k & 1: r = pt_add(r, add)
        add = pt_add(add, add)
        k >>= 1
    return r

def pubkey_from_privkey(priv: int, compressed: bool = True) -> bytes:
    pt = scalar_mul(priv, G)
    x, y = pt
    if compressed:
        return bytes([0x02 + (y & 1)]) + x.to_bytes(32, 'big')
    return b'\x04' + x.to_bytes(32, 'big') + y.to_bytes(32, 'big')

def privkey_to_wif(priv: int) -> str:
    raw = b'\x80' + priv.to_bytes(32, 'big') + b'\x01'
    chk = hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
    n   = int.from_bytes(raw + chk, 'big')
    alpha = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    res = ''
    while n:
        n, r = divmod(n, 58)
        res = alpha[r] + res
    return res


# ──────────────────────────────────────────────────────────────────
# Blockchain API
# ──────────────────────────────────────────────────────────────────

def _get_json(url: str) -> dict | None:
    import urllib.request, urllib.error
    try:
        req = urllib.request.Request(url,
              headers={'User-Agent': 'btc-puzzle-nonce-analyzer/1.0'})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  [net] {url}: {e}")
        return None

def fetch_tx(txid: str) -> dict | None:
    return _get_json(f'https://blockstream.info/api/tx/{txid}')

def fetch_address_txs(address: str, limit: int = 50) -> list:
    data = _get_json(f'https://blockstream.info/api/address/{address}/txs')
    return data[:limit] if isinstance(data, list) else []

def fetch_address_info(address: str) -> dict | None:
    return _get_json(f'https://blockstream.info/api/address/{address}')


# ──────────────────────────────────────────────────────────────────
# Nonce Reuse: recover k and privkey
# ──────────────────────────────────────────────────────────────────

def recover_key_nonce_reuse(r: int,
                             s1: int, z1: int,
                             s2: int, z2: int) -> int | None:
    """
    Recover private key from ECDSA nonce reuse.

    Same r → same nonce k used in both signatures:
      k = (z1 - z2) / (s1 - s2)  mod N
      prv = (s1*k - z1) / r       mod N

    Returns private key or None if invalid.
    """
    try:
        ds = (s1 - s2) % N
        if ds == 0:
            return None
        k   = ((z1 - z2) % N * modinv(ds)) % N
        if k == 0:
            return None
        prv = ((s1 * k - z1) % N * modinv(r)) % N
        if prv == 0 or prv >= N:
            return None
        return prv
    except Exception:
        return None


def verify_signature(priv: int, r: int, s: int, z: int,
                     pubkey_hex: str | None) -> bool:
    """Verify the recovered private key matches the signature."""
    # Method 1: check against known pubkey
    if pubkey_hex:
        try:
            pk_bytes  = bytes.fromhex(pubkey_hex)
            compressed = (len(pk_bytes) == 33)
            derived    = pubkey_from_privkey(priv, compressed)
            if derived == pk_bytes:
                return True
        except Exception:
            pass

    # Method 2: verify signature math
    # s = (z + r*priv) / k  →  check (z + r*priv) ≡ s*k mod N
    # We recover k from priv and r:
    # k*G should have x ≡ r mod N
    try:
        # We can't easily reverse k from r without factoring.
        # Instead compute k = (z + r*priv) / s mod N
        # and check that (k*G).x ≡ r mod N
        k_check = ((z + r * priv) % N * modinv(s)) % N
        if k_check == 0:
            return False
        pt = scalar_mul(k_check, G)
        return pt is not None and pt[0] % N == r % N
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────
# LLL / HNP attack (biased nonces)
# ──────────────────────────────────────────────────────────────────

def lll_attack(signatures: list[dict], bias_bits: int = 8) -> int | None:
    """
    LLL-based attack for biased ECDSA nonces.
    Assumes top bias_bits of nonce k are 0 (i.e. k < 2^(256-bias_bits)).

    Requires at least ceil(256/bias_bits) + 2 signatures.
    Uses sympy for LLL reduction.

    Returns recovered private key or None.
    """
    try:
        from sympy import Matrix
    except ImportError:
        print("  [LLL] Need sympy: pip install sympy")
        return None

    # Filter sigs with valid z
    valid = [s for s in signatures if s.get('z') and s.get('r') and s.get('s')]
    needed = max(8, 256 // bias_bits + 4)

    if len(valid) < needed:
        print(f"  [LLL] Need {needed} sigs, have {len(valid)} — not enough")
        return None

    print(f"  [LLL] Building lattice ({len(valid[:needed])} sigs, bias={bias_bits} bits)...")

    sigs = valid[:needed]
    d    = len(sigs)
    B    = 2 ** bias_bits  # known bound on k's top bits being zero

    # Lattice construction (standard HNP approach)
    # Ref: "Lattice Attacks on Digital Signature Schemes" - Nguyen & Shparlinski
    # Build matrix M of size (d+2) x (d+2)
    # Row structure: for each sig (r_i, s_i, z_i):
    #   t_i = r_i * s_i^-1 mod N
    #   u_i = -z_i * s_i^-1 mod N
    #   k_i = t_i * privkey + u_i (mod N)

    rows = []
    ts = []; us = []
    for sig in sigs:
        si_inv = modinv(sig['s'])
        t = (sig['r'] * si_inv) % N
        u = (- sig['z'] * si_inv) % N
        ts.append(t)
        us.append(u)

    # Build lattice matrix (d+2 rows, d+2 cols)
    size = d + 2
    M = [[0] * size for _ in range(size)]

    for i in range(d):
        M[i][i] = N             # diagonal N
        M[d][i] = ts[i]         # t values in last row
        M[d+1][i] = us[i]       # u values

    M[d][d] = 1                 # identity for privkey row
    M[d+1][d+1] = N             # bound

    # Scale for bias
    scale = N // B
    for i in range(d):
        for j in range(size):
            M[i][j] *= scale

    print(f"  [LLL] Running LLL reduction ({size}x{size} matrix)...")
    try:
        mat    = Matrix(M)
        lll_m  = mat.lll()
    except Exception as e:
        print(f"  [LLL] LLL failed: {e}")
        return None

    # Search for short vector containing privkey
    for row_idx in range(lll_m.rows):
        row = [int(lll_m[row_idx, j]) for j in range(size)]
        # The privkey candidate is in column d
        priv_cand = row[d] % N
        if priv_cand == 0:
            continue

        # Verify against first signature
        sig0 = sigs[0]
        if sig0['z'] and verify_signature(priv_cand, sig0['r'], sig0['s'],
                                           sig0['z'], sig0.get('pubkey_hex')):
            print(f"  [LLL] *** FOUND privkey = {hex(priv_cand)}")
            return priv_cand

        # Try negative
        priv_neg = (-priv_cand) % N
        if verify_signature(priv_neg, sig0['r'], sig0['s'],
                            sig0['z'], sig0.get('pubkey_hex')):
            print(f"  [LLL] *** FOUND privkey (neg) = {hex(priv_neg)}")
            return priv_neg

    print("  [LLL] No key found in LLL output")
    return None


# ──────────────────────────────────────────────────────────────────
# Main analysis: trace creator's transactions
# ──────────────────────────────────────────────────────────────────

# Known puzzle funding transactions (add more if discovered).
# This TX funded ALL 160 puzzle addresses at once — a recovered creator key
# is NOT puzzle-specific, it potentially unlocks every unsolved puzzle.
PUZZLE_FUNDING_TXS = [
    '08389f34c98c606322740c0be6a7125d9860bb8d5cb182c02f98461e5fa6cd15',
    # Add any other funding transactions here
]


def find_creator_addresses(funding_txid: str) -> list[str]:
    """
    Fetch the funding TX and extract all input addresses.
    These are the creator's wallet addresses.
    """
    print(f"\n[CreatorTrace] Fetching funding TX: {funding_txid}")
    tx = fetch_tx(funding_txid)
    if not tx:
        return []

    addrs = []
    for inp in tx.get('vin', []):
        a = inp.get('prevout', {}).get('scriptpubkey_address', '')
        if a and a not in addrs:
            addrs.append(a)
    print(f"[CreatorTrace] Creator addresses: {addrs}")
    return addrs


def collect_all_signatures(addresses: list[str],
                            depth: int = 2,
                            max_tx: int = 200) -> list[dict]:
    """
    Collect ALL ECDSA signatures from all transactions of creator's addresses.
    depth: how many hops to follow (input address → its inputs, etc.)
    """
    all_sigs = []
    visited_txids = set()
    queue = list(addresses)
    visited_addrs = set(addresses)

    print(f"\n[SigCollect] Collecting signatures from {len(addresses)} address(es)...")
    print(f"[SigCollect] depth={depth}  max_tx={max_tx}")

    for hop in range(depth):
        if not queue:
            break
        next_hop_addrs = []
        print(f"\n[SigCollect] Hop {hop+1}: {len(queue)} address(es)...")

        for addr in queue:
            txs = fetch_address_txs(addr, limit=max_tx)
            print(f"  {addr}: {len(txs)} transactions")

            for tx in txs:
                txid = tx.get('txid', '')
                if txid in visited_txids:
                    continue
                visited_txids.add(txid)

                sigs = extract_sigs_from_tx(tx)
                all_sigs.extend(sigs)

                # Collect next-hop addresses from inputs
                if hop < depth - 1:
                    for inp in tx.get('vin', []):
                        a = inp.get('prevout', {}).get('scriptpubkey_address', '')
                        if a and a not in visited_addrs:
                            visited_addrs.add(a)
                            next_hop_addrs.append(a)

            time.sleep(0.3)  # rate limit

        queue = next_hop_addrs[:50]  # cap next hop

    print(f"\n[SigCollect] Total: {len(all_sigs)} signatures from "
          f"{len(visited_txids)} transactions")
    return all_sigs


def check_nonce_reuse(signatures: list[dict]) -> list[dict]:
    """
    Check for ECDSA nonce reuse: same r value across different signatures.
    Returns list of collision groups.
    """
    print(f"\n[NonceReuse] Checking {len(signatures)} signatures for r-value collisions...")

    r_map: dict[int, list] = {}
    for sig in signatures:
        r = sig['r']
        if r not in r_map:
            r_map[r] = []
        r_map[r].append(sig)

    collisions = [grp for grp in r_map.values() if len(grp) >= 2]
    print(f"[NonceReuse] Found {len(collisions)} r-value collision group(s)")

    recovered_keys = []
    for grp in collisions:
        print(f"\n  r = {hex(grp[0]['r'])}")
        print(f"  Signatures using same r: {len(grp)}")
        for sig in grp[:4]:
            print(f"    txid={sig['txid'][:16]}...  "
                  f"input={sig['input_idx']}  "
                  f"z={'0x'+hex(sig['z'])[2:16]+'...' if sig['z'] else 'None'}")

        # Try to recover key from all pairs
        for i in range(len(grp)):
            for j in range(i+1, len(grp)):
                s1, z1 = grp[i].get('s'), grp[i].get('z')
                s2, z2 = grp[j].get('s'), grp[j].get('z')
                if not (s1 and z1 and s2 and z2):
                    continue
                if s1 == s2:
                    continue

                priv = recover_key_nonce_reuse(grp[i]['r'], s1, z1, s2, z2)
                if priv is None:
                    continue

                # Verify
                pubkey_hex = grp[i].get('pubkey_hex') or grp[j].get('pubkey_hex')
                ok = verify_signature(priv, grp[i]['r'], s1, z1, pubkey_hex)
                if ok:
                    print(f"\n  *** NONCE REUSE — PRIVATE KEY RECOVERED! ***")
                    print(f"  privkey (hex) = {hex(priv)}")
                    print(f"  privkey (dec) = {priv}")
                    print(f"  WIF           = {privkey_to_wif(priv)}")
                    recovered_keys.append({
                        'privkey': priv,
                        'wif':     privkey_to_wif(priv),
                        'source':  f"{grp[i]['txid']}:{grp[i]['input_idx']} + "
                                   f"{grp[j]['txid']}:{grp[j]['input_idx']}",
                    })
                    break
            else:
                continue
            break

    if not collisions:
        print("[NonceReuse] No nonce reuse found (this is expected for a careful creator)")

    return recovered_keys


def analyze_nonce_bias(signatures: list[dict]) -> dict:
    """
    Statistical analysis of nonce bias.
    Checks distribution of k's bits (via r distribution).
    r = (k*G).x  so r's high bits correlate with k's high bits.
    """
    print(f"\n[NonceBias] Analyzing {len(signatures)} signature r-values...")

    rs = [sig['r'] for sig in signatures if sig.get('r')]
    if not rs:
        print("  No r values to analyze")
        return {}

    # Check ratio r/N — should be uniform in [0,1] for unbiased k
    ratios = [r / N for r in rs]
    mean_r = sum(ratios) / len(ratios)
    std_r  = (sum((x - mean_r)**2 for x in ratios) / len(ratios)) ** 0.5

    print(f"  r/N stats:  mean={mean_r:.6f}  std={std_r:.6f}")
    print(f"  Expected:   mean~0.5  std~0.289 (for unbiased nonces)")

    # Check high bits of r
    high_bit_freq = sum(1 for r in rs if r > N // 2) / len(rs)
    print(f"  r > N/2:    {high_bit_freq:.3f}  (expected 0.5)")

    # Check for low-bit clustering (bias in lowest bits)
    low4 = [r & 0xF for r in rs]
    from collections import Counter
    c = Counter(low4)
    max_freq = max(c.values()) / len(rs)
    print(f"  Low 4 bits: max freq = {max_freq:.3f}  "
          f"(expected ~0.0625 = 1/16 for uniform)")

    bias_detected = abs(mean_r - 0.5) > 0.05 or std_r < 0.25 or max_freq > 0.15
    if bias_detected:
        print(f"\n  *** BIAS DETECTED! r distribution is non-uniform.")
        print(f"  LLL attack may work — run with --lll flag.")
    else:
        print(f"\n  r distribution looks uniform — no obvious nonce bias")

    return {
        'mean_ratio': mean_r,
        'std_ratio':  std_r,
        'high_bit_freq': high_bit_freq,
        'max_low4_freq': max_freq,
        'bias_detected': bias_detected,
        'n_sigs':     len(rs),
    }


def save_results(sigs: list[dict], path: str = 'nonce_sigs.json'):
    """Save collected signatures to JSON for later analysis."""
    data = []
    for s in sigs:
        data.append({
            'txid':       s['txid'],
            'input_idx':  s['input_idx'],
            'r':          hex(s['r']),
            's':          hex(s['s']),
            'z':          hex(s['z']) if s['z'] else None,
            'pubkey_hex': s.get('pubkey_hex'),
            'type':       s.get('type'),
        })
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"\n[Save] {len(data)} signatures -> {path}")


def load_results(path: str = 'nonce_sigs.json') -> list[dict]:
    """Load previously saved signatures."""
    import os
    if not os.path.exists(path):
        return []
    with open(path) as f:
        raw = json.load(f)
    data = []
    for s in raw:
        data.append({
            'txid':       s['txid'],
            'input_idx':  s['input_idx'],
            'r':          int(s['r'], 16),
            's':          int(s['s'], 16),
            'z':          int(s['z'], 16) if s['z'] else None,
            'pubkey_hex': s.get('pubkey_hex'),
            'type':       s.get('type'),
        })
    return data


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='ECDSA Nonce Attack — Bitcoin Puzzle Creator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    parser.add_argument('--txid',   default=PUZZLE_FUNDING_TXS[0],
                        help=f'Funding TX (default: {PUZZLE_FUNDING_TXS[0][:16]}...)')
    parser.add_argument('--depth',  type=int, default=2,
                        help='Address tracing depth (default: 2)')
    parser.add_argument('--max-tx', type=int, default=100,
                        help='Max transactions per address (default: 100)')
    parser.add_argument('--lll',    action='store_true',
                        help='Run LLL nonce-bias attack (requires sympy)')
    parser.add_argument('--lll-bits', type=int, default=8,
                        help='Assumed nonce bias bits for LLL (default: 8)')
    parser.add_argument('--load',   default='',
                        help='Load signatures from JSON (skip network fetch)')
    parser.add_argument('--save',   default='nonce_sigs.json',
                        help='Save collected signatures (default: nonce_sigs.json)')
    parser.add_argument('--quick',  action='store_true',
                        help='Quick: only check the funding TX itself')
    args = parser.parse_args()

    print("\n" + "="*60)
    print("  ECDSA NONCE ATTACK — Bitcoin Puzzle Creator Analysis")
    print("="*60)

    # ── Load or collect signatures ────────────────────────────────
    if args.load:
        sigs = load_results(args.load)
        print(f"[Load] Loaded {len(sigs)} signatures from {args.load}")
    elif args.quick:
        print(f"\n[Quick] Analyzing only funding TX: {args.txid}")
        tx = fetch_tx(args.txid)
        if tx:
            sigs = extract_sigs_from_tx(tx)
            print(f"[Quick] Extracted {len(sigs)} signatures")
        else:
            sigs = []
    else:
        creator_addrs = find_creator_addresses(args.txid)
        if not creator_addrs:
            print("[!] Could not find creator addresses. Try --quick or check TX ID.")
            sys.exit(1)
        sigs = collect_all_signatures(creator_addrs,
                                       depth=args.depth,
                                       max_tx=args.max_tx)
        save_results(sigs, args.save)

    if not sigs:
        print("[!] No signatures collected. Nothing to analyze.")
        sys.exit(1)

    z_count = sum(1 for s in sigs if s.get('z'))
    print(f"\n[Summary] Signatures: {len(sigs)}  "
          f"(with z: {z_count}, without z: {len(sigs)-z_count})")

    # ── Nonce reuse check ─────────────────────────────────────────
    recovered = check_nonce_reuse(sigs)

    if recovered:
        print(f"\n{'!'*60}")
        print(f"  CREATOR KEY(S) RECOVERED via nonce reuse!")
        for r in recovered:
            print(f"  privkey = {hex(r['privkey'])}")
            print(f"  WIF     = {r['wif']}")
            print(f"  Source: {r['source']}")
        print(f"{'!'*60}")
        print(f"\nNEXT: Check if this is a BIP32 master key:")
        print(f"  python analysis/bip32_analysis.py --master-key {hex(recovered[0]['privkey'])}")
        # Save to file
        with open('CREATOR_KEY_FOUND.txt', 'w') as f:
            for r in recovered:
                f.write(f"privkey: {hex(r['privkey'])}\nWIF: {r['wif']}\n")
        print(f"\nSaved to CREATOR_KEY_FOUND.txt")
    else:
        # ── Nonce bias analysis ───────────────────────────────────
        bias_info = analyze_nonce_bias(sigs)

        # ── LLL attack if bias detected or forced ─────────────────
        if args.lll or bias_info.get('bias_detected'):
            priv = lll_attack(sigs, bias_bits=args.lll_bits)
            if priv:
                print(f"\n{'!'*60}")
                print(f"  LLL ATTACK SUCCEEDED!")
                print(f"  privkey = {hex(priv)}")
                print(f"  WIF     = {privkey_to_wif(priv)}")
                print(f"{'!'*60}")
            else:
                print("\n  LLL attack did not find the key.")
                print("  Try with more signatures or different --lll-bits value.")
        else:
            print(f"\n[Result] No vulnerabilities found in {len(sigs)} signatures.")
            print(f"  Creator used secure nonce generation.")
            print(f"  Next best options:")
            print(f"    1. Collect more signatures (increase --depth)")
            print(f"    2. Try LLL with --lll --lll-bits 4")
            print(f"    3. Check BIP32 derivation: python analysis/bip32_analysis.py")


if __name__ == '__main__':
    main()
