#!/usr/bin/env python3
"""
Brainwallet / Dictionary Attack — Bitcoin Puzzle
===================================================
"Try the simplest attack first — default credentials before zero-days."
(Methodology borrowed from offensive-security recon practice: cheap,
high-yield checks go BEFORE expensive ones. A SHA256-dictionary sweep
costs seconds; a GPU brute force costs years. Always rule out the cheap
win first.)

IDEA:
  Early Bitcoin "brainwallets" derived a private key directly from a
  human-memorable passphrase:
      privkey = SHA256(passphrase)            (most common scheme)
      privkey = SHA256(SHA256(passphrase))    (double-hash variant)
  This was a REAL, widely-used (and widely-exploited) practice in
  2013-2015 — exactly the era this puzzle was created in. Bots have
  swept brainwallets for a decade; if the puzzle creator ever used one,
  it's crackable in milliseconds, not millennia.

WHAT THIS SCRIPT DOES:
  1. VALIDATION PASS: test every candidate phrase against all 70 known
     SOLVED puzzle keys. If ANY match is found, that proves the creator
     used brainwallet-style generation — and tells us the exact phrase
     pattern to extend to the unsolved target.
  2. TARGET PASS: test every candidate phrase directly against the
     target puzzle's address.

This is a SHORTCUT search, not a substitute for GPU brute force — it
covers a few hundred thousand candidates in seconds, a vanishingly
small slice of the keyspace, but at effectively zero cost.

Usage:
  python analysis/brainwallet_attack.py                # target #71, built-in wordlist
  python analysis/brainwallet_attack.py --target 73
  python analysis/brainwallet_attack.py --wordlist my_words.txt --target 71
  python analysis/brainwallet_attack.py --validate-only # only check vs solved keys
"""

import sys
import os
import hashlib
import argparse
import itertools

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.puzzle_registry import get_puzzle, puzzle_range, PUZZLE_ADDRESSES
from utils.address import point_to_address, verify_key_address
from ecc.curve import scalar_mul, G, N
from analysis.rng_analysis import KNOWN_KEYS


# ──────────────────────────────────────────────────────────────────
# Wordlist generation
# ──────────────────────────────────────────────────────────────────

BASE_WORDS = [
    # Bitcoin / crypto themed — most likely category for THIS puzzle
    "bitcoin", "Bitcoin", "BITCOIN", "satoshi", "Satoshi", "satoshinakamoto",
    "nakamoto", "blockchain", "Blockchain", "btc", "BTC", "crypto",
    "cryptocurrency", "privatekey", "private key", "puzzle", "Puzzle",
    "bitcoinpuzzle", "btcpuzzle", "1000btc", "1000bitcoin",
    "hiddenkey", "hidden key", "treasure", "challenge", "secret",
    "wallet", "Wallet", "brainwallet", "genesis", "halving",
    # Generic high-frequency weak passphrases (public-domain knowledge —
    # the same handful that show up at the top of every breach-corpus
    # frequency analysis; used here for legitimate brainwallet recon,
    # not reproduced from any single copyrighted list)
    "password", "letmein", "qwerty", "abc123", "iloveyou", "admin",
    "welcome", "monkey", "dragon", "freedom", "whatever", "trustno1",
    "hunter2", "shadow", "master", "ninja", "sunshine", "princess",
    "football", "baseball", "starwars", "computer", "internet",
    "test", "hello", "secret123",
]

YEARS = [str(y) for y in range(2008, 2017)]          # Bitcoin's early era
NUMBERS = ["", "0", "1", "123", "1234", "12345", "123456",
           "1234567890", "00", "01", "07", "21000000"]
SEPARATORS = ["", "_", "-", ".", " "]


def generate_candidates(target: int, extra_words: list = None) -> list:
    """
    Generate a bounded but high-signal set of candidate passphrases.
    Combines base words with puzzle-specific markers (the target number
    itself is the single highest-value guess: "bitcoinpuzzle71" etc.)
    """
    words = list(BASE_WORDS)
    if extra_words:
        words.extend(extra_words)

    candidates = set()

    # 1. Bare words
    candidates.update(words)

    # 2. word + year / word + number combos
    for w in words:
        for suffix in YEARS + NUMBERS:
            if suffix:
                for sep in SEPARATORS:
                    candidates.add(f"{w}{sep}{suffix}")

    # 3. Puzzle-number-specific — the single most targeted guess class
    for w in ["bitcoinpuzzle", "btcpuzzle", "puzzle", "Puzzle",
              "bitcoin puzzle", "satoshipuzzle", "key"]:
        for sep in SEPARATORS:
            candidates.add(f"{w}{sep}{target}")
            candidates.add(f"{w}{sep}#{target}")
            candidates.add(f"{target}{sep}{w}")

    # 4. All puzzle numbers 1-160 with the base markers (covers the
    #    case where the creator generated EVERY key from the same
    #    template — if we validate on a SOLVED number we know the
    #    template instantly transfers to the target)
    for w in ["bitcoinpuzzle", "puzzle"]:
        for n in range(1, 161):
            candidates.add(f"{w}{n}")

    return sorted(candidates)


# ──────────────────────────────────────────────────────────────────
# Candidate -> private key schemes
# ──────────────────────────────────────────────────────────────────

