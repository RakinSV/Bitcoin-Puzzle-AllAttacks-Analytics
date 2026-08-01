#!/usr/bin/env python3
"""
CREATOR SIGNATURE ATTACK — the one math attack that ignores interval size.

The 6 unsolved puzzles with an exposed pubkey (#125-150) exposed it by SPENDING,
which means the creator produced real ECDSA signatures for those keys. If the
signing RNG ever repeated or biased a nonce k, the private key falls to algebra /
a lattice REGARDLESS of the 2^129 interval. That is the only way a big-reward
puzzle could be taken without astronomical compute.

Hypotheses, each checked independently:
  H1  exact nonce reuse  — same r on two signatures (same key OR two keys) -> solve
  H2  cross-key r-collision across ALL collected sigs
  H3  low/structured nonce — r or (r,s) unusually small / patterned
  H4  biased nonce via LLL — assume top B bits of k are 0, for B in {1..16}

Local research on public chain data. Run:
  python analysis/creator_sig_attack.py
"""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from ecc.curve import N
from utils.puzzle_registry import PUZZLE_ADDRESSES
from analysis.tx_parser import extract_sigs_from_tx
from analysis.pubkey_pattern import fetch_address_txs, fetch_tx

EXPOSED = [125, 130, 135, 140, 145, 150]


def collect():
    """Gather every ECDSA signature touching the exposed puzzle addresses."""
    sigs = []
    seen_tx = set()
    for n in EXPOSED:
        addr = PUZZLE_ADDRESSES[n]
        try:
            txs = fetch_address_txs(addr, limit=50)
        except Exception as e:
            print(f"  #{n} {addr}: fetch error {e}")
            continue
        cnt = 0
        for tx in txs or []:
            txid = tx.get('txid')
            if txid in seen_tx:
                continue
            seen_tx.add(txid)
            full = tx if tx.get('vin') and 'prevout' in (tx['vin'][0] or {}) else \
                (fetch_tx(txid) or tx)
            for s in extract_sigs_from_tx(full):
                s['puzzle'] = n
                sigs.append(s)
                cnt += 1
        print(f"  #{n} {addr}: {cnt} signatures from {len(txs or [])} txs")
    return sigs


def h1_h2_reuse(sigs):
    """Any two signatures sharing r -> recover the key(s)."""
    by_r = {}
    for s in sigs:
        if s.get('r') is None:
            continue
        by_r.setdefault(s['r'], []).append(s)
    hits = []
    for r, group in by_r.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if None in (a.get('z'), b.get('z'), a.get('s'), b.get('s')):
                    continue
                # same key path: k=(z1-z2)/(s1-s2), d=(s1*k - z1)/r
                ds = (a['s'] - b['s']) % N
                if ds == 0:
                    continue
                k = ((a['z'] - b['z']) * pow(ds, -1, N)) % N
                d = ((a['s'] * k - a['z']) * pow(r, -1, N)) % N
                hits.append((r, a['puzzle'], b['puzzle'], hex(d)))
    return hits


def h3_structured(sigs):
    """Flag suspiciously small / patterned r or s (weak nonce)."""
    flags = []
    for s in sigs:
        r, sv = s.get('r'), s.get('s')
        if r is None:
            continue
        if r < 2 ** 200 or (sv is not None and sv < 2 ** 200):
            flags.append((s['puzzle'], 'small r/s', r.bit_length()))
        # top bits all zero would show as a short bit length
    return flags


def h4_lll(sigs, bias_bits):
    """Biased-nonce lattice attack (needs several sigs from the SAME key)."""
    try:
        from analysis.nonce_attack import lll_attack
    except Exception:
        return None
    # group by pubkey; LLL needs multiple sigs under one key
    by_pk = {}
    for s in sigs:
        pk = s.get('pubkey_hex')
        if pk and None not in (s.get('r'), s.get('s'), s.get('z')):
            by_pk.setdefault(pk, []).append(s)
    for pk, group in by_pk.items():
        if len(group) >= 3:
            k = lll_attack(group, bias_bits=bias_bits)
            if k:
                return (pk, bias_bits, hex(k))
    return None


def main():
    print("=" * 74)
    print("  CREATOR SIGNATURE ATTACK — exposed puzzles #125-150")
    print("=" * 74)
    print("[collect] fetching signatures from the 6 exposed addresses...")
    sigs = collect()
    withz = [s for s in sigs if s.get('z') is not None]
    print(f"\n  collected {len(sigs)} signatures ({len(withz)} with a usable sighash z)")

    print("\n[H1/H2] nonce-reuse / cross-key r-collision:")
    hits = h1_h2_reuse(sigs)
    if hits:
        for r, p1, p2, d in hits:
            print(f"  *** REUSE r={hex(r)[:18]}.. between #{p1}/#{p2} -> key {d} ***")
    else:
        print("  no shared r among collected signatures.")

    print("\n[H3] structured / small nonce:")
    fl = h3_structured(sigs)
    print(f"  {fl if fl else 'no small/patterned r,s'}")

    print("\n[H4] LLL biased-nonce (needs >=3 sigs per key):")
    got = None
    for B in (1, 2, 4, 8, 12, 16):
        got = h4_lll(sigs, B)
        if got:
            print(f"  *** LLL recovered {got} ***")
            break
    if not got:
        # report why: how many sigs per key?
        from collections import Counter
        per = Counter(s.get('pubkey_hex') for s in sigs if s.get('pubkey_hex'))
        maxsigs = max(per.values()) if per else 0
        print(f"  no recovery — max signatures under any single key = {maxsigs} "
              f"(LLL needs >=3 from the SAME key).")

    print("=" * 74)
    print("  Any '***' above is a genuine break — verify the key vs the address.")
    print("=" * 74)


if __name__ == '__main__':
    main()
