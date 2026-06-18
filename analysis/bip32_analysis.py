#!/usr/bin/env python3
"""
BIP32 HD Wallet Derivation Analysis
=====================================
Проверяет: если создатель пазла использовал HD-кошелёк (BIP32) без
hardened деривации — то зная ОДИН ключ + xpub родителя можно вычислить ВСЕ.

Два сценария:
  A) У нас есть master privkey (из nonce_attack.py) →
     Деривируем m/0, m/1, ..., m/255 → проверяем адреса пазлов.

  B) У нас нет master key, но знаем решённые пазлы (#1-65) →
     Ищем паттерн деривации: может ключи = m/n или m/0/n или другая схема.

  C) Тест "прямой кейспейс": ключи = sha256(b"puzzle" + N) или похожее.

Запуск:
  python analysis/bip32_analysis.py                          # тест B
  python analysis/bip32_analysis.py --master-key 0x...      # тест A
  python analysis/bip32_analysis.py --test-all              # все тесты
"""

import sys
import os
import hmac
import hashlib
import struct
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# secp256k1
N  = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
P  = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
G  = (GX, GY)


# ──────────────────────────────────────────────────────────────────
# Minimal EC operations
# ──────────────────────────────────────────────────────────────────

def modinv(a, m=P):
    return pow(a, m - 2, m)

def pt_add(P1, P2):
    if P1 is None: return P2
    if P2 is None: return P1
    x1, y1 = P1; x2, y2 = P2
    if x1 == x2:
        if y1 != y2: return None
        lam = (3*x1*x1 * modinv(2*y1)) % P
    else:
        lam = ((y2-y1) * modinv(x2-x1)) % P
    x3 = (lam*lam - x1 - x2) % P
    y3 = (lam*(x1-x3) - y1) % P
    return (x3, y3)

def scalar_mul(k, pt=G):
    r = None; add = pt
    while k:
        if k & 1: r = pt_add(r, add)
        add = pt_add(add, add)
        k >>= 1
    return r

def pubkey_compressed(priv: int) -> bytes:
    pt = scalar_mul(priv)
    x, y = pt
    return bytes([0x02 + (y & 1)]) + x.to_bytes(32, 'big')

def pubkey_hash160(pub: bytes) -> bytes:
    sha = hashlib.sha256(pub).digest()
    return hashlib.new('ripemd160', sha).digest()

def hash160_to_address(h160: bytes) -> str:
    payload = b'\x00' + h160
    chk = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    n = int.from_bytes(payload + chk, 'big')
    alpha = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    res = ''
    while n:
        n, r = divmod(n, 58)
        res = alpha[r] + res
    for b in (payload + chk):
        if b == 0: res = '1' + res
        else: break
    return res

def privkey_to_address(priv: int) -> str:
    return hash160_to_address(pubkey_hash160(pubkey_compressed(priv)))


# ──────────────────────────────────────────────────────────────────
# BIP32 key derivation
# ──────────────────────────────────────────────────────────────────

def bip32_ckd_priv(parent_key: int, parent_chain: bytes,
                    index: int) -> tuple[int, bytes]:
    """
    BIP32 child key derivation (private).

    Non-hardened (i < 2^31):
        I = HMAC-SHA512(parent_chain, serP(parent_pub) + ser32(i))
    Hardened (i >= 2^31):
        I = HMAC-SHA512(parent_chain, 0x00 + ser256(parent_key) + ser32(i))

    Returns (child_key, child_chain).
    """
    if index >= 0x80000000:
        # Hardened
        data = b'\x00' + parent_key.to_bytes(32, 'big') + struct.pack('>I', index)
    else:
        # Non-hardened: need parent pubkey
        pub = pubkey_compressed(parent_key)
        data = pub + struct.pack('>I', index)

    I = hmac.new(parent_chain, data, hashlib.sha512).digest()
    IL = int.from_bytes(I[:32], 'big')
    IR = I[32:]

    if IL >= N:
        raise ValueError("BIP32: IL >= N, invalid key")

    child_key = (IL + parent_key) % N
    if child_key == 0:
        raise ValueError("BIP32: child key is zero")

    return child_key, IR


