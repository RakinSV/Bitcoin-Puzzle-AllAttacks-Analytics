"""
Pubkey Pattern Analysis — Bitcoin Puzzle Creator
=================================================
Эта атака НЕ требует приватных ключей!

Идея:
  Для решённых пазлов #1-66 их публичные ключи видны в spending TX.
  Если создатель использовал какой-то паттерн k_n = f(k_{n-1}),
  то между соседними EC-точками должен быть паттерн:

    K_n - K_{n-1} = (k_n - k_{n-1}) * G  = c * G

  где c = k_n - k_{n-1} — разность приватных ключей.

  Если разность c мала (< 2^60), Kangaroo решит это за секунды.
  Если c одинакова для всех n — нашли паттерн → предсказываем K_71.

Алгоритм:
  1. Фетчим funding TX (создал все пазлы) → все output addresses
  2. Для каждого адреса находим spending TX → scriptSig / witness → pubkey
  3. Строим список (puzzle_n, pubkey_n) для всех решённых пазлов
  4. Вычисляем разности Delta_n = K_n - K_{n-1}
  5. Проверяем: все Delta_n одинаковы? Нет - ищем мини-диапазон каждой
  6. Если паттерн найден - предсказываем K_71

Альтернативные паттерны проверяемые:
  a) Линейная: k_n = k_{n-1} + c     → Delta_n = c*G (const)
  b) BIP32 child: k_n = f(k_{n-1}, chain) → сложно без знания chain
  c) Позиционная: k_n / range_n = const  → нормализованные ключи
  d) Мультипликативная: k_n = r * k_{n-1} mod N
     → K_n = r * K_{n-1} → проверяем является ли K_n = scalar * K_{n-1}

Примечание:
  "Kangaroo на разностях" — если Delta_n = c*G для малого c,
  решаем ECDLP(Delta_n, G) за O(sqrt(range_n)) = секунды для малых n.
"""

import json
import sys
import time
import hashlib
from typing import Optional

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    print("[!] pip install requests — нужен для получения данных с blockchain")

# secp256k1
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
G  = (GX, GY)
INF = (0, 0)

# Funding TX (creates all puzzle outputs)
FUNDING_TX = '08389f34c98c606322740c0be6a7125d9860bb8d5cb182c02f98461e5fa6cd15'

# Known puzzle addresses (for cross-referencing)
# Derived from: puzzle n has value 2^(n-1) * 10000 satoshis (approx)
# The actual mapping is determined by the output values in the funding TX

# ──────────────────────────────────────────────────────────────────
# EC Math
# ──────────────────────────────────────────────────────────────────

def _inv(a: int) -> int:
    return pow(a, P - 2, P)

def ec_add(P1, P2):
    if P1 == INF: return P2
    if P2 == INF: return P1
    x1, y1 = P1
    x2, y2 = P2
    if x1 == x2:
        if y1 != y2: return INF
        # Doubling
        lam = (3 * x1 * x1 * _inv(2 * y1)) % P
    else:
        lam = ((y2 - y1) * _inv(x2 - x1)) % P
    x3 = (lam * lam - x1 - x2) % P
    y3 = (lam * (x1 - x3) - y1) % P
    return (x3, y3)

def ec_neg(pt):
    if pt == INF: return INF
    x, y = pt
    return (x, (-y) % P)

def ec_sub(P1, P2):
    return ec_add(P1, ec_neg(P2))

def scalar_mul(k: int, pt):
    if k == 0: return INF
    if k < 0: return scalar_mul(-k, ec_neg(pt))
    r = INF; add = pt
    while k:
        if k & 1: r = ec_add(r, add)
        add = ec_add(add, add)
        k >>= 1
    return r

