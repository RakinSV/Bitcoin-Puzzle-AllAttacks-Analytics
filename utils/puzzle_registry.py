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
  - Puzzles 71-150: github.com/albertobsd/keyhunt tests/unsolvedpuzzles.txt
    (line N -> puzzle N+66; verified against btcpuzzle.info for #71/72/73)

Puzzle N's private key lies in [2^(N-1), 2^N - 1].
"""

# Addresses for puzzles 71-150 (source: keyhunt unsolvedpuzzles.txt).
# Some of these (75, 80, 85, ... 130) have since been solved by the
# community pool — that's fine, the address itself doesn't change.
_ADDRESSES_71_150 = {
    71: '1PWo3JeB9jrGwfHDNpdGK54CRas7fsVzXU',
    72: '1JTK7s9YVYywfm5XUH7RNhHJH1LshCaRFR',
    73: '12VVRNPi4SJqUTsp6FmqDqY5sGosDtysn4',
    74: '1FWGcVDK3JGzCC3WtkYetULPszMaK2Jksv',
    75: '1DJh2eHFYQfACPmrvpyWc8MSTYKh7w9eRF',
    76: '1Bxk4CQdqL9p22JEtDfdXMsng1XacifUtE',
    77: '15qF6X51huDjqTmF9BJgxXdt1xcj46Jmhb',
    78: '1ARk8HWJMn8js8tQmGUJeQHjSE7KRkn2t8',
    79: '15qsCm78whspNQFydGJQk5rexzxTQopnHZ',
    80: '13zYrYhhJxp6Ui1VV7pqa5WDhNWM45ARAC',
    81: '14MdEb4eFcT3MVG5sPFG4jGLuHJSnt1Dk2',
    82: '1CMq3SvFcVEcpLMuuH8PUcNiqsK1oicG2D',
    83: '1K3x5L6G57Y494fDqBfrojD28UJv4s5JcK',
    84: '1PxH3K1Shdjb7gSEoTX7UPDZ6SH4qGPrvq',
    85: '16AbnZjZZipwHMkYKBSfswGWKDmXHjEpSf',
    86: '19QciEHbGVNY4hrhfKXmcBBCrJSBZ6TaVt',
    87: '1EzVHtmbN4fs4MiNk3ppEnKKhsmXYJ4s74',
    88: '1AE8NzzgKE7Yhz7BWtAcAAxiFMbPo82NB5',
    89: '17Q7tuG2JwFFU9rXVj3uZqRtioH3mx2Jad',
    90: '1K6xGMUbs6ZTXBnhw1pippqwK6wjBWtNpL',
    91: '15ANYzzCp5BFHcCnVFzXqyibpzgPLWaD8b',
    92: '18ywPwj39nGjqBrQJSzZVq2izR12MDpDr8',
    93: '1CaBVPrwUxbQYYswu32w7Mj4HR4maNoJSX',
    94: '1JWnE6p6UN7ZJBN7TtcbNDoRcjFtuDWoNL',
    95: '1CKCVdbDJasYmhswB6HKZHEAnNaDpK7W4n',
    96: '1PXv28YxmYMaB8zxrKeZBW8dt2HK7RkRPX',
    97: '1AcAmB6jmtU6AiEcXkmiNE9TNVPsj9DULf',
    98: '1EQJvpsmhazYCcKX5Au6AZmZKRnzarMVZu',
    99: '18KsfuHuzQaBTNLASyj15hy4LuqPUo1FNB',
    100: '15EJFC5ZTs9nhsdvSUeBXjLAuYq3SWaxTc',
    101: '1HB1iKUqeffnVsvQsbpC6dNi1XKbyNuqao',
    102: '1GvgAXVCbA8FBjXfWiAms4ytFeJcKsoyhL',
    103: '1824ZJQ7nKJ9QFTRBqn7z7dHV5EGpzUpH3',
    104: '18A7NA9FTsnJxWgkoFfPAFbQzuQxpRtCos',
    105: '1NeGn21dUDDeqFQ63xb2SpgUuXuBLA4WT4',
    106: '174SNxfqpdMGYy5YQcfLbSTK3MRNZEePoy',
    107: '1MnJ6hdhvK37VLmqcdEwqC3iFxyWH2PHUV',
    108: '1KNRfGWw7Q9Rmwsc6NT5zsdvEb9M2Wkj5Z',
    109: '1PJZPzvGX19a7twf5HyD2VvNiPdHLzm9F6',
    110: '1GuBBhf61rnvRe4K8zu8vdQB3kHzwFqSy7',
    111: '1GDSuiThEV64c166LUFC9uDcVdGjqkxKyh',
    112: '1Me3ASYt5JCTAK2XaC32RMeH34PdprrfDx',
    113: '1CdufMQL892A69KXgv6UNBD17ywWqYpKut',
    114: '1BkkGsX9ZM6iwL3zbqs7HWBV7SvosR6m8N',
    115: '1PXAyUB8ZoH3WD8n5zoAthYjN15yN5CVq5',
    116: '1AWCLZAjKbV1P7AHvaPNCKiB7ZWVDMxFiz',
    117: '1G6EFyBRU86sThN3SSt3GrHu1sA7w7nzi4',
    118: '1MZ2L1gFrCtkkn6DnTT2e4PFUTHw9gNwaj',
    119: '1Hz3uv3nNZzBVMXLGadCucgjiCs5W9vaGz',
    120: '1Fo65aKq8s8iquMt6weF1rku1moWVEd5Ua',
    121: '16zRPnT8znwq42q7XeMkZUhb1bKqgRogyy',
    122: '1KrU4dHE5WrW8rhWDsTRjR21r8t3dsrS3R',
    123: '17uDfp5r4n441xkgLFmhNoSW1KWp6xVLD',
    124: '13A3JrvXmvg5w9XGvyyR4JEJqiLz8ZySY3',
    125: '16RGFo6hjq9ym6Pj7N5H7L1NR1rVPJyw2v',
    126: '1UDHPdovvR985NrWSkdWQDEQ1xuRiTALq',
    127: '15nf31J46iLuK1ZkTnqHo7WgN5cARFK3RA',
    128: '1Ab4vzG6wEQBDNQM1B2bvUz4fqXXdFk2WT',
    129: '1Fz63c775VV9fNyj25d9Xfw3YHE6sKCxbt',
    130: '1QKBaU6WAeycb3DbKbLBkX7vJiaS8r42Xo',
    131: '1CD91Vm97mLQvXhrnoMChhJx4TP9MaQkJo',
    132: '15MnK2jXPqTMURX4xC3h4mAZxyCcaWWEDD',
    133: '13N66gCzWWHEZBxhVxG18P8wyjEWF9Yoi1',
    134: '1NevxKDYuDcCh1ZMMi6ftmWwGrZKC6j7Ux',
    135: '19GpszRNUej5yYqxXoLnbZWKew3KdVLkXg',
    136: '1M7ipcdYHey2Y5RZM34MBbpugghmjaV89P',
    137: '18aNhurEAJsw6BAgtANpexk5ob1aGTwSeL',
    138: '1FwZXt6EpRT7Fkndzv6K4b4DFoT4trbMrV',
    139: '1CXvTzR6qv8wJ7eprzUKeWxyGcHwDYP1i2',
    140: '1MUJSJYtGPVGkBCTqGspnxyHahpt5Te8jy',
    141: '13Q84TNNvgcL3HJiqQPvyBb9m4hxjS3jkV',
    142: '1LuUHyrQr8PKSvbcY1v1PiuGuqFjWpDumN',
    143: '18192XpzzdDi2K11QVHR7td2HcPS6Qs5vg',
    144: '1NgVmsCCJaKLzGyKLFJfVequnFW9ZvnMLN',
    145: '1AoeP37TmHdFh8uN72fu9AqgtLrUwcv2wJ',
    146: '1FTpAbQa4h8trvhQXjXnmNhqdiGBd1oraE',
    147: '14JHoRAdmJg3XR4RjMDh6Wed6ft6hzbQe9',
    148: '19z6waranEf8CcP8FqNgdwUe1QRxvUNKBG',
    149: '14u4nA5sugaswb6SZgn5av2vuChdMnD9E5',
    150: '1NBC8uXJy1GiJ6drkiZa1WuKn51ps7EPTv',
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
        raise KeyError(
            f"No known address for puzzle #{n}. "
            f"Known range: {min(PUZZLE_ADDRESSES)}-{max(PUZZLE_ADDRESSES)}"
        )
    lo, hi = puzzle_range(n)
    return {'addr': PUZZLE_ADDRESSES[n], 'start': lo, 'end': hi}


def all_puzzle_numbers() -> list:
    return sorted(PUZZLE_ADDRESSES.keys())


def is_known(n: int) -> bool:
    return n in PUZZLE_ADDRESSES
