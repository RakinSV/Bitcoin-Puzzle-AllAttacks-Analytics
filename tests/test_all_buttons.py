#!/usr/bin/env python3
"""
Exercise EVERY action button in the GUI end-to-end.

For each run button this takes the command the button itself would build (so a
mis-wired button or a wrong CLI flag is caught), actually runs it, and checks
the worker starts and behaves. Long-running actions (lottery, sniper, monitor,
full sweep) only have to start cleanly and produce output; they are then killed.

Failures we are hunting:
  * wrong/unsupported CLI flags   -> argparse exits 2 "unrecognized arguments"
  * module not importable         -> traceback / "No module named"
  * worker dies instantly         -> non-zero exit with a traceback

Run:  python tests/test_all_buttons.py
"""

import os
import subprocess
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication          # noqa: E402
import app.gui as gui                               # noqa: E402

APP = QApplication.instance() or QApplication([])

# Actions that run indefinitely, or far longer than any sane test budget:
#  - the solver modes (lottery/CPU never stop; Kangaroo takes minutes)
#  - watchers (sniper/monitor)
#  - the full sweep and the bench sweep
#  - on-chain actions: ~150 addresses x 0.25s politeness sleep + API latency,
#    i.e. minutes. Slow is not the same as hung; we assert they run clean.
LONG_RUNNING = {"Solve", "Solve/GPU lottery", "Solve/Kangaroo", "Solve/CPU",
                "Multi-sniper", "Monitor",
                "First-time full research", "Run ALL analyses (all 150 puzzles)",
                "Benchmark sweep",
                "Live puzzle status", "Ghost-solved re-verification",
                "Creator fingerprint (deep)", "Refresh live puzzle status"}
# Need the network; a connectivity failure is not a wiring bug.
ONLINE = {"Live puzzle status", "Ghost-solved re-verification",
          "Creator fingerprint (deep)", "ECDSA nonce-reuse attack",
          "Pubkey EC-point patterns", "Refresh live puzzle status",
          "Multi-sniper", "Monitor"}

BAD = ("Traceback", "No module named", "unrecognized arguments",
       "invalid choice", "error: argument", "usage:")

results = []


def run_cmd(label, prog, args, budget):
    """Return (verdict, detail).

    stdout MUST be drained continuously: a chatty worker fills the pipe buffer
    and blocks forever otherwise, which would look like "still running" and hide
    whether it actually exits cleanly. (The real app drains via QProcess.)
    """
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.Popen([prog] + args, cwd=ROOT, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except Exception as e:
        return "FAIL", f"could not launch: {e}"

    chunks = []
    reader = threading.Thread(target=lambda: chunks.append(p.stdout.read() or b""),
                              daemon=True)
    reader.start()

    deadline = time.time() + budget
    while time.time() < deadline and p.poll() is None:
        time.sleep(0.2)

    killed = p.poll() is None
    if killed:
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)],
                           capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            p.kill()
        p.wait(timeout=10)
    reader.join(timeout=10)
    text = b"".join(chunks).decode("utf-8", "replace")

    hit = next((b for b in BAD if b in text), None)
    if hit:
        line = next((l for l in text.splitlines() if hit in l), hit)
        return "FAIL", f"{line.strip()[:90]}"

    if killed:
        if label in LONG_RUNNING:
            # "slow" is fine; "silent" is not — a long runner must show progress.
            if not text.strip():
                return "FAIL", f"no output in {budget}s — hung, not just slow"
            return "OK", f"ran clean, {len(text)} chars out, killed at {budget}s"
        return "FAIL", f"did not exit within {budget}s (unexpected for this action)"

    if p.returncode != 0:
        if label in ONLINE:
            return "WARN", f"exit {p.returncode} (online action, may be network)"
        return "FAIL", f"exit {p.returncode}"
    return "OK", f"exit 0, {len(text)} chars out"


def main():
    w = gui.MainWindow()
    # Kangaroo needs a pubkey; use puzzle #70's real one so the builder succeeds.
    w.s_pubkey.setText("0290e6900a58d33393bc1097b5aed31f2e4e7cbd3e5466af958665bc0121248483")

    print("=" * 78)
    print(f"  Exercising {len(w.run_buttons)} action buttons")
    print("=" * 78)

    for btn in w.run_buttons:
        label = btn._label
        try:
            prog, args = btn._builder()
        except Exception as e:
            results.append((label, "FAIL", f"builder raised: {e}"))
            print(f"  [FAIL] {label:<38} builder raised: {e}")
            continue
        budget = 12 if label in LONG_RUNNING else 30
        verdict, detail = run_cmd(label, prog, args, budget)
        results.append((label, verdict, detail))
        print(f"  [{verdict:<4}] {label:<38} {detail}")

    # the Solve page has three modes; the loop above only covered the current one
    print("\n  -- Solve page modes --")
    for idx, name in ((0, "Solve/GPU lottery"), (1, "Solve/Kangaroo"), (2, "Solve/CPU")):
        w.s_mode.setCurrentIndex(idx)
        try:
            prog, args = w._build_solve()
        except Exception as e:
            results.append((name, "FAIL", f"builder raised: {e}"))
            print(f"  [FAIL] {name:<38} builder raised: {e}")
            continue
        verdict, detail = run_cmd(name, prog, args, 15)
        results.append((name, verdict, detail))
        print(f"  [{verdict:<4}] {name:<38} {detail}")

    # Kangaroo with an empty pubkey must be refused by the builder
    w.s_mode.setCurrentIndex(1); w.s_pubkey.setText("")
    try:
        w._build_solve()
        results.append(("Kangaroo empty-pubkey guard", "FAIL", "did not raise"))
        print("  [FAIL] Kangaroo empty-pubkey guard        did not raise")
    except ValueError:
        results.append(("Kangaroo empty-pubkey guard", "OK", "refused as expected"))
        print("  [OK  ] Kangaroo empty-pubkey guard        refused as expected")

    fails = [r for r in results if r[1] == "FAIL"]
    warns = [r for r in results if r[1] == "WARN"]
    print("\n" + "=" * 78)
    print(f"  {len(results)} actions | OK={len(results)-len(fails)-len(warns)} "
          f"WARN={len(warns)} FAIL={len(fails)}")
    for lbl, _, d in fails:
        print(f"    FAIL: {lbl} -> {d}")
    for lbl, _, d in warns:
        print(f"    WARN: {lbl} -> {d}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
