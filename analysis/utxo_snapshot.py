#!/usr/bin/env python3
"""
UTXO SNAPSHOT — everything needed to spend a puzzle address, gathered in advance.

When a key is finally found the clock starts: the moment a spending transaction
hits the mempool it exposes the public key, and bots race to sweep whatever the
transaction leaves behind. That is the wrong moment to be querying an explorer,
picking through outputs and hoping the network is up.

So this collects it beforehand. For every unspent output of a puzzle address:

    txid, vout, value (sat and BTC), scriptPubKey (hex), confirmations

Puzzle addresses usually carry MORE THAN ONE output -- people have been adding
small donations for years -- and anything left unspent by the sweeping
transaction is free for the taking once the key is public. The snapshot lists
every one so none is missed.

Two safeguards worth knowing about:

  * scriptPubKey is DERIVED, not merely copied. A legacy P2PKH script is exactly
    76a914 <20-byte hash160> 88ac, and the hash160 comes from decoding the
    address itself. The value returned by the API is then compared against that.
    A silent mismatch would mean signing for the wrong script, so it is reported
    rather than trusted.
  * The snapshot records WHEN it was taken. Balances change; an old file is a
    starting point to re-verify, not gospel.

Reading a public address reveals nothing about you, and the puzzle addresses are
watched by thousands already. Still, if operational privacy matters to you, take
the snapshot from a different machine or over Tor -- this module only ever GETs.

Usage:
  python analysis/utxo_snapshot.py --puzzle 71
  python analysis/utxo_snapshot.py --puzzle 71 --out my_utxos.txt
"""
import argparse
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.address import decode_address_hash160
from utils.puzzle_registry import PUZZLE_ADDRESSES

UA = 'btc-puzzle-research/1.0'
TIMEOUT = 20
APIS = ('https://blockstream.info/api', 'https://mempool.space/api')


def _get_json(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode('utf-8', 'replace'))
    except Exception:
        return None


def expected_script_pubkey(address: str) -> str:
    """The P2PKH locking script this address must have, derived from the address.

    76a914 <hash160> 88ac  ==  OP_DUP OP_HASH160 <20 bytes> OP_EQUALVERIFY
                               OP_CHECKSIG
    Deriving beats trusting whatever an API hands back: signing against the wrong
    script produces a transaction that cannot spend.
    """
    h160 = decode_address_hash160(address).hex()
    return '76a914' + h160 + '88ac'


def fetch_utxos(address: str) -> list:
    """Every unspent output of `address`, with its script and confirmations."""
    data = None
    for base in APIS:
        data = _get_json('%s/address/%s/utxo' % (base, address))
        if data is not None:
            api = base
            break
    if data is None:
        return []

    tip = _get_json('%s/blocks/tip/height' % api)
    want = expected_script_pubkey(address)

    out = []
    for u in data:
        rec = {
            'txid': u.get('txid'),
            'vout': u.get('vout'),
            'value_sat': u.get('value'),
            'value_btc': (u.get('value') or 0) / 1e8,
            'script_pubkey': want,
            'script_source': 'derived-from-address',
        }
        st = u.get('status') or {}
        if st.get('block_height') and isinstance(tip, int):
            rec['block_height'] = st['block_height']
            rec['confirmations'] = tip - st['block_height'] + 1
        # Cross-check against the transaction's own copy of the script.
        tx = _get_json('%s/tx/%s' % (api, u.get('txid')))
        if tx:
            try:
                actual = tx['vout'][u['vout']].get('scriptpubkey')
            except Exception:
                actual = None
            if actual:
                rec['script_matches_chain'] = (actual.lower() == want)
                if actual.lower() != want:
                    rec['script_on_chain'] = actual
        time.sleep(0.1)
        out.append(rec)
    out.sort(key=lambda r: (-(r.get('value_sat') or 0), r.get('txid') or ''))
    return out


def render(n: int, address: str, utxos: list) -> str:
    total = sum(u.get('value_sat') or 0 for u in utxos)
    bad = [u for u in utxos if u.get('script_matches_chain') is False]
    lines = []
    lines.append("PUZZLE #%d -- UTXO SNAPSHOT" % n)
    lines.append("=" * 62)
    lines.append("address        : %s" % address)
    lines.append("taken at       : %s UTC" % time.strftime('%Y-%m-%d %H:%M:%S',
                                                           time.gmtime()))
    lines.append("outputs        : %d" % len(utxos))
    lines.append("total          : %.8f BTC  (%d sat)" % (total / 1e8, total))
    lines.append("scriptPubKey   : %s" % expected_script_pubkey(address))
    lines.append("                 (derived from the address: 76a914 <hash160> 88ac)")
    if bad:
        lines.append("")
        lines.append("!! %d output(s) carry a script that does NOT match the one" % len(bad))
        lines.append("!! derived from this address. Do not sign until resolved.")
    lines.append("")
    lines.append("SPEND EVERY OUTPUT BELOW IN ONE TRANSACTION.")
    lines.append("Anything left behind is claimable by anyone the moment the")
    lines.append("public key appears in the mempool.")
    lines.append("=" * 62)
    for i, u in enumerate(utxos, 1):
        lines.append("")
        lines.append("[%d] txid : %s" % (i, u['txid']))
        lines.append("    vout : %s" % u['vout'])
        lines.append("    value: %.8f BTC  (%s sat)"
                     % (u['value_btc'], u['value_sat']))
        lines.append("    script: %s" % u['script_pubkey'])
        if u.get('confirmations'):
            lines.append("    conf : %s  (block %s)"
                         % (u['confirmations'], u.get('block_height')))
        if u.get('script_matches_chain') is not None:
            lines.append("    check: on-chain script %s"
                         % ("matches" if u['script_matches_chain'] else "DIFFERS"))
    lines.append("")
    lines.append("=" * 62)
    lines.append("Balances change -- donations still arrive. Re-run this before")
    lines.append("building the transaction and reconcile against the chain.")
    return "\n".join(lines)


def snapshot(n: int, out_path: str = None, verbose: bool = True) -> str | None:
    """Write the snapshot; returns the path, or None if nothing could be read."""
    address = PUZZLE_ADDRESSES.get(n)
    if not address:
        if verbose:
            print("[utxo] no address on record for puzzle #%d" % n)
        return None
    utxos = fetch_utxos(address)
    if not utxos:
        if verbose:
            print("[utxo] no UTXO data for #%d (offline, or nothing unspent)" % n)
        return None
    text = render(n, address, utxos)
    path = out_path or os.path.join(os.path.dirname(__file__), '..',
                                    'UTXO_puzzle%d.txt' % n)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    if verbose:
        total = sum(u['value_sat'] for u in utxos)
        print("[utxo] #%d: %d output(s), %.8f BTC -> %s"
              % (n, len(utxos), total / 1e8, os.path.basename(path)))
    return path


def main():
    ap = argparse.ArgumentParser(description="Snapshot a puzzle address's UTXOs")
    ap.add_argument('--puzzle', type=int, required=True)
    ap.add_argument('--out')
    ap.add_argument('--print', action='store_true', dest='show')
    args = ap.parse_args()

    path = snapshot(args.puzzle, args.out)
    if path and args.show:
        print()
        with open(path, encoding='utf-8') as f:
            print(f.read())
    return 0 if path else 1


if __name__ == '__main__':
    sys.exit(main())
