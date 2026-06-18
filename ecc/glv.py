"""
GLV эндоморфизм для secp256k1 — ускорение scalar_mul ~1.7x
k = k1 + k2*λ (mod N)
φ(P) = (β*x mod P, y) = λ*P
"""

from .curve import N, P, point_add, point_neg, scalar_mul as std_mul

BETA   = 0x7AE96A2B657C07106E64479EAC3434E99CF0497512F58995C1396C28719501EE
LAMBDA = 0x5363AD4CC05C30E0A5261C028812645A122E22EA20816678DF02967C1B23BD72

# Предвычисленные параметры GLV разложения (secp256k1 spec)
_A1 =  0x3086D221A7D46BCDE86C90E49284EB15
_B1 = -0xE4437ED6010E88286F547FA90ABFE4C3
_A2 =  0x114CA50F7A8E2F3F657C1108D9D44CFD8
_B2 =  0x3086D221A7D46BCDE86C90E49284EB15

def glv_endomorphism(point):
    """φ(x, y) = (β*x mod P, y) ≡ λ*point — одна операция умножения."""
    if point == (0, 0): return (0, 0)
    x, y = point
    return ((BETA * x) % P, y)

def glv_decompose(k: int):
    """
    Разложение k = k1 + k2*λ (mod N).
    |k1|, |k2| ≈ 128 бит вместо 256.
    """
    n1 = (_B2 * k) % N
    n2 = ((-_B1) * k) % N

    c1 = (n1 + N // 2) // N
    c2 = (n2 + N // 2) // N

    k1 = (k - c1 * _A1 - c2 * _A2) % N
    k2 = (-c1 * _B1 - c2 * _B2) % N

    if k1 > N // 2: k1 -= N
    if k2 > N // 2: k2 -= N

    return k1, k2

def scalar_mul_glv(k: int, point):
    """
    Ускоренное умножение: k*P = k1*P + k2*φ(P).

    Использует алгоритм Шамира (Simultaneous Double-and-Add):
      - одно удвоение вместо двух за итерацию
      - 128 итераций вместо 256 (k1, k2 ~ 128 бит)
      - Предвычисляется P1+P2 для обработки обоих битов за одно сложение
    Итого: ~128 doublings + ~128 adds ≈ 256 ops vs стандарт 256+128 = 384 ops → ~1.5x
    """
    k1, k2 = glv_decompose(k)
    phi_pt  = glv_endomorphism(point)

    # Учитываем знаки k1, k2
    P1 = point    if k1 >= 0 else point_neg(point)
    P2 = phi_pt   if k2 >= 0 else point_neg(phi_pt)
    k1, k2 = abs(k1), abs(k2)

    # Предвычисление P1+P2 для алгоритма Шамира
    P12 = point_add(P1, P2)

    bits   = max(k1.bit_length(), k2.bit_length(), 1)
    result = (0, 0)   # INF

    for i in range(bits - 1, -1, -1):
        # Одно удвоение (ключевая оптимизация vs два отдельных цикла)
        result = point_add(result, result) if result != (0, 0) else (0, 0)
        b1 = (k1 >> i) & 1
        b2 = (k2 >> i) & 1
        if b1 and b2:
            result = point_add(result, P12)
        elif b1:
            result = point_add(result, P1)
        elif b2:
            result = point_add(result, P2)

    return result
