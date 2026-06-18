#!/usr/bin/env python3
"""
Bitcoin Puzzle Public Key Monitor.

Watches puzzle address on the blockchain. If a spending transaction appears,
the public key becomes visible in the scriptSig and Pollard's Kangaroo can
solve the puzzle in ~90 seconds instead of ~98,000 years.

Usage:
  python monitor.py                  # monitor puzzle #71 (default)
  python monitor.py --puzzle 71      # explicit
  python monitor.py --interval 60    # check every 60s (default 300s)
  python monitor.py --once           # check once and exit

When a pubkey is found:
  - Saves to pubkey_found.txt
  - Prints the Kangaroo command to run
"""

import sys
import os
import time
import argparse
import json
import struct
import hashlib

sys.path.insert(0, os.path.dirname(__file__))

from main import PUZZLES

# ---------------------------------------------------------------------------
# API helpers (no external deps - uses urllib from stdlib)
# ---------------------------------------------------------------------------

def _get(url: str, timeout: int = 15) -> dict | None:
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'btc-puzzle-monitor/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  [net] {e}")
        return None


def get_address_info(address: str) -> dict | None:
    """Fetch address info from Blockstream API."""
    url = f"https://blockstream.info/api/address/{address}"
    return _get(url)


def get_spent_txo_count(address: str) -> int:
    """
    Lightweight check: returns spent_txo_count only (one tiny API call).
    Fast polling — only does full investigation when count > 0.
    """
    info = get_address_info(address)
    if info is None:
        return -1
    return info.get('chain_stats', {}).get('spent_txo_count', 0)


def get_address_txs(address: str) -> list | None:
    """Fetch recent transactions for address."""
    url = f"https://blockstream.info/api/address/{address}/txs"
    data = _get(url)
    return data if isinstance(data, list) else None


def get_tx(txid: str) -> dict | None:
    url = f"https://blockstream.info/api/tx/{txid}"
    return _get(url)


# ---------------------------------------------------------------------------
# Public key extraction
# ---------------------------------------------------------------------------

def extract_pubkey_from_scriptsig(scriptsig_hex: str) -> bytes | None:
    """Extract compressed or uncompressed public key from P2PKH scriptSig.

    P2PKH scriptSig format: <sig_len> <DER_sig> <pubkey_len> <pubkey>
    """
    try:
        data = bytes.fromhex(scriptsig_hex)
        pos = 0
        # Skip signature
        if pos >= len(data):
            return None
        sig_len = data[pos]
        pos += 1 + sig_len
        if pos >= len(data):
            return None
        # Read pubkey
        pk_len = data[pos]
        pos += 1
        if pk_len not in (33, 65):   # compressed or uncompressed
            return None
        pubkey = data[pos:pos + pk_len]
        if len(pubkey) != pk_len:
            return None
        # Validate prefix
        if pk_len == 33 and pubkey[0] not in (0x02, 0x03):
            return None
        if pk_len == 65 and pubkey[0] != 0x04:
            return None
        return pubkey
    except Exception:
        return None


def pubkey_to_address(pubkey: bytes) -> str:
    sha256_hash = hashlib.sha256(pubkey).digest()
    ripemd160   = hashlib.new('ripemd160', sha256_hash).digest()
    payload     = b'\x00' + ripemd160
    checksum    = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    full        = payload + checksum
    # Base58Check encode
    alphabet    = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    n           = int.from_bytes(full, 'big')
    result      = ''
    while n:
        n, r = divmod(n, 58)
        result = alphabet[r] + result
    for byte in full:
        if byte == 0:
            result = '1' + result
        else:
            break
    return result


def verify_pubkey(pubkey: bytes, expected_address: str) -> bool:
    return pubkey_to_address(pubkey) == expected_address


# ---------------------------------------------------------------------------
# Main monitor loop
# ---------------------------------------------------------------------------

def check_puzzle(puzzle_num: int, address: str) -> bytes | None:
    """Check if the puzzle address has been spent. Returns pubkey bytes or None."""
    print(f"  Checking puzzle #{puzzle_num}: {address}")

    txs = get_address_txs(address)
    if txs is None:
        print("  [!] API error, skipping.")
        return None

    if not txs:
        print("  [OK] No transactions - address unspent (pubkey unknown)")
        return None

    print(f"  [!] {len(txs)} transaction(s) found!")
    for tx in txs:
        txid = tx.get('txid', '')
        print(f"  TX: {txid}")

        # Check inputs for a spending tx
        for inp in tx.get('vin', []):
            prevout = inp.get('prevout', {})
            if prevout.get('scriptpubkey_address') == address:
                # This input spends from our address
                scriptsig = inp.get('scriptsig', '')
                witness   = inp.get('witness', [])

                # Try scriptSig (legacy P2PKH)
                if scriptsig:
                    pk = extract_pubkey_from_scriptsig(scriptsig)
                    if pk and verify_pubkey(pk, address):
                        print(f"  [!!] PUBLIC KEY FOUND in scriptSig!")
                        return pk

                # Try witness (P2WPKH)
                for item in witness:
                    try:
                        pk_bytes = bytes.fromhex(item)
                        if len(pk_bytes) in (33, 65) and verify_pubkey(pk_bytes, address):
                            print(f"  [!!] PUBLIC KEY FOUND in witness!")
                            return pk_bytes
                    except Exception:
                        continue

    print("  Transactions found but no spending input from this address (not yet spent).")
    return None