def bip32_root_from_seed(seed: bytes) -> tuple[int, bytes]:
    """Derive root key from seed (BIP32 master key generation)."""
    I = hmac.new(b'Bitcoin seed', seed, hashlib.sha512).digest()
    master_key   = int.from_bytes(I[:32], 'big') % N
    master_chain = I[32:]
    return master_key, master_chain


def derive_path(master_key: int, master_chain: bytes,
                path: str) -> tuple[int, bytes]:
    """
    Derive key at path like m/0/1/2' or m/44'/0'/0'/0/0.
    ' = hardened (+ 0x80000000).
    """
    key, chain = master_key, master_chain
    for segment in path.split('/'):
        if segment == 'm':
            continue
        hardened = segment.endswith("'")
        idx = int(segment.rstrip("'"))
        if hardened:
            idx += 0x80000000
        key, chain = bip32_ckd_priv(key, chain, idx)
    return key, chain


# ──────────────────────────────────────────────────────────────────
# Known puzzle data
# ──────────────────────────────────────────────────────────────────

# Puzzle addresses for ANY known puzzle #1-150 (utils/puzzle_registry.py).
# Falls back to a small hardcoded set if the registry import fails for
# some reason (e.g. script run outside the project tree).
try:
    from utils.puzzle_registry import PUZZLE_ADDRESSES
except Exception:
    PUZZLE_ADDRESSES = {
        1:  '1BgGZ9tcN4rm9KBzDn7KprQz87SZ26SAMH',
        2:  '1CUNEBjYrCn2y1SdiUMohaKUi4wpP326Lb',
        5:  '1E6NuFjCi27W5zoXg8TRdcSRq84zJeBW3k',
        10: '1LeBZP5QCwwgXRtmVUvTVrraqPUokyLHqe',
        15: '1QCbW9HWnwQWiQqVo5exhAnmfqKRrCRsvW',
        20: '1HsMJxNiV7TLxmoF6uJNkydxPFDog4NQum',
        25: '15JhYXn6Mx3oF4Y7PcTAv2wVVAuCFFQNiP',
        30: '1LHtnpd8nU5VHEMkG2TMYYNUjjLc992bps',
        71: '1PWo3JeB9jrGwfHDNpdGK54CRas7fsVzXU',
    }

# Known solved keys
KNOWN_KEYS = {
     1: 0x1,
     2: 0x3,
     3: 0x7,
     4: 0x8,
     5: 0x15,
     6: 0x31,
     7: 0x4c,
     8: 0xe0,
     9: 0x1d3,
    10: 0x202,
    11: 0x483,
    12: 0xa7b,
    13: 0x1460,
    14: 0x2930,
    15: 0x68f3,
    16: 0xc936,
    17: 0x1764f,
    18: 0x3080d,
    19: 0x5749f,
    20: 0xd2c55,
    21: 0x1ba534,
    22: 0x2de40f,
    23: 0x556e52,
    24: 0xdc2a04,
    25: 0x1fa5ee5,
    26: 0x340326e,
    27: 0x6ac3875,
    28: 0xd916ce8,
    29: 0x17e2551e,
    30: 0x3d94cd64,
    31: 0x7d4fe747,
    32: 0xb862a62e,
    33: 0x1a96ca8d8,
    34: 0x34a65911d,
    35: 0x4aed21170,
    36: 0x9de820a7c,
    37: 0x1757756a93,
    38: 0x22382facd0,
    39: 0x4b5f8303e9,
    40: 0xe9ae4933d6,
    41: 0x153869acc5b,
    42: 0x2a221c58d8f,
    43: 0x6bd3b27c591,
    44: 0xe02b35a358f,
    45: 0x122fca143c05,
    46: 0x2ec18388d544,
    47: 0x6cd610b53cba,
    48: 0xade6d7ce3b9b,
    49: 0x174176b015f4d,
    50: 0x22bd43c2e9354,
    # Puzzles 51-70 (source: btcpuzzle.info, verified 2026-06)
    51: 0x75070a1a009d4,
    52: 0xefae164cb9e3c,
    53: 0x180788e47e326c,
    54: 0x236fb6d5ad1f43,
    55: 0x6abe1f9b67e114,
    56: 0x9d18b63ac4ffdf,
    57: 0x1eb25c90795d61c,
    58: 0x2c675b852189a21,
    59: 0x7496cbb87cab44f,
    60: 0xfc07a1825367bbe,
    61: 0x13c96a3742f64906,
    62: 0x363d541eb611abee,
    63: 0x7cce5efdaccf6808,
    64: 0xf7051f27b09112d4,
    65: 0x1a838b13505b26867,
    66: 0x2832ed74f2b5e35ee,
    67: 0x730fc235c1942c1ae,
    68: 0xbebb3940cd0fc1491,
    69: 0x101d83275fb2bc7e0c,
    70: 0x349b84b6431a6c4ef1,
}


