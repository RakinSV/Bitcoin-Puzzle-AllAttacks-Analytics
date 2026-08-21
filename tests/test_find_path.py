#!/usr/bin/env python3
"""
Does the lottery actually CAPTURE a key when it finds one?

Detection is only the first link. The chain that has to hold, in order, is:

    GPU reports a hit -> the key is decoded -> WIF is derived -> the file is
    written and fsync'd -> the address verifies

A break anywhere past the first link looks exactly like a search that never
found anything, and would silently discard months of compute. tests/
test_gpu_bigkey_kat.py proves the GPU reports large keys; this proves the rest of
the chain carries that report to disk.

Everything runs in a temp directory so a real FOUND_KEY file is never touched or
faked in the user's working copy.

Run:  python tests/test_find_path.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.rng_analysis import KNOWN_KEYS
from ecc.curve import scalar_mul, G
from utils.address import point_to_address, verify_key_address

FAILS = []


def check(name, cond, detail=""):
    print("  [%s] %s%s" % ("OK" if cond else "FAIL", name,
                           ("  -- " + detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def test_wif_is_correct():
    """WIF must round-trip back to the same scalar, and match a known vector."""
    from main import _key_to_wif
    import hashlib

    def wif_to_int(w):
        alpha = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
        num = 0
        for ch in w:
            num = num * 58 + alpha.index(ch)
        raw = num.to_bytes(37 if len(w) < 52 else 38, 'big')
        # strip checksum, leading 0x80, optional 0x01 compression flag
        body = raw[:-4]
        body = body[1:]                       # version byte
        if len(body) == 33 and body[-1] == 1:
            body = body[:-1]
        return int.from_bytes(body, 'big')

    for n in (1, 30, 55, 70):
        k = KNOWN_KEYS[n]
        w = _key_to_wif(k)
        # checksum must be valid
        alpha = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
        num = 0
        for ch in w:
            num = num * 58 + alpha.index(ch)
        raw = num.to_bytes((num.bit_length() + 7) // 8, 'big')
        ok_sum = hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4] == raw[-4:]
        check("WIF checksum valid for #%d" % n, ok_sum)
        check("WIF decodes back to the key for #%d" % n, wif_to_int(w) == k,
              "%s..." % w[:12])


def test_save_writes_every_file():
    """A find must land on disk -- emergency file first, then the rest."""
    from main import _save_found_key

    k = KNOWN_KEYS[55]
    addr = point_to_address(*scalar_mul(k, G))

    workdir = tempfile.mkdtemp(prefix="findpath-")
    cwd = os.getcwd()
    home = os.environ.get("USERPROFILE")
    try:
        os.chdir(workdir)
        # Point the desktop copy at the scratch dir too, so nothing escapes.
        os.environ["USERPROFILE"] = workdir
        os.makedirs(os.path.join(workdir, "Desktop"), exist_ok=True)
        _save_found_key(k, addr)

        files = os.listdir(workdir)
        found_files = [f for f in files if "FOUND" in f.upper()]
        check("at least one FOUND file written", bool(found_files),
              ", ".join(sorted(found_files)[:4]))
        check("emergency file present",
              any("EMERGENCY" in f.upper() for f in found_files))

        # The saved key must be recoverable from what was written.
        blob = ""
        for f in found_files:
            p = os.path.join(workdir, f)
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    blob += fh.read()
        check("hex key appears in the saved text", hex(k) in blob)
        check("address appears in the saved text", addr in blob)

        from main import _key_to_wif
        check("WIF appears in the saved text", _key_to_wif(k) in blob)
    finally:
        os.chdir(cwd)
        if home is not None:
            os.environ["USERPROFILE"] = home
        shutil.rmtree(workdir, ignore_errors=True)


def test_verification_rejects_a_wrong_key():
    """The 'Address verified' check must not rubber-stamp a wrong key."""
    k = KNOWN_KEYS[40]
    addr = point_to_address(*scalar_mul(k, G))
    check("correct key verifies", verify_key_address(k, addr))
    check("wrong key is rejected", not verify_key_address(k + 1, addr))
    check("off-by-one-bit key is rejected", not verify_key_address(k ^ 1, addr))


def test_gpu_hit_decodes_to_the_real_key():
    """End-to-end: plant a real key in the swept block, decode what comes back."""
    from kangaroo.gpu_search import GPUSearchEngine
    from utils.address import get_target_for_kernel

    k = KNOWN_KEYS[63]
    addr = point_to_address(*scalar_mul(k, G))
    eng = GPUSearchEngine(device_idx=0, threads=64, blocks=128,
                          points_per_thread=8)
    eng.set_target(get_target_for_kernel(addr))
    eng.initialize(k - 5000)

    hit = None
    for _ in range(4):
        for r in eng.step() or []:
            if r.get("k") == k:
                hit = r
                break
        if hit:
            break
    check("GPU reports the planted key", hit is not None)
    if hit:
        check("reported key is exactly right", hit["k"] == k, hex(hit["k"]))
        check("reported key verifies against the address",
              verify_key_address(hit["k"], addr))
    del eng


if __name__ == "__main__":
    print("=" * 66)
    print("  FIND-PATH: does a hit actually reach the disk intact?")
    print("=" * 66)
    print("\n--- WIF encoding ---")
    test_wif_is_correct()
    print("\n--- saving to disk ---")
    test_save_writes_every_file()
    print("\n--- verification is not a rubber stamp ---")
    test_verification_rejects_a_wrong_key()
    print("\n--- end-to-end GPU hit ---")
    test_gpu_hit_decodes_to_the_real_key()
    print("\n" + "=" * 66)
    if FAILS:
        print("  %d FAILED: %s" % (len(FAILS), FAILS))
        sys.exit(1)
    print("  FIND PATH INTACT -- a real hit would be decoded and saved [OK]")
    print("=" * 66)
