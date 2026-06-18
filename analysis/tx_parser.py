"""
Bitcoin Transaction Parser + Sighash Computation
=================================================
Парсит legacy P2PKH транзакции и вычисляет z (sighash) для каждого input.
z нужен для ECDSA nonce-атак: privkey = (s*k - z) / r mod N.

Поддерживает: P2PKH (legacy), P2SH (частично), segwit witness (извлечение r,s).
"""

import hashlib
import struct
import json
from typing import Optional

# secp256k1
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


# ──────────────────────────────────────────────────────────────────
# Утилиты
# ──────────────────────────────────────────────────────────────────

def hash256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def _varint_encode(n: int) -> bytes:
    if n < 0xfd:
        return bytes([n])
    elif n <= 0xffff:
        return b'\xfd' + n.to_bytes(2, 'little')
    elif n <= 0xffffffff:
        return b'\xfe' + n.to_bytes(4, 'little')
    else:
        return b'\xff' + n.to_bytes(8, 'little')


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Returns (value, new_pos)."""
    b = data[pos]
    if b < 0xfd:
        return b, pos + 1
    elif b == 0xfd:
        return int.from_bytes(data[pos+1:pos+3], 'little'), pos + 3
    elif b == 0xfe:
        return int.from_bytes(data[pos+1:pos+5], 'little'), pos + 5
    else:
        return int.from_bytes(data[pos+1:pos+9], 'little'), pos + 9


# ──────────────────────────────────────────────────────────────────
# DER signature parsing
# ──────────────────────────────────────────────────────────────────

def parse_der_sig(sig_bytes: bytes) -> Optional[tuple[int, int]]:
    """
    Parse DER-encoded ECDSA signature → (r, s) or None.
    The last byte is sighash_type, strip it before parsing.
    """
    try:
        # Strip sighash type (last byte, usually 0x01)
        if len(sig_bytes) > 0 and sig_bytes[-1] in (0x01, 0x02, 0x03, 0x81, 0x82, 0x83):
            data = sig_bytes[:-1]
        else:
            data = sig_bytes

        if not data or data[0] != 0x30:
            return None
        pos = 2   # skip 0x30 <total_len>

        if data[pos] != 0x02:
            return None
        r_len = data[pos + 1]
        r = int.from_bytes(data[pos + 2: pos + 2 + r_len], 'big')
        pos += 2 + r_len

        if data[pos] != 0x02:
            return None
        s_len = data[pos + 1]
        s = int.from_bytes(data[pos + 2: pos + 2 + s_len], 'big')

        if r <= 0 or r >= N or s <= 0 or s >= N:
            return None
        return r, s
    except Exception:
        return None


def parse_scriptsig_p2pkh(scriptsig_hex: str) -> Optional[tuple[bytes, bytes]]:
    """
    Parse P2PKH scriptSig → (sig_bytes, pubkey_bytes) or None.
    Format: <push> <sig+sighash> <push> <pubkey>
    """
    try:
        data = bytes.fromhex(scriptsig_hex)
        pos = 0
        sig_len = data[pos]; pos += 1
        sig_bytes = data[pos: pos + sig_len]; pos += sig_len
        pk_len = data[pos]; pos += 1
        pk_bytes = data[pos: pos + pk_len]
        if len(pk_bytes) not in (33, 65):
            return None
        return sig_bytes, pk_bytes
    except Exception:
        return None


def parse_witness_sig(witness: list) -> Optional[tuple[bytes, bytes]]:
    """
    Parse P2WPKH witness stack → (sig_bytes, pubkey_bytes).
    witness = [sig_hex, pubkey_hex]
    """
    try:
        if len(witness) < 2:
            return None
        sig_b = bytes.fromhex(witness[0])
        pk_b  = bytes.fromhex(witness[1])
        if len(pk_b) not in (33, 65):
            return None
        return sig_b, pk_b
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────
# Sighash (z) computation — legacy P2PKH / P2SH
# ──────────────────────────────────────────────────────────────────

def compute_sighash_legacy(tx: dict, input_idx: int) -> Optional[int]:
    """
    Compute SIGHASH_ALL (z) for input_idx in a legacy transaction.

    Uses Blockstream API tx format:
      tx['version'], tx['locktime']
      tx['vin'][i]: txid, vout, sequence, prevout.scriptpubkey
      tx['vout'][j]: value (satoshis), scriptpubkey

    Returns z as int or None if data incomplete.
    """
    try:
        inp = tx['vin'][input_idx]
        prevout_script = bytes.fromhex(inp['prevout']['scriptpubkey'])

        # Serialise signing preimage
        buf = tx['version'].to_bytes(4, 'little')

        buf += _varint_encode(len(tx['vin']))
        for i, vin in enumerate(tx['vin']):
            txid_bytes = bytes.fromhex(vin['txid'])[::-1]
            buf += txid_bytes
            buf += vin['vout'].to_bytes(4, 'little')
            if i == input_idx:
                buf += _varint_encode(len(prevout_script)) + prevout_script
            else:
                buf += b'\x00'   # empty script for other inputs
            buf += vin['sequence'].to_bytes(4, 'little')

        buf += _varint_encode(len(tx['vout']))
        for out in tx['vout']:
            buf += out['value'].to_bytes(8, 'little')
            script = bytes.fromhex(out['scriptpubkey'])
            buf += _varint_encode(len(script)) + script

        buf += tx['locktime'].to_bytes(4, 'little')
        buf += (1).to_bytes(4, 'little')   # SIGHASH_ALL

        return int.from_bytes(hash256(buf), 'big')
    except Exception as e:
        return None


def compute_sighash_segwit_v0(tx: dict, input_idx: int,
                               amount: int, script_code: bytes) -> Optional[int]:
    """
    Compute BIP143 sighash for P2WPKH input.
    amount: satoshis of the UTXO being spent.
    script_code: for P2WPKH = OP_DUP OP_HASH160 <20-byte-hash> OP_EQUALVERIFY OP_CHECKSIG
    """
    try:
        # BIP143 preimage
        version = tx['version'].to_bytes(4, 'little')

        # hashPrevouts
        all_outpoints = b''
        for vin in tx['vin']:
            all_outpoints += bytes.fromhex(vin['txid'])[::-1]
            all_outpoints += vin['vout'].to_bytes(4, 'little')
        hash_prevouts = hash256(all_outpoints)

        # hashSequence
        all_seqs = b''
        for vin in tx['vin']:
            all_seqs += vin['sequence'].to_bytes(4, 'little')
        hash_sequence = hash256(all_seqs)

        # outpoint
        inp = tx['vin'][input_idx]
        outpoint = bytes.fromhex(inp['txid'])[::-1] + inp['vout'].to_bytes(4, 'little')

        # scriptCode length-prefixed
        sc = _varint_encode(len(script_code)) + script_code

        # value
        value = amount.to_bytes(8, 'little')
        nsequence = inp['sequence'].to_bytes(4, 'little')

        # hashOutputs
        all_outs = b''
        for out in tx['vout']:
            script = bytes.fromhex(out['scriptpubkey'])
            all_outs += out['value'].to_bytes(8, 'little')
            all_outs += _varint_encode(len(script)) + script
        hash_outputs = hash256(all_outs)

        locktime = tx['locktime'].to_bytes(4, 'little')
        sighash_type = (1).to_bytes(4, 'little')

        preimage = (version + hash_prevouts + hash_sequence +
                    outpoint + sc + value + nsequence +
                    hash_outputs + locktime + sighash_type)
        return int.from_bytes(hash256(preimage), 'big')
    except Exception:
        return None


def p2wpkh_script_code(pubkey: bytes) -> bytes:
    """Build P2WPKH script_code from pubkey."""
    import hashlib
    h = hashlib.new('ripemd160', hashlib.sha256(pubkey).digest()).digest()
    return bytes([0x76, 0xa9, 0x14]) + h + bytes([0x88, 0xac])


# ──────────────────────────────────────────────────────────────────
# High-level: extract all signatures from a tx dict
# ──────────────────────────────────────────────────────────────────

def extract_sigs_from_tx(tx: dict) -> list[dict]:
    """
    Extract all ECDSA signatures from a transaction.

    Returns list of dicts:
      { 'txid', 'input_idx', 'r', 's', 'z', 'pubkey_hex', 'type' }
    z may be None if sighash computation failed.
    """
    results = []
    txid = tx.get('txid', 'unknown')

    for i, inp in enumerate(tx.get('vin', [])):
        scriptsig = inp.get('scriptsig', '')
        witness   = inp.get('witness', [])
        entry_type = 'unknown'

        sig_bytes = pk_bytes = None

        # P2PKH (legacy)
        if scriptsig:
            parsed = parse_scriptsig_p2pkh(scriptsig)
            if parsed:
                sig_bytes, pk_bytes = parsed
                entry_type = 'p2pkh'

        # P2WPKH (segwit v0)
        if sig_bytes is None and witness:
            parsed = parse_witness_sig(witness)
            if parsed:
                sig_bytes, pk_bytes = parsed
                entry_type = 'p2wpkh'

        if sig_bytes is None:
            continue

        rs = parse_der_sig(sig_bytes)
        if rs is None:
            continue
        r, s = rs

        # Compute sighash z
        z = None
        if entry_type == 'p2pkh':
            z = compute_sighash_legacy(tx, i)
        elif entry_type == 'p2wpkh' and pk_bytes:
            sc     = p2wpkh_script_code(pk_bytes)
            amount = inp.get('prevout', {}).get('value', 0)
            z      = compute_sighash_segwit_v0(tx, i, amount, sc)

        results.append({
            'txid':       txid,
            'input_idx':  i,
            'r':          r,
            's':          s,
            'z':          z,
            'pubkey_hex': pk_bytes.hex() if pk_bytes else None,
            'type':       entry_type,
        })

    return results
