"""
Bitcoin Puzzle Registry — addresses & ranges for puzzles #1-150.
=================================================================
Static data: addresses never change once funded. SOLVED/UNSOLVED status
is DYNAMIC (changes as people find keys) — checked live via blockchain
in analysis/puzzle_status.py. This module only answers "what address
and key-range does puzzle N have?".

Sources:
  - Puzzles 1-70: derived from publicly known private keys
    (see analysis/rng_analysis.py KNOWN_KEYS, sourced from btcpuzzle.info)
  - Puzzles 71-160: keyhunt's tests/unsolvedpuzzles.txt, RENUMBERED against the
    blockchain (see the correction note below).

Puzzle N's private key lies in [2^(N-1), 2^N - 1].
"""

# Addresses for puzzles 71-160.
#
# CORRECTED 2026-08. The previous table read keyhunt's `unsolvedpuzzles.txt` as
# "line N -> puzzle N+66". That file lists only the puzzles UNSOLVED when it was
# written, so the ten already-solved multiples of five (75, 80, ... 120) are
# absent from it and the numbering drifted by +1 for each one skipped, reaching
# +10. Everything we concluded about high puzzles was attached to the wrong
# number: the entry labelled 125 is really puzzle 135 — proved by deriving the
# published 135-bit key for #135, which lands exactly on that address.
#
# Re-labelled from the chain instead of from line numbers: puzzle N is funded
# with exactly N * 0.1 BTC, so round(funded_BTC * 10) IS the puzzle number
# (analysis/verify_registry.py re-checks this at any time). Puzzles 75, 80, ...
# 120 have no entry here because that source never contained them; they are all
# solved, so nothing we search depends on them.
_ADDRESSES_71_150 = {
    71: '1PWo3JeB9jrGwfHDNpdGK54CRas7fsVzXU',
    72: '1JTK7s9YVYywfm5XUH7RNhHJH1LshCaRFR',
    73: '12VVRNPi4SJqUTsp6FmqDqY5sGosDtysn4',
    74: '1FWGcVDK3JGzCC3WtkYetULPszMaK2Jksv',
    76: '1DJh2eHFYQfACPmrvpyWc8MSTYKh7w9eRF',
    77: '1Bxk4CQdqL9p22JEtDfdXMsng1XacifUtE',
    78: '15qF6X51huDjqTmF9BJgxXdt1xcj46Jmhb',
    79: '1ARk8HWJMn8js8tQmGUJeQHjSE7KRkn2t8',
    81: '15qsCm78whspNQFydGJQk5rexzxTQopnHZ',
    82: '13zYrYhhJxp6Ui1VV7pqa5WDhNWM45ARAC',
    83: '14MdEb4eFcT3MVG5sPFG4jGLuHJSnt1Dk2',
    84: '1CMq3SvFcVEcpLMuuH8PUcNiqsK1oicG2D',
    86: '1K3x5L6G57Y494fDqBfrojD28UJv4s5JcK',
    87: '1PxH3K1Shdjb7gSEoTX7UPDZ6SH4qGPrvq',
    88: '16AbnZjZZipwHMkYKBSfswGWKDmXHjEpSf',
    89: '19QciEHbGVNY4hrhfKXmcBBCrJSBZ6TaVt',
    91: '1EzVHtmbN4fs4MiNk3ppEnKKhsmXYJ4s74',
    92: '1AE8NzzgKE7Yhz7BWtAcAAxiFMbPo82NB5',
    93: '17Q7tuG2JwFFU9rXVj3uZqRtioH3mx2Jad',
    94: '1K6xGMUbs6ZTXBnhw1pippqwK6wjBWtNpL',
    96: '15ANYzzCp5BFHcCnVFzXqyibpzgPLWaD8b',
    97: '18ywPwj39nGjqBrQJSzZVq2izR12MDpDr8',
    98: '1CaBVPrwUxbQYYswu32w7Mj4HR4maNoJSX',
    99: '1JWnE6p6UN7ZJBN7TtcbNDoRcjFtuDWoNL',
    101: '1CKCVdbDJasYmhswB6HKZHEAnNaDpK7W4n',
    102: '1PXv28YxmYMaB8zxrKeZBW8dt2HK7RkRPX',
    103: '1AcAmB6jmtU6AiEcXkmiNE9TNVPsj9DULf',
    104: '1EQJvpsmhazYCcKX5Au6AZmZKRnzarMVZu',
    106: '18KsfuHuzQaBTNLASyj15hy4LuqPUo1FNB',
    107: '15EJFC5ZTs9nhsdvSUeBXjLAuYq3SWaxTc',
    108: '1HB1iKUqeffnVsvQsbpC6dNi1XKbyNuqao',
    109: '1GvgAXVCbA8FBjXfWiAms4ytFeJcKsoyhL',
    111: '1824ZJQ7nKJ9QFTRBqn7z7dHV5EGpzUpH3',
    112: '18A7NA9FTsnJxWgkoFfPAFbQzuQxpRtCos',
    113: '1NeGn21dUDDeqFQ63xb2SpgUuXuBLA4WT4',
    114: '174SNxfqpdMGYy5YQcfLbSTK3MRNZEePoy',
    116: '1MnJ6hdhvK37VLmqcdEwqC3iFxyWH2PHUV',
    117: '1KNRfGWw7Q9Rmwsc6NT5zsdvEb9M2Wkj5Z',
    118: '1PJZPzvGX19a7twf5HyD2VvNiPdHLzm9F6',
    119: '1GuBBhf61rnvRe4K8zu8vdQB3kHzwFqSy7',
    121: '1GDSuiThEV64c166LUFC9uDcVdGjqkxKyh',
    122: '1Me3ASYt5JCTAK2XaC32RMeH34PdprrfDx',
    123: '1CdufMQL892A69KXgv6UNBD17ywWqYpKut',
    124: '1BkkGsX9ZM6iwL3zbqs7HWBV7SvosR6m8N',
    125: '1PXAyUB8ZoH3WD8n5zoAthYjN15yN5CVq5',
    126: '1AWCLZAjKbV1P7AHvaPNCKiB7ZWVDMxFiz',
    127: '1G6EFyBRU86sThN3SSt3GrHu1sA7w7nzi4',
    128: '1MZ2L1gFrCtkkn6DnTT2e4PFUTHw9gNwaj',
    129: '1Hz3uv3nNZzBVMXLGadCucgjiCs5W9vaGz',
    130: '1Fo65aKq8s8iquMt6weF1rku1moWVEd5Ua',
    131: '16zRPnT8znwq42q7XeMkZUhb1bKqgRogyy',
    132: '1KrU4dHE5WrW8rhWDsTRjR21r8t3dsrS3R',
    133: '17uDfp5r4n441xkgLFmhNoSW1KWp6xVLD',
    134: '13A3JrvXmvg5w9XGvyyR4JEJqiLz8ZySY3',
    135: '16RGFo6hjq9ym6Pj7N5H7L1NR1rVPJyw2v',
    136: '1UDHPdovvR985NrWSkdWQDEQ1xuRiTALq',
    137: '15nf31J46iLuK1ZkTnqHo7WgN5cARFK3RA',
    138: '1Ab4vzG6wEQBDNQM1B2bvUz4fqXXdFk2WT',
    139: '1Fz63c775VV9fNyj25d9Xfw3YHE6sKCxbt',
    140: '1QKBaU6WAeycb3DbKbLBkX7vJiaS8r42Xo',
    141: '1CD91Vm97mLQvXhrnoMChhJx4TP9MaQkJo',
    142: '15MnK2jXPqTMURX4xC3h4mAZxyCcaWWEDD',
    143: '13N66gCzWWHEZBxhVxG18P8wyjEWF9Yoi1',
    144: '1NevxKDYuDcCh1ZMMi6ftmWwGrZKC6j7Ux',
    145: '19GpszRNUej5yYqxXoLnbZWKew3KdVLkXg',
    146: '1M7ipcdYHey2Y5RZM34MBbpugghmjaV89P',
    147: '18aNhurEAJsw6BAgtANpexk5ob1aGTwSeL',
    148: '1FwZXt6EpRT7Fkndzv6K4b4DFoT4trbMrV',
    149: '1CXvTzR6qv8wJ7eprzUKeWxyGcHwDYP1i2',
    150: '1MUJSJYtGPVGkBCTqGspnxyHahpt5Te8jy',
    151: '13Q84TNNvgcL3HJiqQPvyBb9m4hxjS3jkV',
    152: '1LuUHyrQr8PKSvbcY1v1PiuGuqFjWpDumN',
    153: '18192XpzzdDi2K11QVHR7td2HcPS6Qs5vg',
    154: '1NgVmsCCJaKLzGyKLFJfVequnFW9ZvnMLN',
    155: '1AoeP37TmHdFh8uN72fu9AqgtLrUwcv2wJ',
    156: '1FTpAbQa4h8trvhQXjXnmNhqdiGBd1oraE',
    157: '14JHoRAdmJg3XR4RjMDh6Wed6ft6hzbQe9',
    158: '19z6waranEf8CcP8FqNgdwUe1QRxvUNKBG',
    159: '14u4nA5sugaswb6SZgn5av2vuChdMnD9E5',
    160: '1NBC8uXJy1GiJ6drkiZa1WuKn51ps7EPTv',
}

