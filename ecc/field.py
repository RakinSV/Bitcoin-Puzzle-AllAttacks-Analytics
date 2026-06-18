"""
Арифметика конечного поля F_p для secp256k1
P = 2^256 - 2^32 - 977
"""

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F

def add(a: int, b: int) -> int:
    return (a + b) % P

def sub(a: int, b: int) -> int:
    return (a - b) % P

def mul(a: int, b: int) -> int:
    return (a * b) % P

def neg(a: int) -> int:
    return (-a) % P

def inv(a: int) -> int:
    """Обратный элемент через малую теорему Ферма: a^(P-2) mod P"""
    if a == 0:
        raise ZeroDivisionError("No inverse for 0")
    return pow(a, P - 2, P)

def div(a: int, b: int) -> int:
    return mul(a, inv(b))

def sqrt(a: int) -> int:
    """Квадратный корень mod P. P ≡ 3 (mod 4)"""
    return pow(a, (P + 1) // 4, P)
