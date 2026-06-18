"""
Тесты ECC арифметики — запускать перед любой другой работой!
  python tests/test_ecc.py
  python -m pytest tests/test_ecc.py -v
"""

import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ecc.curve import G, N, INF, point_add, point_double, scalar_mul, pubkey, point_neg
from ecc.field import P, inv, mul
from ecc.glv   import (glv_endomorphism, glv_decompose, scalar_mul_glv,
                         BETA, LAMBDA)
from utils.address import (point_to_address, decode_address_hash160,
                            point_to_hash160_compressed, get_target_for_kernel,
                            verify_key_address)


# ==============================================================
# ECC тесты
# ==============================================================

def test_generator_on_curve():
    x, y = G
    assert (y * y) % P == (x * x * x + 7) % P, "G not on curve!"
    print("[OK] G lies on curve y^2=x^3+7")

def test_infinity():
    neg_G = point_neg(G)
    assert point_add(G, neg_G) == INF
    print("[OK] G + (-G) = INF")

def test_neutral_element():
    assert point_add(G, INF) == G
    assert point_add(INF, G) == G
    print("[OK] G + INF = G")

def test_order():
    result = scalar_mul(N, G)
    assert result == INF, f"N*G != INF, got {result}"
    print("[OK] N*G = INF")

def test_double():
    assert scalar_mul(2, G) == point_add(G, G)
    print("[OK] 2*G = G+G")

def test_associativity():
    P3 = scalar_mul(3, G)
    P5 = scalar_mul(5, G)
    P8 = scalar_mul(8, G)
    assert point_add(P3, P5) == P8, "ECC addition not associative?"
    print("[OK] 3*G + 5*G = 8*G")

def test_negation():
    k    = 2**30 + 12345
    pt   = scalar_mul(k, G)
    neg  = point_neg(pt)
    x, y = pt
    assert neg == (x, (-y) % P)
    assert point_add(pt, neg) == INF
    print("[OK] Negation: P + (-P) = INF")


# ==============================================================
# GLV тесты
# ==============================================================

def test_glv_endomorphism():
    phi_G   = glv_endomorphism(G)
    lambda_G = scalar_mul(LAMBDA, G)
    assert phi_G == lambda_G, f"GLV endomorphism error!\n  phi(G)={phi_G}\n  lam*G={lambda_G}"
    print("[OK] phi(G) = lambda*G")

def test_glv_decompose():
    test_keys = [12345, 2**65 + 777, N - 1, 2**70 + 42]
    for k in test_keys:
        k1, k2 = glv_decompose(k)
        assert (k1 + k2 * LAMBDA) % N == k % N, f"GLV decompose error for k={k}"
        assert k1.bit_length() <= 130, f"k1 too large: {k1.bit_length()} bits"
        assert k2.bit_length() <= 130, f"k2 too large: {k2.bit_length()} bits"
    print(f"[OK] GLV decompose: k1,k2 <= 130 bits (tested {len(test_keys)} keys)")

def test_glv_mul_correct():
    test_keys = [1, 7, 2**64 + 42, 2**70 - 1, 2**70, 2**70 + 999]
    for k in test_keys:
        glv = scalar_mul_glv(k, G)
        std = scalar_mul(k, G)
        assert glv == std, f"GLV mul != std for k={k}"
    print(f"[OK] scalar_mul_glv = scalar_mul (tested {len(test_keys)} keys)")

def test_glv_speed():
    k = 2**70 + 0xDEADBEEF

    N_ITER = 5
    t0 = time.perf_counter()
    for _ in range(N_ITER):
        scalar_mul(k, G)
    t_std = time.perf_counter() - t0

    t0 = time.perf_counter()
    for _ in range(N_ITER):
        scalar_mul_glv(k, G)
    t_glv = time.perf_counter() - t0

    ratio = t_std / t_glv if t_glv > 0 else 0
    print(f"[OK] Speed: std={t_std:.3f}s  glv={t_glv:.3f}s  speedup={ratio:.2f}x")


# ==============================================================
# Bitcoin address тесты
# ==============================================================

def test_puzzle1_address():
    pt   = scalar_mul(1, G)
    addr = point_to_address(pt[0], pt[1])
    EXPECTED = '1BgGZ9tcN4rm9KBzDn7KprQz87SZ26SAMH'
    assert addr == EXPECTED, f"Puzzle #1 address wrong!\n  got: {addr}\n  exp: {EXPECTED}"
    print(f"[OK] Puzzle #1 address: {addr}")

def test_hash160_roundtrip():
    k      = 1
    pt     = scalar_mul(k, G)
    h1     = point_to_hash160_compressed(pt[0], pt[1])
    addr   = point_to_address(pt[0], pt[1])
    h2     = decode_address_hash160(addr)
    assert h1 == h2, f"hash160 mismatch: {h1.hex()} != {h2.hex()}"
    print(f"[OK] hash160 roundtrip: {h1.hex()}")

def test_target_for_kernel():
    addr   = '1BgGZ9tcN4rm9KBzDn7KprQz87SZ26SAMH'   # puzzle #1
    tw     = get_target_for_kernel(addr)
    assert len(tw) == 5
    assert all(0 <= w < 2**32 for w in tw)
    print(f"[OK] target_for_kernel: {[hex(w) for w in tw]}")

def test_verify_key():
    # k=1 → address puzzle #1
    assert verify_key_address(1, '1BgGZ9tcN4rm9KBzDn7KprQz87SZ26SAMH')
    assert not verify_key_address(2, '1BgGZ9tcN4rm9KBzDn7KprQz87SZ26SAMH')
    print("[OK] verify_key_address works")

def test_multiple_keys():
    # Проверяем k=1..5 → адреса из списка пазлов
    from main import PUZZLES
    for pnum in [1]:
        pz   = PUZZLES[pnum]
        k    = pz['start']
        addr = pz['addr']
        if pz['start'] == pz['end']:   # пазл #1: k строго равно 1
            assert verify_key_address(k, addr), f"Puzzle #{pnum}: key {k} -> addr mismatch"
            print(f"[OK] Puzzle #{pnum}: k={hex(k)} -> {addr}")


# ==============================================================
# Запуск всех тестов
# ==============================================================

ALL_TESTS = [
    test_generator_on_curve,
    test_infinity,
    test_neutral_element,
    test_order,
    test_double,
    test_associativity,
    test_negation,
    test_glv_endomorphism,
    test_glv_decompose,
    test_glv_mul_correct,
    test_glv_speed,
    test_puzzle1_address,
    test_hash160_roundtrip,
    test_target_for_kernel,
    test_verify_key,
    test_multiple_keys,
]

if __name__ == '__main__':
    print("=" * 55)
    print("ECC & Address Tests")
    print("=" * 55)
    failed = []
    for fn in ALL_TESTS:
        try:
            fn()
        except Exception as e:
            print(f"[FAIL] {fn.__name__}: {e}")
            failed.append(fn.__name__)
    print("=" * 55)
    if not failed:
        print(f"ALL {len(ALL_TESTS)} TESTS PASSED [OK]")
    else:
        print(f"FAILED: {failed}")
    sys.exit(len(failed))
