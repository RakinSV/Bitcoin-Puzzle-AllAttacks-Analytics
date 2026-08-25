#!/usr/bin/env python3
"""
BUILD SWEEP TX — ready-to-paste Bitcoin Core commands for an offline machine.

Produces the three commands that move a puzzle prize, with every txid, vout,
scriptPubKey and amount already filled in, so the offline machine needs no
network and no explorer:

    createrawtransaction  ->  decoderawtransaction  ->  signrawtransactionwithkey

The private key is passed to signrawtransactionwithkey directly and never
imported into a wallet, so nothing persists in wallet.dat.

WHY THE INPUT LIST IS NOT SIMPLY "EVERYTHING"
---------------------------------------------
The usual advice is to sweep every output, because whatever is left behind is
free for anyone once the spending transaction publishes the public key. That is
right for the real money and wrong for the dust, and #71 shows why: it carries 59
outputs, and while the top three are 6.39, 0.639 and 0.071 BTC, the tail includes
outputs of 546, 272, 2 and even 1 satoshi.

Each P2PKH input costs ~148 vB to spend. At 20 sat/vB that is 2,960 sat of fee to
recover an output that may hold 1 sat. Sweeping all 59 there costs ~133,000 sat
MORE in fees than the dust it rescues -- you would be paying five figures of
satoshi to deny a bot four hundred.

So inputs are selected by whether they pay for themselves at the chosen fee rate.
Everything excluded is listed explicitly with its value, so the decision is
visible rather than silent. --all overrides this if denying the bots is worth
more to you than the arithmetic.

Usage:
  python analysis/build_sweep_tx.py --puzzle 71 --dest bc1q... --fee-rate 20
  python analysis/build_sweep_tx.py --puzzle 71 --dest bc1q... --all
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.puzzle_registry import PUZZLE_ADDRESSES
from analysis.utxo_snapshot import fetch_utxos, expected_script_pubkey

# Legacy P2PKH sizes. An input is signature + pubkey + outpoint; a P2WPKH output
# is 31 vB, a P2PKH one 34 -- 34 is used so the estimate never runs short.
VB_PER_INPUT = 148
VB_PER_OUTPUT = 34
VB_OVERHEAD = 10


def select_inputs(utxos, fee_rate, take_all=False):
    """Split UTXOs into those worth spending at this fee rate, and the rest."""
    cost = VB_PER_INPUT * fee_rate
    if take_all:
        return list(utxos), []
    keep = [u for u in utxos if (u.get('value_sat') or 0) > cost]
    skip = [u for u in utxos if (u.get('value_sat') or 0) <= cost]
    return keep, skip


def build(n, dest, fee_rate, take_all=False, wif=None):
    address = PUZZLE_ADDRESSES.get(n)
    if not address:
        raise SystemExit("no address on record for puzzle #%d" % n)

    utxos = fetch_utxos(address)
    if not utxos:
        raise SystemExit("could not read UTXOs (offline?) -- run "
                         "analysis/utxo_snapshot.py first")

    keep, skip = select_inputs(utxos, fee_rate, take_all)
    if not keep:
        raise SystemExit("no output pays for its own fee at %d sat/vB" % fee_rate)

    vsize = len(keep) * VB_PER_INPUT + VB_PER_OUTPUT + VB_OVERHEAD
    fee = vsize * fee_rate
    total_in = sum(u['value_sat'] for u in keep)
    send = total_in - fee
    if send <= 0:
        raise SystemExit("fee (%d sat) exceeds the selected inputs (%d sat)"
                         % (fee, total_in))

    script = expected_script_pubkey(address)
    inputs = [{"txid": u['txid'], "vout": u['vout']} for u in keep]
    prevtxs = [{"txid": u['txid'], "vout": u['vout'],
                "scriptPubKey": script,
                "amount": round(u['value_sat'] / 1e8, 8)} for u in keep]
    outputs = {dest: round(send / 1e8, 8)}

    L = []
    A = L.append
    A("# " + "=" * 68)
    A("# SWEEP PUZZLE #%d  ->  %s" % (n, dest))
    A("# generated %s UTC" % time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime()))
    A("# " + "=" * 68)
    A("#")
    A("# source address : %s" % address)
    A("# outputs found  : %d   (total %.8f BTC)"
      % (len(utxos), sum(u['value_sat'] for u in utxos) / 1e8))
    A("# inputs used    : %d   (total %.8f BTC)" % (len(keep), total_in / 1e8))
    A("# est. size      : ~%s vB" % f"{vsize:,}")
    A("# fee rate       : %d sat/vB" % fee_rate)
    A("# fee            : %s sat  (%.8f BTC)" % (f"{fee:,}", fee / 1e8))
    A("# YOU RECEIVE    : %.8f BTC" % (send / 1e8))
    A("#")
    if skip:
        lost = sum(u['value_sat'] for u in skip)
        extra = len(skip) * VB_PER_INPUT * fee_rate
        A("# SKIPPED %d output(s) holding %s sat in total." % (len(skip), f"{lost:,}"))
        A("# Adding them would cost ~%s sat in extra fees to recover %s sat,"
          % (f"{extra:,}", f"{lost:,}"))
        A("# i.e. %s sat WORSE off. They become claimable by anyone once this"
          % f"{extra - lost:,}")
        A("# transaction publishes the public key. Use --all to take them anyway.")
        for u in sorted(skip, key=lambda x: -(x['value_sat'] or 0))[:8]:
            A("#   %s sat  %s:%s" % (str(u['value_sat']).rjust(8),
                                     u['txid'][:20] + '...', u['vout']))
        if len(skip) > 8:
            A("#   ... and %d more" % (len(skip) - 8))
        A("#")
    A("# Run bitcoind with no peers:")
    A("#   bitcoind -connect=0 -listen=0 -maxconnections=0")
    A("# " + "=" * 68)
    A("")
    A("# --- 1. build the unsigned transaction ---------------------------------")
    A("bitcoin-cli createrawtransaction \\")
    A("  '%s' \\" % json.dumps(inputs, separators=(',', ':')))
    A("  '%s'" % json.dumps(outputs, separators=(',', ':')))
    A("")
    A("# --- 2. READ IT BACK before signing ------------------------------------")
    A("# Confirm the destination and the amount with your own eyes.")
    A("bitcoin-cli decoderawtransaction \"<HEX_FROM_STEP_1>\"")
    A("")
    A("# --- 3. sign with the key, without importing it ------------------------")
    A("# The key is passed inline; it never enters wallet.dat.")
    A("bitcoin-cli signrawtransactionwithkey \"<HEX_FROM_STEP_1>\" \\")
    A("  '[\"%s\"]' \\" % (wif or "<WIF_FROM_FOUND_KEY.txt>"))
    A("  '%s'" % json.dumps(prevtxs, separators=(',', ':')))
    A("")
    A("# --- 4. broadcast (ONLINE machine) -------------------------------------")
    A("# The signed hex is safe to carry out; it no longer contains the key,")
    A("# but it DOES expose the public key the moment it is seen. Prefer a")
    A("# private relay so it is mined rather than front-run:")
    A("#   https://slipstream.mara.com")
    A("# or:  bitcoin-cli sendrawtransaction \"<SIGNED_HEX>\"")
    A("")
    A("# " + "=" * 68)
    A("# Re-check balances before using this: donations still arrive, and any")
    A("# new output not listed here will be left behind.")
    return "\n".join(L), {'inputs': len(keep), 'skipped': len(skip),
                          'fee': fee, 'send': send, 'vsize': vsize}


def main():
    ap = argparse.ArgumentParser(description="Generate offline sweep commands")
    ap.add_argument('--puzzle', type=int, required=True)
    ap.add_argument('--dest', required=True,
                    help="YOUR receiving address (bc1q... or 1...)")
    ap.add_argument('--fee-rate', type=int, default=20,
                    help="sat/vB (default 20; check mempool.space when spending)")
    ap.add_argument('--all', action='store_true', dest='take_all',
                    help="include dust that costs more to spend than it holds")
    ap.add_argument('--wif', help="embed the key (default: leave a placeholder)")
    ap.add_argument('--out')
    args = ap.parse_args()

    text, info = build(args.puzzle, args.dest, args.fee_rate,
                       args.take_all, args.wif)
    path = args.out or os.path.join(os.path.dirname(__file__), '..',
                                    'SWEEP_puzzle%d.sh' % args.puzzle)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text + "\n")
        f.flush()
        os.fsync(f.fileno())

    print("=" * 66)
    print("  SWEEP SCRIPT FOR PUZZLE #%d" % args.puzzle)
    print("=" * 66)
    print("  inputs used : %d   skipped as dust: %d"
          % (info['inputs'], info['skipped']))
    print("  est. size   : ~%s vB   fee: %s sat" % (f"{info['vsize']:,}",
                                                    f"{info['fee']:,}"))
    print("  you receive : %.8f BTC" % (info['send'] / 1e8))
    print("  written     : %s" % os.path.basename(path))
    if not args.wif:
        print("\n  The key is a placeholder. Paste the WIF from FOUND_KEY.txt on")
        print("  the offline machine -- it does not need to travel on the stick.")
    print("=" * 66)


if __name__ == '__main__':
    main()
