"""
Утилиты для работы с Bitcoin адресами.
Декодирование Base58Check → hash160.
Вычисление hash160 для публичного ключа.
"""

import hashlib
import struct

B58_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

# RIPEMD160 начальные векторы (из спецификации)
_RIPEMD_IV = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0]


def b58decode(s: str) -> bytes:
    """Decode Base58 string to bytes (leading '1' = 0x00 bytes)."""
    n = 0
    for c in s:
        n = n * 58 + B58_ALPHABET.index(c)
    # Count leading '1's → leading zero bytes
    leading_zeros = 0
    for c in s:
        if c == '1':
            leading_zeros += 1
        else:
            break
    result = n.to_bytes(max(1, (n.bit_length() + 7) // 8), 'big')
    return b'\x00' * leading_zeros + result


def decode_address_hash160(address: str) -> bytes:
    """
    P2PKH адрес → 20-байтный hash160.
    Проверяет контрольную сумму.
    """
    data = b58decode(address)
    if len(data) != 25:
        raise ValueError(f"Bad address length {len(data)}: {address}")
    if data[0] != 0x00:
        raise ValueError(f"Not a P2PKH address (version={data[0]}): {address}")

    payload  = data[:21]
    checksum = data[21:]
    check    = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if check != checksum:
        raise ValueError(f"Bad checksum for address: {address}")

    return payload[1:]   # 20 bytes hash160


def hash160(pub_bytes: bytes) -> bytes:
    """SHA256 → RIPEMD160 (hash160)."""
    sha = hashlib.sha256(pub_bytes).digest()
    rmd = hashlib.new('ripemd160')
    rmd.update(sha)
    return rmd.digest()


def point_to_hash160_compressed(x: int, y: int) -> bytes:
    """secp256k1 точка → hash160 для сжатого публичного ключа."""
    prefix = b'\x02' if y % 2 == 0 else b'\x03'
    pub    = prefix + x.to_bytes(32, 'big')
    return hash160(pub)


def point_to_address(x: int, y: int) -> str:
    """secp256k1 точка → Bitcoin P2PKH адрес (сжатый ключ)."""
    h160    = point_to_hash160_compressed(x, y)
    payload = b'\x00' + h160
    check   = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    data    = payload + check

    n = int.from_bytes(data, 'big')
    result = ''
    while n > 0:
        n, r = divmod(n, 58)
        result = B58_ALPHABET[r] + result

    for byte in data:
        if byte == 0:
            result = '1' + result
        else:
            break

    return result


def get_target_for_kernel(address: str) -> list:
    """
    Конвертирует P2PKH адрес в формат для BitCrack OpenCL ядра.

    BitCrack ядро вычисляет ripemd160sha256NoFinal() → digest[5],
    затем в doRMD160FinalRound() добавляет IV и делает byte-swap.
    Для сравнения нужен «обратный» формат:

        target[j] = (LE(hash160_word_j) - iv[(j+1)%5]) & 0xFFFFFFFF

    где LE = little-endian uint32 из 4 байт hash160.
    Это эквивалентно undoRMD160FinalRound() из CLKeySearchDevice.cpp.
    """
    h160 = decode_address_hash160(address)
    return [
        (struct.unpack_from('<I', h160, 4 * j)[0] - _RIPEMD_IV[(j + 1) % 5]) & 0xFFFFFFFF
        for j in range(5)
    ]


def verify_key_address(k: int, address: str) -> bool:
    """Проверяет, соответствует ли приватный ключ k данному адресу."""
    from ecc.curve import scalar_mul, G
    pt = scalar_mul(k, G)
    if pt == (0, 0):
        return False
    return point_to_address(pt[0], pt[1]) == address
