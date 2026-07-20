"""
Kangaroo key reconstruction — pure, worker-independent.

A distinguished point stores only the x-coordinate, which is shared by P and -P,
so a collision means the two discrete logs agree *up to sign*. Each herd's log is
modelled as `a*k + b (mod N)`:

    tame : starts at tame_base = k_start   ->  a=0,   b = tame_base + dist
    wild : starts at  Q = k*G              ->  a=1,   b = dist
    neg  : starts at -Q = -k*G             ->  a=N-1, b = dist

A collision between two herds means `a1*k + b1 == s*(a2*k + b2)` for s = +/-1,
solved by `k = (s*b2 - b1) / (a1 - s*a2) mod N`. Every candidate is verified
against the real pubkey, so a wrong sign branch costs nothing.

This is deliberately GPU-free so the DP-pool SERVER can reconstruct keys from
distinguished points submitted by any worker — the tame_base (= k_start) and Q
(= pubkey) are shared by every worker, so a tame DP from worker A and a wild DP
from worker B reconstruct exactly as if one engine had found both.
"""
from ecc.curve import scalar_mul, G, N, P

_KIND = {0: 'tame', 1: 'wild', 2: 'neg', 'tame': 'tame', 'wild': 'wild', 'neg': 'neg'}


def decompress_pubkey(hex_str: str):
    """secp256k1 compressed pubkey (02/03 + 32-byte x, hex) -> (x, y) ints.

    P = 2^256-2^32-977 is 3 mod 4, so sqrt(a) = a^((P+1)/4). The 02/03 prefix
    picks the even/odd y. This is what a mempool exposes when a puzzle address is
    first spent from — the moment the pool server is worth starting."""
    h = hex_str.strip().lower()
    if h.startswith('0x'):
        h = h[2:]
    if len(h) != 66 or h[:2] not in ('02', '03'):
        raise ValueError("expected a 33-byte compressed pubkey (02/03 + x)")
    x = int(h[2:], 16)
    y2 = (pow(x, 3, P) + 7) % P
    y = pow(y2, (P + 1) // 4, P)
    if (y * y - y2) % P != 0:
        raise ValueError("x is not on the curve")
    if (y & 1) != (int(h[:2], 16) & 1):
        y = P - y
    return x, y


def herd_affine(kind, dist: int, tame_base: int):
    """Return (a, b) with the herd's discrete log == a*k + b (mod N)."""
    k = _KIND[kind]
    if k == 'tame':
        return 0, (tame_base + dist) % N
    if k == 'wild':
        return 1, dist % N
    return N - 1, dist % N          # neg: -k + dist


def recover(dist1, kind1, dist2, kind2, k_start, k_end, pubkey):
    """Recover k from an x-collision between two herds, or None.

    pubkey is the target EC point as an (x, y) int tuple. k_start is also the
    tame_base. Returns the private key int iff it lands in [k_start, k_end] and
    verifies against pubkey.
    """
    a1, b1 = herd_affine(kind1, dist1, k_start)
    a2, b2 = herd_affine(kind2, dist2, k_start)
    for s in (1, N - 1):                       # the +P / -P ambiguity
        A = (a1 - s * a2) % N
        B = (s * b2 - b1) % N
        if A == 0:
            continue                            # no information from this pair
        k = (B * pow(A, -1, N)) % N
        if k_start <= k <= k_end and scalar_mul(k, G) == tuple(pubkey):
            return k
    return None