def pubkey_from_hex(pk_hex: str) -> Optional[tuple]:
    """Parse compressed or uncompressed pubkey hex -> (x, y)."""
    try:
        b = bytes.fromhex(pk_hex)
        if len(b) == 65 and b[0] == 0x04:
            x = int.from_bytes(b[1:33], 'big')
            y = int.from_bytes(b[33:65], 'big')
            return (x, y)
        elif len(b) == 33 and b[0] in (0x02, 0x03):
            x = int.from_bytes(b[1:], 'big')
            y_sq = (pow(x, 3, P) + 7) % P
            y = pow(y_sq, (P + 1) // 4, P)
            if (y % 2) != (b[0] & 1):
                y = (-y) % P
            return (x, y)
    except Exception:
        pass
    return None

# ──────────────────────────────────────────────────────────────────
# Blockchain API
# ──────────────────────────────────────────────────────────────────

def fetch_tx(txid: str) -> Optional[dict]:
    url = f'https://blockstream.info/api/tx/{txid}'
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    # fallback
    try:
        r = requests.get(f'https://mempool.space/api/tx/{txid}', timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def fetch_address_txs(addr: str, limit: int = 10) -> list:
    """Get list of TX IDs for address (spending TXs)."""
    url = f'https://blockstream.info/api/address/{addr}/txs'
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return r.json()[:limit]
    except Exception:
        pass
    return []


def fetch_utxo(txid: str, vout: int) -> Optional[dict]:
    """Check if a UTXO is spent, and if so return the spending TX."""
    url = f'https://blockstream.info/api/tx/{txid}/outspend/{vout}'
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

# ──────────────────────────────────────────────────────────────────
# Pubkey extraction from TX
# ──────────────────────────────────────────────────────────────────

def extract_pubkey_from_input(inp: dict) -> Optional[str]:
    """Extract pubkey from a single TX input."""
    # P2PKH: scriptSig = <push sig> <push pubkey>
    scriptsig_hex = inp.get('scriptsig', '')
    if scriptsig_hex:
        try:
            data = bytes.fromhex(scriptsig_hex)
            pos = 0
            if pos < len(data):
                sig_len = data[pos]; pos += 1
                pos += sig_len  # skip signature
                if pos < len(data):
                    pk_len = data[pos]; pos += 1
                    pk_bytes = data[pos: pos + pk_len]
                    if len(pk_bytes) in (33, 65):
                        pk_hex = pk_bytes.hex()
                        if pubkey_from_hex(pk_hex):
                            return pk_hex
        except Exception:
            pass
    # P2WPKH: witness = [sig, pubkey]
    witness = inp.get('witness', [])
    if len(witness) >= 2:
        pk_hex = witness[1]
        if pubkey_from_hex(pk_hex):
            return pk_hex
    return None


def extract_pubkey_from_tx(tx: dict, from_txid: str = None,
                            from_vout: int = None) -> Optional[str]:
    """
    Extract the puzzle pubkey from a TX that SPENDS a specific output.

    from_txid + from_vout: the funding TX output being spent.
    Matches the correct input in the spending TX to get the RIGHT pubkey.

    Falls back to first valid pubkey if no match found.
    """
    if from_txid and from_vout is not None:
        # Find the specific input that spends this (txid, vout)
        for inp in tx.get('vin', []):
            if (inp.get('txid') == from_txid and
                    inp.get('vout') == from_vout):
                pk = extract_pubkey_from_input(inp)
                if pk:
                    return pk

    # Fallback: return first valid pubkey from any input
    for inp in tx.get('vin', []):
        pk = extract_pubkey_from_input(inp)
        if pk:
            return pk

    return None

# ──────────────────────────────────────────────────────────────────
# Puzzle output discovery
# ──────────────────────────────────────────────────────────────────

def extract_pubkey_from_p2pk_script(script_hex: str) -> Optional[str]:
    """
    Extract pubkey from a P2PK output script.
    Format: <OP_PUSH_N> <pubkey> OP_CHECKSIG
      Compressed:   21 <33-byte-pubkey> ac
      Uncompressed: 41 <65-byte-pubkey> ac
    Returns hex pubkey or None.
    """
    try:
        b = bytes.fromhex(script_hex)
        # Compressed P2PK: len=35, b[0]=0x21=33, b[-1]=0xac
        if len(b) == 35 and b[0] == 0x21 and b[-1] == 0xac:
            pk = b[1:34].hex()
            if pubkey_from_hex(pk):
                return pk
        # Uncompressed P2PK: len=67, b[0]=0x41=65, b[-1]=0xac
        if len(b) == 67 and b[0] == 0x41 and b[-1] == 0xac:
            pk = b[1:66].hex()
            if pubkey_from_hex(pk):
                return pk
    except Exception:
        pass
    return None


def get_puzzle_outputs(funding_txid: str = FUNDING_TX) -> list:
    """
    Fetch funding TX and return list of output dicts sorted by value.
    Includes scriptpubkey for P2PK extraction on unspent outputs.
    """
    print(f"[PuzzleMap] Fetching funding TX {funding_txid[:16]}...")
    tx = fetch_tx(funding_txid)
    if not tx:
        print("[!] Could not fetch funding TX")
        return []

    outputs = []
    for i, out in enumerate(tx.get('vout', [])):
        addr        = out.get('scriptpubkey_address')
        val         = out.get('value', 0)
        script_hex  = out.get('scriptpubkey', '')
        script_type = out.get('scriptpubkey_type', '')
        outputs.append({
            'vout':        i,
            'addr':        addr,
            'value':       val,
            'script_hex':  script_hex,
            'script_type': script_type,
        })

    outputs.sort(key=lambda x: x['value'])
    print(f"[PuzzleMap] Found {len(outputs)} outputs, "
          f"values: {outputs[0]['value']} - {outputs[-1]['value']} sat")
    return outputs


def collect_solved_pubkeys(funding_txid: str = FUNDING_TX,
                           max_puzzles: int = 66,
                           cache_file: str = 'puzzle_pubkeys.json') -> dict:
    """
    For each puzzle output, find spending TX and extract pubkey.

    Returns: {puzzle_n: {'pubkey': hex, 'addr': str, 'txid': str}}
    """
    import os

    # Load cache if exists
    cache = {}
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            cache = json.load(f)
        print(f"[PubkeyCache] Loaded {len(cache)} cached pubkeys from {cache_file}")

    outputs = get_puzzle_outputs(funding_txid)
    if not outputs:
        return cache

    # Assign puzzle numbers by value rank
    # Puzzle n has value 2^n satoshis (this is the actual structure)
    # We infer puzzle number from the sorted order
    solved = dict(cache)  # start with cache

    for rank, out in enumerate(outputs[:max_puzzles], start=1):
        key_str = str(rank)
        if key_str in solved:
            continue  # already cached

        vout = out['vout']
        addr = out['addr']
        if not addr:
            continue

        # Try P2PK output script first (pubkey visible without spending)
        pk_hex = extract_pubkey_from_p2pk_script(out.get('script_hex', ''))
        if pk_hex:
            pt = pubkey_from_hex(pk_hex)
            solved[key_str] = {
                'puzzle_n':    rank,
                'pubkey':      pk_hex,
                'addr':        addr or '',
                'txid':        funding_txid,  # pubkey from output script
                'vout':        vout,
                'value':       out['value'],
                'source':      'p2pk_output',
            }
            print(f"  Puzzle #{rank:2d}: {pk_hex[:20]}... [P2PK output] "
                  f"(x={hex(pt[0])[:20]}...)")
            continue

        # Check if this output is spent
        spend_info = fetch_utxo(funding_txid, vout)
        if not spend_info or not spend_info.get('spent', False):
            # Not yet spent, no P2PK pubkey → unsolved P2PKH
            print(f"  Puzzle #{rank:2d}: UNSOLVED (P2PKH, unspent)")
            continue

        spending_txid = spend_info.get('txid')
        if not spending_txid:
            continue

        # Fetch spending TX
        spending_tx = fetch_tx(spending_txid)
        if not spending_tx:
            continue

        # Extract pubkey from the SPECIFIC input that spends this output
        pk_hex = extract_pubkey_from_tx(spending_tx,
                                         from_txid=funding_txid,
                                         from_vout=vout)
        if pk_hex and pubkey_from_hex(pk_hex):
            pt = pubkey_from_hex(pk_hex)
            solved[key_str] = {
                'puzzle_n': rank,
                'pubkey':   pk_hex,
                'addr':     addr or '',
                'txid':     spending_txid,
                'vout':     vout,
                'value':    out['value'],
                'source':   'spending_tx',
            }
            print(f"  Puzzle #{rank:2d}: {pk_hex[:20]}... "
                  f"(x={hex(pt[0])[:20]}...)")
        else:
            print(f"  Puzzle #{rank:2d}: spent but pubkey not found in TX "
                  f"{spending_txid[:16]}...")
        time.sleep(0.2)  # rate limiting

    # Save cache
    with open(cache_file, 'w') as f:
        json.dump(solved, f, indent=2)
    print(f"[PubkeyCache] Saved {len(solved)} pubkeys to {cache_file}")
    return solved


# ──────────────────────────────────────────────────────────────────
# Pattern analysis on pubkeys
# ──────────────────────────────────────────────────────────────────

def analyze_pubkey_differences(pubkeys: dict) -> list:
    """
    Compute EC differences between consecutive puzzle pubkeys.
    Returns list of (n, Delta_n=(K_n - K_{n-1}), delta_bits_estimate)
    """
    print(f"\n[DeltaAnalysis] Computing EC differences between consecutive pubkeys...")

    # Sort by puzzle number
    sorted_keys = sorted(pubkeys.items(), key=lambda x: int(x[0]))
    points = []
    for k, v in sorted_keys:
        pt = pubkey_from_hex(v['pubkey'])
        if pt:
            points.append((int(k), pt))

    print(f"  Valid pubkeys: {len(points)}")

    deltas = []
    for i in range(1, len(points)):
        n,     Kn     = points[i]
        n_prev, Kprev = points[i-1]

        # Delta = K_n - K_{n-1} = (k_n - k_{n-1}) * G
        delta_pt = ec_sub(Kn, Kprev)

        # Estimate the "size" of delta via its position on the curve
        # If k_n is in [2^n-1, 2^n-1], then typical k_n - k_{n-1} could be anything
        # The smallest interesting range: from -N/2 to N/2
        # For now, just record the point
        deltas.append({
            'from_n':   n_prev,
            'to_n':     n,
            'delta_pt': delta_pt,
            'Kn':       Kn,
            'Kprev':    Kprev,
        })

    return deltas


def check_constant_delta(deltas: list) -> Optional[tuple]:
    """
    Check if all deltas are the same EC point (constant difference).
    If yes, returns (delta_pt, delta_int) where delta_int is the
    discrete log of delta_pt (if solvable in small range).
    """
    print(f"\n[ConstantDelta] Checking if K_n - K_{{n-1}} is constant...")

    if not deltas:
        return None

    first_delta = deltas[0]['delta_pt']
    all_same = all(d['delta_pt'] == first_delta for d in deltas)

    if all_same:
        print(f"  *** ALL DELTAS ARE EQUAL! Linear pattern found! ***")
        print(f"  delta = {hex(first_delta[0])[:30]}...")
        return first_delta
    else:
        # Count matching deltas
        from collections import Counter
        delta_counts = Counter(d['delta_pt'] for d in deltas)
        most_common, count = delta_counts.most_common(1)[0]
        print(f"  Deltas are not constant.")
        print(f"  Most common delta: appears {count}/{len(deltas)} times")
        if count > len(deltas) * 0.5:
            print(f"  *** MAJORITY MATCH — partial pattern? ***")

    return None


def check_ratio_pattern(pubkeys: dict) -> Optional[int]:
    """
    Check if K_n = r * K_{n-1} (multiplicative in EC group).
    This means k_n = r * k_{n-1} mod N.

    For EC: K_n = r*K_{n-1} means K_n is a scalar multiple of K_{n-1}.
    We can test: does ec_add(K_{n-1}, K_{n-1}) = K_n? (r=2)
    Then r=3, r=4, etc.
    """
    print(f"\n[RatioPattern] Checking multiplicative ratios r*K_{{n-1}} = K_n...")

    sorted_keys = sorted(pubkeys.items(), key=lambda x: int(x[0]))
    points = [(int(k), pubkey_from_hex(v['pubkey'])) for k, v in sorted_keys
              if pubkey_from_hex(v['pubkey'])]

    if len(points) < 3:
        return None

    # Test small ratios
    for r in range(2, 100):
        matches = 0
        for i in range(1, min(len(points), 10)):
            n,     Kn   = points[i]
            n1, Kprev   = points[i-1]
            candidate   = scalar_mul(r, Kprev)
            if candidate == Kn:
                matches += 1
        if matches >= min(5, len(points) - 1):
            print(f"  *** FOUND ratio r={r}: {matches} consecutive matches! ***")
            return r

    # Test negative ratios too (k_n = -r * k_{n-1})
    for r in range(2, 20):
        matches = 0
        for i in range(1, min(len(points), 10)):
            n,     Kn   = points[i]
            n1, Kprev   = points[i-1]
            candidate   = ec_neg(scalar_mul(r, Kprev))
            if candidate == Kn:
                matches += 1
        if matches >= min(5, len(points) - 1):
            print(f"  *** FOUND negative ratio r={r}: {matches} consecutive matches! ***")
            return -r

    print(f"  No simple multiplicative ratio found (tested 2-99)")
    return None


def mini_kangaroo(target_pt: tuple, range_bits: int = 40) -> Optional[int]:
    """
    Solve ECDLP: find k such that k*G = target_pt, k in [0, 2^range_bits].

    Uses CPU-based Kangaroo (for small ranges only!).
    For range_bits <= 40 this runs in seconds.
    """
    print(f"\n[MiniKangaroo] Solving ECDLP for target in [0, 2^{range_bits}]...")
    N_range = 1 << range_bits

    # Baby-step Giant-step (BSGS) for small ranges
    # BSGS: compute t = sqrt(N_range) steps
    t = int(N_range ** 0.5) + 1

    if t > 1_000_000:
        print(f"  Range too large for BSGS ({t} steps). Use GPU Kangaroo.")
        return None

    print(f"  BSGS: {t} baby steps + {t} giant steps")

    # Baby steps: compute j*G for j=0..t, store x-coordinate
    baby_steps = {}
    pt = INF
    for j in range(t + 1):
        if pt != INF:
            baby_steps[pt[0]] = j
        pt = ec_add(pt, G)

    # Giant steps: target - i*t*G for i=0..t
    tG = scalar_mul(t, G)
    neg_tG = ec_neg(tG)
    current = target_pt

    for i in range(t + 1):
        if current != INF and current[0] in baby_steps:
            k = i * t + baby_steps[current[0]]
            # Verify
            if scalar_mul(k, G) == target_pt:
                print(f"  *** Found k = {k} = {hex(k)} ***")
                return k
            # Try k = i*t - baby_step (negative)
            k2 = i * t - baby_steps[current[0]]
            if k2 >= 0 and scalar_mul(k2, G) == target_pt:
                print(f"  *** Found k = {k2} = {hex(k2)} ***")
                return k2
        current = ec_add(current, neg_tG)

    print(f"  Not found in [0, 2^{range_bits}]")
    return None


def predict_target(pubkeys: dict, delta_pt: tuple, delta_k: int,
                    target: int = 71) -> dict:
    """
    Given that k_n = k_{n-1} + delta_k, predict k_<target> for any puzzle.

    Requires: knowing k for at least one puzzle OR solving ECDLP for a puzzle.
    Instead, we check: K_{n-1} + delta_pt = K_n for all n.
    Then K_target = K_{target-1} + delta_pt (we need K_{target-1} first).

    Since puzzle target-1 is typically unsolved, we can't get K_{target-1}
    directly. But we can extrapolate from the last known puzzle pubkey.
    """
    print(f"\n[PredictTarget] Extrapolating K_{target}...")

    sorted_keys = sorted(pubkeys.items(), key=lambda x: int(x[0]))
    if not sorted_keys:
        return {}

    last_n, last_v = sorted_keys[-1]
    last_n   = int(last_n)
    last_pt  = pubkey_from_hex(last_v['pubkey'])

    if last_pt is None:
        return {}

    steps = target - last_n
    extrapolated = last_pt
    for _ in range(steps):
        extrapolated = ec_add(extrapolated, delta_pt)

    print(f"  Last known: puzzle #{last_n}, K_{last_n} = {hex(last_pt[0])[:30]}...")
    print(f"  Steps to extrapolate: {steps}")
    print(f"  Predicted K_{target} = {hex(extrapolated[0])[:30]}...")
    print(f"\n  *** If correct, can run Kangaroo on K_{target} RIGHT NOW! ***")

    return {
        f'predicted_K{target}': extrapolated,
        'target':                target,
        'from_puzzle':           last_n,
        'delta_steps':           steps,
    }


def analyze_normalized_positions(pubkeys: dict) -> None:
    """
    Check if k_n / 2^(n-1) is constant (normalized position).
    We don't have k_n directly, but we have K_n = k_n * G.
    We can check if K_n = (k_n / 2^(n-1)) * 2^(n-1) * G
    But that's just K_n = ratio * (2^(n-1) * G) which requires knowing ratio.

    Instead: if k_n = pos_n * 2^(n-1) for constant pos_n,
    then K_n = pos_n * (2^(n-1) * G)
    We can check: is K_n a scalar multiple of 2^(n-1)*G with the same scalar?
    """
    print(f"\n[NormPos] Checking normalized position consistency...")

    sorted_keys = sorted(pubkeys.items(), key=lambda x: int(x[0]))
    # Need at least 2 consecutive keys
    if len(sorted_keys) < 2:
        return

    # For each pair (n, K_n) and (n+1, K_{n+1}):
    # If k_n = pos * 2^(n-1) and k_{n+1} = pos * 2^n:
    # K_{n+1} = k_{n+1} * G = 2 * k_n * G = 2 * K_n
    # → K_{n+1} = 2*K_n (doubling)
    doubles_count = 0
    total_pairs = 0
    for i in range(len(sorted_keys) - 1):
        n1, v1 = sorted_keys[i];    K1 = pubkey_from_hex(v1['pubkey'])
        n2, v2 = sorted_keys[i+1];  K2 = pubkey_from_hex(v2['pubkey'])
        if K1 is None or K2 is None:
            continue
        # Check if K2 = 2*K1 (same normalized position)
        two_K1 = ec_add(K1, K1)
        total_pairs += 1
        if two_K1 == K2:
            doubles_count += 1

    if doubles_count > 0:
        print(f"  K_{{n+1}} = 2*K_n for {doubles_count}/{total_pairs} pairs!")
        if doubles_count == total_pairs:
            print(f"  *** ALL pairs satisfy K_{{n+1}} = 2*K_n! ***")
            print(f"  This means k_n = k_1 * 2^(n-1) for all n!")
            print(f"  → k_71 = k_1 * 2^70 = {hex(1 * (1 << 70))}")
    else:
        print(f"  K_{{n+1}} != 2*K_n (no power-of-2 scaling)")


# ──────────────────────────────────────────────────────────────────
# Known pubkeys (hard-coded from public sources for speed)
# Filled in from blockchain data — spending TXs of solved puzzles
# Source: publicly available on-chain data
# ──────────────────────────────────────────────────────────────────

# These are the actual pubkeys from the spending transactions
# (P2PKH compressed pubkeys or P2WPKH witness pubkeys)
# Note: only SOLVED puzzles have spending TXs with pubkeys
KNOWN_PUBKEYS_HEX = {
    # Puzzle# : pubkey_hex (from spending TX)
    # *** These need to be filled from blockchain ***
    # Run: python analysis/pubkey_pattern.py --collect
    # Or manually add from https://www.blockchain.com/btc/tx/<TXID>
}

# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────

def run_analysis(collected: dict, target: int = 71) -> None:
    """Run all pattern checks on collected pubkeys. target = puzzle # to predict."""
    n = len(collected)
    if n < 3:
        print(f"[!] Need at least 3 pubkeys for pattern analysis. Have {n}.")
        print(f"    Run: python analysis/pubkey_pattern.py --collect")
        return

    print(f"\n{'='*60}")
    print(f"  PUBKEY PATTERN ANALYSIS — {n} solved puzzles")
    print(f"{'='*60}")

    # 1. Normalized position check
    analyze_normalized_positions(collected)

    # 2. Multiplicative ratio check
    check_ratio_pattern(collected)

    # 3. EC differences
    deltas = analyze_pubkey_differences(collected)

    # 4. Constant delta check
    const_delta = check_constant_delta(deltas)

    if const_delta and const_delta != INF:
        # 5. Solve mini ECDLP for the delta
        # The delta c = k_n - k_{n-1}
        # For small puzzles, typical k_n ~ 2^(n-1) to 2^n
        # Max difference: k_n (up to 2^66) - k_{n-1} (at least 2^64) ~ 3*2^64
        # That's too large for BSGS, but range_bits=70 Kangaroo on GPU could do it

        print(f"\n[Delta] Constant delta found!")
        print(f"  delta (x-coord): {hex(const_delta[0])}")
        print(f"\n  Solving k_delta = ECDLP(delta, G) on CPU [0, 2^40]...")
        k_delta = mini_kangaroo(const_delta, range_bits=40)

        if k_delta:
            print(f"\n  *** DELTA k = {k_delta} ***")
            pred = predict_target(collected, const_delta, k_delta, target=target)
        else:
            print(f"\n  Delta too large for CPU — needs GPU Kangaroo")
            print(f"  Run: python main.py --kangaroo --pubkey "
                  f"{hex(const_delta[0])}:{hex(const_delta[1])}")
            pred = predict_target(collected, const_delta, 0, target=target)

    # 6. Print summary of all delta x-coordinates
    if deltas:
        print(f"\n[Deltas] All {len(deltas)} EC differences:")
        print(f"  {'Pair':12s}  {'delta.x (first 16 hex chars)'}")
        print(f"  {'-'*50}")
        for d in deltas[:20]:
            dx = d['delta_pt']
            dx_str = hex(dx[0])[:18] if dx != INF else 'INF'
            print(f"  #{d['from_n']:2d}->#{d['to_n']:2d}       {dx_str}...")
        if len(deltas) > 20:
            print(f"  ... and {len(deltas)-20} more")


def main():
    import argparse
    import os

    parser = argparse.ArgumentParser(
        description='Pubkey pattern analysis for Bitcoin Puzzle creator'
    )
    parser.add_argument('--collect', action='store_true',
                        help='Collect pubkeys from blockchain')
    parser.add_argument('--max-puzzles', type=int, default=66,
                        help='Max puzzle number to collect (default: 66)')
    parser.add_argument('--cache', default='puzzle_pubkeys.json',
                        help='Cache file for pubkeys')
    parser.add_argument('--load', default='',
                        help='Load pubkeys from JSON file (skip collection)')
    parser.add_argument('--analyze-only', action='store_true',
                        help='Only run analysis, no blockchain fetch')
    parser.add_argument('--target', type=int, default=71,
                        help='Puzzle number to predict/extrapolate to (default: 71). '
                             'Run analysis/puzzle_status.py --unsolved to see candidates.')
    args = parser.parse_args()

    print("\n" + "="*60)
    print("  BITCOIN PUZZLE — Pubkey Pattern Analysis")
    print("  Ищем паттерн в EC-точках решённых пазлов")
    print("="*60)

    if args.load and os.path.exists(args.load):
        with open(args.load) as f:
            collected = json.load(f)
        print(f"[Load] Loaded {len(collected)} entries from {args.load}")
    elif args.collect or not args.analyze_only:
        if not HAS_REQUESTS:
            print("[!] Install requests: pip install requests")
            sys.exit(1)
        print(f"\n[Step 1] Collecting pubkeys from blockchain...")
        print(f"  Funding TX: {FUNDING_TX}")
        print(f"  Max puzzles: {args.max_puzzles}")
        collected = collect_solved_pubkeys(
            funding_txid=FUNDING_TX,
            max_puzzles=args.max_puzzles,
            cache_file=args.cache,
        )
    else:
        # Try to load from default cache
        if os.path.exists(args.cache):
            with open(args.cache) as f:
                collected = json.load(f)
        else:
            collected = {}

    if not collected:
        print("\n[!] No pubkeys collected.")
        print("    Try: python analysis/pubkey_pattern.py --collect")
        sys.exit(1)

    run_analysis(collected, target=args.target)


if __name__ == '__main__':
    main()