def on_pubkey_found(puzzle_num: int, address: str, pubkey: bytes,
                    puzzle_start: int, puzzle_end: int,
                    autosolve: bool = False):
    """Handle discovery of the public key."""
    pk_hex = pubkey.hex()
    print(f"\n{'!'*60}")
    print(f"  PUZZLE #{puzzle_num} PUBLIC KEY DISCOVERED!")
    print(f"  Address:  {address}")
    print(f"  Pubkey:   {pk_hex}")
    print(f"{'!'*60}")

    # Save to file
    fname = f'pubkey_puzzle{puzzle_num}.txt'
    with open(fname, 'w') as f:
        f.write(f"Puzzle #{puzzle_num}\n")
        f.write(f"Address: {address}\n")
        f.write(f"Pubkey:  {pk_hex}\n")
        f.write(f"Range:   [{hex(puzzle_start)}, {hex(puzzle_end)}]\n")
        f.write(f"Found:   {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"\nKangaroo command:\n")
        f.write(f"  python main.py --puzzle {puzzle_num} --mode kangaroo "
                f"--pubkey {pk_hex}\n")
    print(f"  Saved to {fname}")

    # Show Kangaroo command
    rng_bits    = (puzzle_end - puzzle_start + 1).bit_length() - 1
    import math
    rng_size    = puzzle_end - puzzle_start + 1
    expected_s  = int(2.5 * math.sqrt(rng_size))
    # ETA with n_tame=n_wild=16384 (n_total=49152), dp_bits=15 on RX 6600 (~500 Mhops/s)
    # dp_bits=15: MIN required = ceil(log2(49152*2048/4096)) = 15  (0% overflow)
    # Detection overhead: after kangaroos collide, need 2^15/4 = 8192 kernel calls
    #   each call = n_total*STEPS_CALL = 49152*2048 = 100.7M hops
    #   overhead = 8192 * 100.7M ≈ 824.8B hops  → ~1650s at 500M/s
    _n_total    = 16384 + 16384 + 16384   # tame + wild + neg
    _dp_bits    = 15
    _steps_call = 2048
    _hops_call  = _n_total * _steps_call
    _n_dp_per   = _steps_call // 512      # = 4 DP checks per call
    _detect_hops = ((1 << _dp_bits) // _n_dp_per) * _hops_call
    _solve_s    = expected_s     / 500e6
    _detect_s   = _detect_hops   / 500e6
    _total_s    = _solve_s + _detect_s
    print(f"\n[NEXT STEP] Run Kangaroo GPU solver (~O(sqrt(2^{rng_bits})) = "
          f"~{expected_s:,} collision steps):")
    print(f"\n  # Optimal settings (RX 6600, expected ~{_total_s:.0f}s = {_total_s/60:.1f}min):")
    print(f"  python main.py --puzzle {puzzle_num} --mode kangaroo \\")
    print(f"                 --pubkey {pk_hex} \\")
    print(f"                 --n-tame 16384 --n-wild 16384 --dp-bits 15")

    if autosolve:
        print(f"\n[AUTO] Launching Kangaroo solver automatically...")
        import subprocess
        cmd = [
            sys.executable,
            os.path.join(os.path.dirname(__file__), 'main.py'),
            '--puzzle',  str(puzzle_num),
            '--mode',    'kangaroo',
            '--pubkey',  pk_hex,
            '--n-tame',  '16384',
            '--n-wild',  '16384',
            '--dp-bits', '15',
        ]
        print(f"  {' '.join(cmd)}\n")
        result = subprocess.run(cmd)
        sys.exit(result.returncode)


def monitor(puzzle_num: int = 71, interval: int = 30,
            once: bool = False, autosolve: bool = False,
            on_found_callback=None):
    """
    Monitor puzzle address.

    on_found_callback(pk_bytes) : if set, called instead of on_pubkey_found().
                                  Used by run_all.py for instant Kangaroo launch.
    interval : polling interval in seconds. Default 30s (was 300s).
               Uses lightweight spent_txo_count check — only ~1KB per request.
    """
    pz = PUZZLES[puzzle_num]
    address = pz['addr']
    k_start = pz['start']
    k_end   = pz['end']

    print(f"Bitcoin Puzzle #{puzzle_num} Public Key Monitor")
    print(f"Address:   {address}")
    print(f"Interval:  {interval}s  |  autosolve={'ON' if autosolve else 'OFF'}")
    print(f"Tip: run with --websocket for instant mempool detection")
    print(f"Press Ctrl+C to stop.\n")

    last_spent = 0

    while True:
        print(f"\r[{time.strftime('%H:%M:%S')}] Quick check...", end='', flush=True)

        # Fast check: only spent_txo_count (~200 bytes)
        spent = get_spent_txo_count(address)

        if spent < 0:
            print(f"\r[{time.strftime('%H:%M:%S')}] API unavailable, retry in {interval}s")
        elif spent > last_spent:
            print(f"\n[{time.strftime('%H:%M:%S')}] *** SPENT TXO COUNT CHANGED: {spent} ***")
            pk = check_puzzle(puzzle_num, address)
            if pk is not None:
                if on_found_callback:
                    on_found_callback(pk)
                    return
                on_pubkey_found(puzzle_num, address, pk, k_start, k_end,
                                autosolve=autosolve)
                sys.exit(0)
            last_spent = spent
        else:
            print(f"\r[{time.strftime('%H:%M:%S')}] Clean — no spending (spent={spent}). "
                  f"Next in {interval}s...", end='', flush=True)

        if once:
            break

        time.sleep(interval)


def monitor_websocket(puzzle_num: int = 71, on_found_callback=None,
                      fallback_interval: int = 30):
    """
    Real-time mempool monitoring via WebSocket (mempool.space API).
    Detects spending transaction INSTANTLY (< 1 second) vs 30s polling.
    Falls back to polling if websockets library not installed.

    Install: pip install websockets
    """
    try:
        import websockets
        import asyncio
    except ImportError:
        print("[Monitor] websockets not installed — falling back to polling.")
        print("          Install: pip install websockets")
        monitor(puzzle_num, interval=fallback_interval,
                on_found_callback=on_found_callback)
        return

    pz = PUZZLES[puzzle_num]
    address = pz['addr']
    k_start = pz['start']
    k_end   = pz['end']

    async def _ws_loop():
        uri = "wss://mempool.space/api/v1/ws"
        print(f"[Monitor-WS] Connecting to {uri}...")
        async with websockets.connect(uri) as ws:
            # Subscribe to address tracking
            await ws.send(json.dumps({"action": "want", "data": ["stats"]}))
            await ws.send(json.dumps({"track-address": address}))
            print(f"[Monitor-WS] Subscribed to {address}")
            print(f"[Monitor-WS] Waiting for mempool activity (INSTANT detection)...\n")

            while True:
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                except asyncio.TimeoutError:
                    # Keepalive ping
                    await ws.send(json.dumps({"action": "ping"}))
                    print(f"\r[Monitor-WS] [{time.strftime('%H:%M:%S')}] Alive...",
                          end='', flush=True)
                    continue

                # Address transaction event
                if 'address-transactions' in msg or 'txs' in msg:
                    print(f"\n[Monitor-WS] *** TRANSACTION DETECTED IN MEMPOOL! ***")
                    txs = msg.get('address-transactions', msg.get('txs', []))
                    for tx in txs:
                        for inp in tx.get('vin', []):
                            scriptsig = inp.get('scriptsig', '')
                            witness   = inp.get('witness', [])
                            if scriptsig:
                                pk = extract_pubkey_from_scriptsig(scriptsig)
                                if pk and verify_pubkey(pk, address):
                                    print(f"[Monitor-WS] PUBKEY IN MEMPOOL SCRIPTSIG!")
                                    if on_found_callback:
                                        on_found_callback(pk)
                                    else:
                                        on_pubkey_found(puzzle_num, address, pk,
                                                        k_start, k_end)
                                    return
                            for item in witness:
                                try:
                                    pk_b = bytes.fromhex(item)
                                    if len(pk_b) in (33, 65) and verify_pubkey(pk_b, address):
                                        print(f"[Monitor-WS] PUBKEY IN MEMPOOL WITNESS!")
                                        if on_found_callback:
                                            on_found_callback(pk_b)
                                        else:
                                            on_pubkey_found(puzzle_num, address, pk_b,
                                                            k_start, k_end)
                                        return
                                except Exception:
                                    continue

    asyncio.run(_ws_loop())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Bitcoin Puzzle Public Key Monitor')
    parser.add_argument('--puzzle',   type=int, default=71,
                        help='Puzzle number to monitor (default: 71)')
    parser.add_argument('--interval', type=int, default=30,
                        help='Check interval in seconds (default: 30)')
    parser.add_argument('--once',      action='store_true',
                        help='Check once and exit')
    parser.add_argument('--autosolve', action='store_true',
                        help='Auto-launch Kangaroo GPU solver when pubkey is found')
    parser.add_argument('--websocket', action='store_true',
                        help='Use WebSocket (mempool.space) for instant detection '
                             '(requires: pip install websockets)')
    args = parser.parse_args()

    if args.puzzle not in PUZZLES:
        print(f"Unknown puzzle #{args.puzzle}. Available: {sorted(PUZZLES.keys())}")
        sys.exit(1)

    if args.websocket:
        monitor_websocket(args.puzzle, fallback_interval=args.interval)
    else:
        monitor(args.puzzle, args.interval, args.once, args.autosolve)


if __name__ == '__main__':
    main()