def verify_key_matches_puzzle(priv: int, puzzle_num: int) -> bool:
    """Check if private key matches the puzzle's address."""
    if puzzle_num not in PUZZLE_ADDRESSES:
        return False
    derived_addr = privkey_to_address(priv)
    return derived_addr == PUZZLE_ADDRESSES[puzzle_num]


# ──────────────────────────────────────────────────────────────────
# Test A: derive all puzzle keys from master privkey
# ──────────────────────────────────────────────────────────────────

def test_master_key_derivation(master_key_hex: str, target: int = 71):
    """
    Given the creator's master key (from nonce attack),
    try various BIP32 derivation paths to find puzzle keys.
    """
    master_key = int(master_key_hex, 16)

    # Try different chain codes (we don't know it, so try common seeds)
    seeds_to_try = [
        b'Bitcoin seed',
        b'Bitcoin Puzzle',
        b'puzzle',
        master_key.to_bytes(32, 'big'),   # key as its own chain code
    ]

    # Also try simple derivation without chain code
    # (some early wallets just did sha256(master + index))

    print(f"\n[BIP32-A] Testing master key: {master_key_hex[:20]}...")
    print(f"[BIP32-A] Trying {len(seeds_to_try)} chain code variants x multiple paths")

    paths_to_try = [
        'm/{i}',
        'm/0/{i}',
        'm/44/0/0/0/{i}',
        'm/0/{i}',
        "m/44'/0'/0'/0/{i}",
    ]

    for seed in seeds_to_try:
        # Try using seed as chain code directly
        # and using it to derive master key
        for path_template in paths_to_try:
            for puzzle_num in list(KNOWN_KEYS.keys())[:5]:
                path = path_template.replace('{i}', str(puzzle_num - 1))
                try:
                    chain = hashlib.sha256(seed).digest()
                    k, _ = derive_path(master_key, chain, path)
                    if verify_key_matches_puzzle(k, puzzle_num):
                        print(f"\n  *** DERIVATION FOUND! ***")
                        print(f"  Path: {path}")
                        print(f"  Chain seed: {seed}")
                        print(f"  Puzzle #{puzzle_num}: {hex(k)}")

                        # Derive target puzzle
                        path_t = path_template.replace('{i}', str(target - 1))
                        k_t, _ = derive_path(master_key, chain, path_t)
                        print(f"\n  *** PUZZLE #{target} KEY: {hex(k_t)} ***")
                        if verify_key_matches_puzzle(k_t, target):
                            print(f"  *** VERIFIED! Address matches! ***")
                        return k_t
                except Exception:
                    continue

    # Test simple: k_puzzle_n = sha256(master_key || n)
    print("\n[BIP32-A] Testing simple hash derivation: sha256(master || n)...")
    for puzzle_num in list(KNOWN_KEYS.keys())[:5]:
        for variant in [
            master_key.to_bytes(32, 'big') + puzzle_num.to_bytes(4, 'big'),
            master_key.to_bytes(32, 'big') + puzzle_num.to_bytes(4, 'little'),
            f"puzzle{puzzle_num}".encode() + master_key.to_bytes(32, 'big'),
        ]:
            k = int(hashlib.sha256(variant).hexdigest(), 16) % N
            if k and verify_key_matches_puzzle(k, puzzle_num):
                print(f"  *** HASH DERIVATION FOUND! Variant: {variant[:20]}")
                k_t = int(hashlib.sha256(
                    master_key.to_bytes(32, 'big') + target.to_bytes(4, 'big')
                ).hexdigest(), 16) % N
                print(f"  Puzzle #{target}: {hex(k_t)}")
                return k_t

    print("[BIP32-A] No derivation pattern found with this master key.")
    return None


