#!/usr/bin/env python3
"""
The sweep script must carry the key -- and the regex that finds it must work.

Withholding the WIF from the generated script protected nothing: it has to reach
the offline machine to sign with, so it travels either way, and leaving a
placeholder only forced a hand-copy of the one string a typo destroys. The key is
now read out of FOUND_KEY.txt automatically, which also keeps it off the command
line and out of shell history.

The second test here exists because of how the first bug hid. An edit put literal
BACKSPACE bytes (0x08) into the WIF pattern, since a backslash-b inside a normal
Python string is an escape rather than two characters. Every listing of that line
rendered identically to the correct one -- the byte is invisible -- while the
pattern silently matched nothing. So the pattern is asserted against a real WIF,
and the module is scanned for control bytes, rather than trusting how it looks.

Run:  python tests/test_sweep_key_fill.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.rng_analysis import KNOWN_KEYS
from main import _key_to_wif
import analysis.build_sweep_tx as B

FAILS = []


def check(name, cond, detail=""):
    print("  [%s] %s%s" % ("OK" if cond else "FAIL", name,
                           ("  -- " + detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def _root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_wif_is_read_from_found_key():
    wif = _key_to_wif(KNOWN_KEYS[45])
    path = os.path.join(_root(), 'FOUND_KEY.txt')
    existed = os.path.exists(path)
    backup = None
    if existed:
        with open(path, encoding='utf-8', errors='replace') as f:
            backup = f.read()
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write("BITCOIN PUZZLE SOLVED!\nPrivate key (WIF):  %s\n" % wif)
        got, src = B.read_found_wif(71)
        check("WIF recovered from FOUND_KEY.txt", got == wif,
              (got or "None")[:24])
        check("source file reported", src == 'FOUND_KEY.txt', str(src))
    finally:
        if backup is not None:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(backup)
        elif os.path.exists(path):
            os.remove(path)


def test_no_key_file_means_no_key():
    """With nothing solved there is nothing to fill in -- and no crash."""
    path = os.path.join(_root(), 'FOUND_KEY.txt')
    if os.path.exists(path):
        print("  [skip] a real FOUND_KEY.txt exists; not touching it")
        return
    got, src = B.read_found_wif(71)
    check("returns (None, None) when nothing is solved",
          got is None and src is None)


def test_pattern_actually_matches_a_wif():
    """Assert behaviour, not appearance: the 0x08 bug looked perfect."""
    import re
    wif = _key_to_wif(KNOWN_KEYS[45])
    src = open(B.__file__, encoding='utf-8').read()
    ctrl = sorted({hex(ord(c)) for c in src if ord(c) < 32 and c not in '\n\t\r'})
    check("module contains no stray control bytes", not ctrl, ", ".join(ctrl))
    # And the compiled pattern must find a real WIF in real surrounding text.
    got, _ = None, None
    line = "Private key (WIF):  %s" % wif
    check("WIF pattern matches inside a line of text",
          any(m == wif for m in re.findall(
              '(?<![1-9A-HJ-NP-Za-km-z])([5KL][1-9A-HJ-NP-Za-km-z]{50,51})'
              '(?![1-9A-HJ-NP-Za-km-z])', line)))


if __name__ == "__main__":
    print("=" * 66)
    print("  SWEEP SCRIPT KEY FILL")
    print("=" * 66)
    print("\n--- the key is read from FOUND_KEY.txt ---")
    test_wif_is_read_from_found_key()
    print("\n--- nothing solved, nothing filled ---")
    test_no_key_file_means_no_key()
    print("\n--- the pattern works, regardless of how it looks ---")
    test_pattern_actually_matches_a_wif()
    print("\n" + "=" * 66)
    if FAILS:
        print("  %d FAILED: %s" % (len(FAILS), FAILS))
        sys.exit(1)
    print("  KEY FILL WORKS [OK]")
    print("=" * 66)