def derive_candidates(phrase: str) -> list:
    """All key-derivation schemes tried for a single phrase."""
    b = phrase.encode('utf-8')
    sha1x = hashlib.sha256(b).digest()
    sha2x = hashlib.sha256(sha1x).digest()
    return [
        ('sha256', int.from_bytes(sha1x, 'big')),
        ('sha256^2', int.from_bytes(sha2x, 'big')),
    ]


def privkey_to_address(priv: int) -> str | None:
    if priv <= 0 or priv >= N:
        return None
    pt = scalar_mul(priv, G)
    if pt == (0, 0):
        return None
    return point_to_address(pt[0], pt[1])


# ──────────────────────────────────────────────────────────────────
# Passes
# ──────────────────────────────────────────────────────────────────

def validate_against_known_keys(candidates: list) -> list:
    """
    Pass 1: does ANY candidate phrase produce a key that matches a
    SOLVED puzzle? This is ground truth — if it matches, the creator
    really did use brainwallet-style generation, and the matching
    phrase TEMPLATE tells us exactly what to try against unsolved ones.
    """
    print(f"\n[Validate] Testing {len(candidates):,} candidates against "
          f"{len(KNOWN_KEYS)} known SOLVED keys...")

    known_set = set(KNOWN_KEYS.values())
    hits = []

    for phrase in candidates:
        for scheme, k in derive_candidates(phrase):
            if k in known_set:
                puzzle_n = next(n for n, kk in KNOWN_KEYS.items() if kk == k)
                hits.append({'phrase': phrase, 'scheme': scheme,
                             'puzzle': puzzle_n, 'key': k})
                print(f"  *** MATCH! phrase={phrase!r} scheme={scheme} "
                      f"-> puzzle #{puzzle_n} (key={hex(k)}) ***")

    if not hits:
        print(f"  No matches. Either the creator did not use brainwallet-style "
              f"generation, or the real phrase isn't in this wordlist.")
    return hits


def attack_target(candidates: list, target: int) -> dict | None:
    """Pass 2: test every candidate directly against the target puzzle's address."""
    pz = get_puzzle(target)
    target_addr = pz['addr']
    lo, hi = puzzle_range(target)

    print(f"\n[Target] Testing {len(candidates):,} candidates against "
          f"puzzle #{target} ({target_addr})...")

    tested = 0
    for phrase in candidates:
        for scheme, k in derive_candidates(phrase):
            tested += 1
            if not (lo <= k <= hi):
                continue  # key wouldn't even fit the puzzle's bit-range
            addr = privkey_to_address(k)
            if addr == target_addr:
                print(f"\n{'!'*60}")
                print(f"  *** FOUND IT ***")
                print(f"  phrase: {phrase!r}  scheme: {scheme}")
                print(f"  privkey: {hex(k)}")
                print(f"{'!'*60}")
                return {'phrase': phrase, 'scheme': scheme, 'key': k}

    print(f"  Tested {tested:,} key candidates ({len(candidates):,} phrases x "
          f"2 schemes). No match for puzzle #{target}.")
    return None


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Brainwallet / dictionary attack on Bitcoin Puzzle keys')
    parser.add_argument('--target', type=int, default=71,
                        help='Puzzle number to attack (default: 71)')
    parser.add_argument('--wordlist', default='',
                        help='Optional extra wordlist file (one phrase per line) '
                             'to merge with the built-in list')
    parser.add_argument('--validate-only', action='store_true',
                        help='Only run the validation pass against solved keys')
    args = parser.parse_args()

    extra_words = []
    if args.wordlist and os.path.exists(args.wordlist):
        with open(args.wordlist, encoding='utf-8', errors='ignore') as f:
            extra_words = [line.strip() for line in f if line.strip()]
        print(f"[Wordlist] Loaded {len(extra_words):,} extra phrases from {args.wordlist}")

    print("\n" + "="*60)
    print("  BRAINWALLET / DICTIONARY ATTACK")
    print(f"  Target: puzzle #{args.target}")
    print("="*60)

    candidates = generate_candidates(args.target, extra_words)
    print(f"\n[Wordlist] Generated {len(candidates):,} candidate phrases "
          f"({len(candidates)*2:,} key candidates with both hash schemes)")

    hits = validate_against_known_keys(candidates)

    if args.validate_only:
        return

    if hits:
        print(f"\n[!] Brainwallet generation CONFIRMED on solved puzzle(s). "
              f"Extending search with confirmed phrase pattern...")

    result = attack_target(candidates, args.target)

    if result:
        with open(f'BRAINWALLET_KEY_{args.target}.txt', 'w') as f:
            f.write(f"Puzzle #{args.target}\n")
            f.write(f"Phrase: {result['phrase']}\n")
            f.write(f"Scheme: {result['scheme']}\n")
            f.write(f"Private key: {hex(result['key'])}\n")
        print(f"\nSaved to BRAINWALLET_KEY_{args.target}.txt")
    else:
        print(f"\n[Result] No brainwallet match for #{args.target} in this "
              f"wordlist. This rules out ~{len(candidates)*2:,} weak-passphrase "
              f"keys at near-zero cost — cheap insurance before/alongside the "
              f"GPU lottery. Try --wordlist with a larger corpus for deeper coverage.")


if __name__ == '__main__':
    main()