# Approximate BTC reward per puzzle (reward_n ~= n/10, per btcpuzzle.info scheme)
def estimated_reward_btc(n: int) -> float:
    return round(n / 10.0, 2)


def puzzle_range(n: int) -> tuple:
    """Key range for puzzle n: [2^(n-1), 2^n - 1]."""
    return (1 << (n - 1), (1 << n) - 1)


PUZZLE_ADDRESSES = dict(_ADDRESSES_71_150)


def _add_addresses_from_known_keys():
    """Derive addresses for puzzles 1-70 from their public, known private keys."""
    try:
        from analysis.rng_analysis import KNOWN_KEYS
        from ecc.curve import scalar_mul, G
        from utils.address import point_to_address
        for n, k in KNOWN_KEYS.items():
            if n not in PUZZLE_ADDRESSES:
                pt = scalar_mul(k, G)
                PUZZLE_ADDRESSES[n] = point_to_address(pt[0], pt[1])
    except Exception as e:
        print(f"[puzzle_registry] WARNING: could not derive addresses 1-70: {e}")


_add_addresses_from_known_keys()


def get_puzzle(n: int) -> dict:
    """Returns {'addr':, 'start':, 'end':} for puzzle n. Raises KeyError if unknown."""
    if n not in PUZZLE_ADDRESSES:
        lo_k, hi_k = min(PUZZLE_ADDRESSES), max(PUZZLE_ADDRESSES)
        if lo_k <= n <= hi_k:
            # Saying "known range: 1-160" here is misleading — n IS in that range.
            # These are the solved multiples of five that the upstream source
            # (a list of UNSOLVED puzzles) never contained.
            raise KeyError(
                f"No address on record for puzzle #{n}. It falls inside the "
                f"covered range {lo_k}-{hi_k} but has no entry: puzzles "
                f"{', '.join(str(m) for m in sorted(set(range(75, 121, 5)) - set(PUZZLE_ADDRESSES)))} "
                f"are already solved and were absent from the source list.")
        raise KeyError(
            f"No known address for puzzle #{n}. Known range: {lo_k}-{hi_k}")
    lo, hi = puzzle_range(n)
    return {'addr': PUZZLE_ADDRESSES[n], 'start': lo, 'end': hi}


def all_puzzle_numbers() -> list:
    return sorted(PUZZLE_ADDRESSES.keys())


def is_known(n: int) -> bool:
    return n in PUZZLE_ADDRESSES