# ──────────────────────────────────────────────────────────────────
# Test B: find derivation pattern from known puzzle keys alone
# ──────────────────────────────────────────────────────────────────

def test_key_derivation_pattern(target: int = 71):
    """
    Without the master key, test if known puzzle keys fit any simple pattern.
    """
    print("\n[BIP32-B] Testing derivation patterns from known puzzle keys...")
    known = [(n, k) for n, k in sorted(KNOWN_KEYS.items()) if n >= 5]

    # Test 1: linear relation  k_n = a*k_(n-1) + b  mod N
    print("\n  Test: linear recurrence k_n = a*k_(n-1) + b mod N")
    if len(known) >= 3:
        # From first two: k2 = a*k1 + b, k3 = a*k2 + b
        # a = (k3-k2) * modinv(k2-k1) mod N
        k1, k2, k3 = known[0][1], known[1][1], known[2][1]
        ds_12 = (k2 - k1) % N
        ds_23 = (k3 - k2) % N
        if ds_12 != 0:
            a = ds_23 * pow(ds_12, N-2, N) % N
            b = (k2 - a * k1) % N
            # Verify against all known keys
            predicted = k1
            all_match = True
            for _, expected in known[1:]:
                predicted = (a * predicted + b) % N
                if predicted != expected:
                    all_match = False
                    break
            if all_match:
                print(f"  *** LINEAR RECURRENCE FOUND! a={hex(a)[:16]}  b={hex(b)[:16]}")
                k = known[-1][1]
                for _ in range(target - known[-1][0]):
                    k = (a * k + b) % N
                print(f"  Puzzle #{target} prediction: {hex(k)}")
                return k
        print("  No linear recurrence")

    # Test 2: ratio  k_n / k_(n-1) = constant mod N
    print("\n  Test: geometric progression k_n = ratio * k_(n-1) mod N")
    if len(known) >= 3:
        k1, k2, k3 = known[0][1], known[1][1], known[2][1]
        if k1 != 0 and k2 != 0:
            ratio12 = k2 * pow(k1, N-2, N) % N
            ratio23 = k3 * pow(k2, N-2, N) % N
            if ratio12 == ratio23:
                # Verify
                predicted = k1
                all_match = True
                for _, expected in known[1:]:
                    predicted = predicted * ratio12 % N
                    if predicted != expected:
                        all_match = False
                        break
                if all_match:
                    print(f"  *** GEOMETRIC FOUND! ratio={hex(ratio12)[:16]}")
                    k = known[-1][1]
                    for _ in range(target - known[-1][0]):
                        k = k * ratio12 % N
                    print(f"  Puzzle #{target} prediction: {hex(k)}")
                    return k
        print("  No geometric progression")

    # Test 3: XOR/hash relations
    print("\n  Test: hash-based k_n = HASH(n) % range_size + range_start")
    for n, k in known:
        lo = 1 << (n - 1)
        hi = (1 << n) - 1
        offset = k - lo
        max_offset = hi - lo
        if max_offset > 0:
            normalized = offset / max_offset

    # Test 4: Multiply-and-truncate from a seed
    print("\n  Test: PRNG-style k_n = (seed * A^n + B) mod range")
    # Too complex to invert without more known keys

    print("\n[BIP32-B] No simple derivation pattern found.")
    print("  Add more known keys from puzzles #18-66 for better analysis.")
    return None


# ──────────────────────────────────────────────────────────────────
# Test C: deterministic key generation schemes
# ──────────────────────────────────────────────────────────────────

