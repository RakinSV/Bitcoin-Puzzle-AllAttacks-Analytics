#!/usr/bin/env python3
"""
run_all_analyses.py — run EVERY analysis and attack (except the GPU lottery)
across ALL puzzles and write every result to files. No parameters needed:

    python run_all_analyses.py

Output goes to  reports/<timestamp>/ :

    00_SUMMARY.txt                  one-screen verdict + any hits
    global/*.txt                    analyses that already span all keys/puzzles
    per_puzzle/*.txt                per-target analyses, looped over all puzzles
                                    (one consolidated file per tool)

Offline analyses run first (instant, no internet). On-chain analyses run last
(need internet; each is wrapped so a network failure never aborts the batch).

This is the "fire and forget" entry point: kick it off, come back to a folder
full of reports. The interactive menu (RUN_ALL_SMART_ATTACKS.bat) is still there
if you want to drive individual tools by hand.
"""

import os
import sys
import time
import subprocess
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
PY = sys.executable

# Where reports go / what the workers use as cwd. In a frozen build ROOT points
# inside the bundle (_internal), which is NOT where a user would ever look, so
# write next to the executable instead.
if getattr(sys, "frozen", False):
    DATA_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    DATA_ROOT = ROOT

from utils.puzzle_registry import all_puzzle_numbers

ALL_PUZZLES = sorted(all_puzzle_numbers())


# ---------------------------------------------------------------------------
# subprocess helper — capture stdout+stderr, never raise, decode cp1251-safely
# ---------------------------------------------------------------------------
def _resolve(cmd):
    """Map a ["analysis/foo.py", ...args] command to a runnable argv.

    In dev we just run the .py with the current interpreter. In a frozen
    PyInstaller build there is no interpreter for arbitrary .py files, so we
    re-invoke the app binary with the --module marker (app_entry routes it
    through runpy)."""
    if getattr(sys, "frozen", False):
        module = cmd[0].replace("/", ".").replace("\\", ".")
        if module.endswith(".py"):
            module = module[:-3]
        return [sys.executable, "--module", module] + cmd[1:]
    return [PY] + cmd


def run(cmd, timeout=600):
    """Run a command, return (exit_code, text). Errors are captured, not raised."""
    try:
        # Force child Python to emit UTF-8 so captured bytes decode cleanly
        # regardless of the Windows console code page (cp1251).
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        p = subprocess.run(
            _resolve(cmd), cwd=DATA_ROOT, capture_output=True, timeout=timeout, env=env,
        )
        raw = p.stdout + p.stderr
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1251", errors="replace")
        return p.returncode, text
    except subprocess.TimeoutExpired:
        return 124, f"[TIMEOUT after {timeout}s]\n"
    except Exception as e:                      # pragma: no cover
        return 1, f"[RUNNER ERROR] {e}\n"


