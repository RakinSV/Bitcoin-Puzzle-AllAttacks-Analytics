"""
secp256k1 — операции с точками эллиптической кривой
y^2 = x^3 + 7 (mod P)
"""

from .field import P, add, sub, mul, inv, neg

N  = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8

INF = (0, 0)

def is_inf(point) -> bool:
    return point == INF

def point_neg(point):
    if is_inf(point):
        return INF
    x, y = point
    return (x, neg(y))

def point_add(P1, P2):
    if is_inf(P1): return P2
    if is_inf(P2): return P1

    x1, y1 = P1
    x2, y2 = P2

    if x1 == x2 and y1 == neg(y2):
        return INF

    if P1 == P2:
        return point_double(P1)

    lam = mul(sub(y2, y1), inv(sub(x2, x1)))
    x3  = sub(sub(mul(lam, lam), x1), x2)
    y3  = sub(mul(lam, sub(x1, x3)), y1)
    return (x3 % P, y3 % P)

def point_double(point):
    if is_inf(point): return INF

    x, y = point
    if y == 0: return INF

    lam = mul(mul(3, mul(x, x)), inv(mul(2, y)))
    x3  = sub(mul(lam, lam), mul(2, x))
    y3  = sub(mul(lam, sub(x, x3)), y)
    return (x3 % P, y3 % P)

def scalar_mul(k: int, point):
    """Double-and-add скалярное умножение."""
    if k == 0: return INF
    if k < 0:  return scalar_mul(-k, point_neg(point))

    result = INF
    addend = point

    while k:
        if k & 1:
            result = point_add(result, addend)
        addend = point_double(addend)
        k >>= 1

    return result

G = (GX, GY)

def pubkey(k: int):
    return scalar_mul(k, G)

def point_to_bytes_compressed(point) -> bytes:
    x, y = point
    prefix = b'\x02' if y % 2 == 0 else b'\x03'
    return prefix + x.to_bytes(32, 'big')