def test_deterministic_schemes(target: int = 71):
    """
    Test various deterministic key generation schemes used in early Bitcoin wallets.
    """
    print("\n[BIP32-C] Testing deterministic generation schemes...")
    known = [(n, k) for n, k in sorted(KNOWN_KEYS.items()) if n >= 5]

    schemes = [
        # (name, key_for_n)
        ("SHA256(n)",
         lambda n: int(hashlib.sha256(str(n).encode()).hexdigest(), 16) % N),
        ("SHA256('puzzle' + n)",
         lambda n: int(hashlib.sha256(f'puzzle{n}'.encode()).hexdigest(), 16) % N),
        ("SHA256(n.to_bytes)",
         lambda n: int(hashlib.sha256(n.to_bytes(4,'big')).hexdigest(), 16) % N),
        ("SHA256(sha256(n))",
         lambda n: int(hashlib.sha256(hashlib.sha256(str(n).encode()).digest()).hexdigest(), 16) % N),
        ("HMAC-SHA256('puzzle', n)",
         lambda n: int(hmac.new(b'puzzle', str(n).encode(), hashlib.sha256).hexdigest(), 16) % N),
        ("keccak-256(n)  [Ethereum style]",
         lambda n: _keccak256_int(str(n).encode()) % N),
    ]

    for name, fn in schemes:
        try:
            match = all(fn(n) == k for n, k in known[:4])
            status = "*** MATCH! ***" if match else "no match"
            print(f"  {name:40s}: {status}")
            if match:
                k_t = fn(target)
                print(f"\n  *** SCHEME FOUND: {name}")
                print(f"  Puzzle #{target} key: {hex(k_t)}")
                return k_t
        except Exception as e:
            print(f"  {name:40s}: error ({e})")

    return None


def _keccak256_int(data: bytes) -> int:
    """Keccak-256 hash (not SHA3) → int."""
    try:
        from Crypto.Hash import keccak
        k = keccak.new(digest_bits=256)
        k.update(data)
        return int(k.hexdigest(), 16)
    except ImportError:
        # Fallback: use sha3_256 (close but not identical to Ethereum's keccak)
        return int(hashlib.sha3_256(data).hexdigest(), 16)


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='BIP32 / Key Derivation Pattern Analysis',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    parser.add_argument('--master-key', default='',
                        help='Creator master private key hex (from nonce_attack.py)')
    parser.add_argument('--test-all',   action='store_true',
                        help='Run all tests (A + B + C)')
    parser.add_argument('--target',     type=int, default=71,
                        help='Puzzle number to predict (default: 71). '
                             'Run analysis/puzzle_status.py --unsolved for candidates.')
    args = parser.parse_args()
    target = args.target

    print("\n" + "="*60)
    print("  BIP32 / KEY DERIVATION PATTERN ANALYSIS")
    print("="*60)
    print(f"  Known puzzle keys: {len(KNOWN_KEYS)}  |  Target: #{target}")
    print(f"  Tip: add more to KNOWN_KEYS for better analysis")

    k_t = None

    if args.master_key:
        # Test A: we have the master key
        k_t = test_master_key_derivation(args.master_key, target=target)
    elif args.test_all:
        k_t = test_deterministic_schemes(target=target)
        if k_t is None:
            k_t = test_key_derivation_pattern(target=target)
    else:
        k_t = test_deterministic_schemes(target=target)
        if k_t is None:
            k_t = test_key_derivation_pattern(target=target)

    if k_t is not None:
        print(f"\n{'!'*60}")
        print(f"  PUZZLE #{target} KEY PREDICTED: {hex(k_t)}")
        print(f"  VERIFY:  python main.py --test")
        print(f"{'!'*60}")
        with open(f'PREDICTED_KEY_{target}.txt', 'w') as f:
            f.write(f"Puzzle #{target} predicted key: {hex(k_t)}\n")
            f.write(f"Decimal: {k_t}\n")
    else:
        print(f"\n  No pattern found. Recommendations:")
        print(f"  1. Add more known keys to KNOWN_KEYS dict")
        print(f"     Source: https://privatekeys.pw/puzzles/bitcoin-puzzle-tx")
        print(f"  2. Run nonce attack: python analysis/nonce_attack.py")
        print(f"  3. Try with --test-all for all detection methods")


if __name__ == '__main__':
    main()