def write(path, header, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n" + "=" * len(header) + "\n\n" + body)


def banner(msg):
    line = "#" * 64
    print(f"\n{line}\n#  {msg}\n{line}")


# ---------------------------------------------------------------------------
# the catalogue of work
# ---------------------------------------------------------------------------
GLOBAL_TASKS = [
    # (filename,                 nice name,                          argv,                              online)
    ("rng_quick.txt",            "RNG distribution (quick)",         ["analysis/rng_analysis.py", "--quick"],            False),
    ("rng_segments.txt",         "RNG priority segments",            ["analysis/rng_analysis.py", "--segments"],         False),
    ("bip32_test_all.txt",       "BIP32 / HD-wallet pattern",        ["analysis/bip32_analysis.py", "--test-all"],       False),
    ("nist_randomness.txt",      "NIST SP 800-22 battery",           ["analysis/nist_randomness.py"],                    False),
    ("puzzle_status.txt",        "Live puzzle status (unsolved)",    ["analysis/puzzle_status.py", "--unsolved", "--max", "150"], True),
    ("ghost_solved.txt",         "Ghost-solved re-verification",     ["analysis/ghost_solved_check.py"],                 True),
    ("creator_fingerprint.txt",  "Creator fingerprint (--deep)",     ["analysis/creator_fingerprint.py", "--deep"],      True),
    ("nonce_attack.txt",         "ECDSA nonce-reuse attack",         ["analysis/nonce_attack.py", "--quick"],            True),
    ("pubkey_pattern.txt",       "Pubkey EC-point pattern",          ["analysis/pubkey_pattern.py", "--collect"],        True),
]

# per-target analyses: looped over every puzzle, one consolidated file each
PER_PUZZLE_TASKS = [
    # (filename,             nice name,                     argv-template (NN substituted))
    ("rng_predict_ALL.txt",  "RNG key prediction",          ["analysis/rng_analysis.py", "--predict", "--target", "{n}"]),
    ("bip32_ALL.txt",        "BIP32 per-puzzle derivation", ["analysis/bip32_analysis.py", "--target", "{n}"]),
    ("brainwallet_ALL.txt",  "Brainwallet dictionary",      ["analysis/brainwallet_attack.py", "--target", "{n}"]),
]

# words in any output that mean "we actually found / predicted a key"
HIT_MARKERS = ("PRIVATE KEY FOUND", "MATCH FOUND", "KEY RECOVERED",
               "PREDICTED KEY", "SOLVED!", "found key", "k = 0x")


def main():
    only_offline = "--offline" in sys.argv
    puzzles = ALL_PUZZLES
    if "--max" in sys.argv:                     # cap puzzle count (smoke test)
        try:
            puzzles = ALL_PUZZLES[: int(sys.argv[sys.argv.index("--max") + 1])]
        except (ValueError, IndexError):
            pass
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = os.path.join(DATA_ROOT, "reports", stamp)
    os.makedirs(outdir, exist_ok=True)

    print(f"Bitcoin Puzzle — full analysis sweep over {len(puzzles)} puzzles")
    print(f"Reports -> {outdir}")
    t_start = time.time()

    summary = []
    hits = []

    # ---- GLOBAL analyses -------------------------------------------------
    banner("PART 1 — GLOBAL ANALYSES (span all keys/puzzles)")
    for fname, name, argv, online in GLOBAL_TASKS:
        if online and only_offline:
            print(f"  [skip] {name} (online, --offline set)")
            continue
        tag = "online" if online else "offline"
        print(f"  [{tag}] {name} ...", end="", flush=True)
        t0 = time.time()
        code, text = run(argv)
        dt = time.time() - t0
        write(os.path.join(outdir, "global", fname),
              f"{name}   (exit={code}, {dt:.1f}s)", text)
        status = "OK" if code == 0 else f"exit {code}"
        print(f" {status} ({dt:.1f}s)")
        summary.append(f"  [{status:>6}] global/{fname:<26} {name}")
        if any(m in text for m in HIT_MARKERS):
            hits.append(f"  !!! possible hit in global/{fname} — {name}")

    # ---- PER-PUZZLE analyses (loop all 150) ------------------------------
    banner(f"PART 2 — PER-PUZZLE ANALYSES (looped over {len(puzzles)} puzzles)")
    for fname, name, tmpl in PER_PUZZLE_TASKS:
        print(f"  {name}: ", end="", flush=True)
        chunks = []
        n_hit = 0
        t0 = time.time()
        for n in puzzles:
            argv = [a.replace("{n}", str(n)) for a in tmpl]
            code, text = run(argv, timeout=120)
            chunks.append(f"\n----- puzzle #{n}  (exit={code}) -----\n{text}")
            if any(m in text for m in HIT_MARKERS):
                n_hit += 1
                hits.append(f"  !!! possible hit in per_puzzle/{fname} — puzzle #{n}")
            if n % 25 == 0:
                print(".", end="", flush=True)
        dt = time.time() - t0
        write(os.path.join(outdir, "per_puzzle", fname),
              f"{name} — {len(puzzles)} puzzles   ({dt:.0f}s, {n_hit} flags)",
              "".join(chunks))
        print(f" done ({dt:.0f}s, {n_hit} flags)")
        summary.append(f"  [   ALL] per_puzzle/{fname:<22} {name} ({n_hit} flags)")

    # ---- SUMMARY ---------------------------------------------------------
    total = time.time() - t_start
    lines = []
    lines.append("BITCOIN PUZZLE — FULL ANALYSIS SWEEP")
    lines.append(f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}")
    lines.append(f"Puzzles covered: {len(puzzles)}  (#{puzzles[0]}..#{puzzles[-1]})")
    lines.append(f"Total time: {total:.0f}s")
    lines.append("")
    lines.append("WHAT RAN")
    lines.append("--------")
    lines.extend(summary)
    lines.append("")
    lines.append("HITS / FLAGS")
    lines.append("------------")
    if hits:
        lines.extend(hits)
        lines.append("")
        lines.append(">>> Inspect the flagged files above. A real hit means a key")
        lines.append(">>> shortcut was found — verify it before doing anything else.")
    else:
        lines.append("  (none) — no RNG/brainwallet/nonce shortcut on any puzzle.")
        lines.append("  Creator used real randomness; brute force / Kangaroo is the")
        lines.append("  only route. This is the expected, healthy result.")
    lines.append("")
    lines.append("NEXT STEP")
    lines.append("---------")
    lines.append("  No shortcut above -> run the GPU lottery: START_LOTTERY.bat")
    lines.append("  Watch mempool for exposed pubkeys to snipe: RUN_MULTI_SNIPER.bat")

    summary_path = os.path.join(outdir, "00_SUMMARY.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    banner("DONE")
    print("\n".join(lines))
    print(f"\nAll reports saved under: {outdir}")


if __name__ == "__main__":
    main()
