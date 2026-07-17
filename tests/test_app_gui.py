#!/usr/bin/env python3
"""
Regression tests for the desktop GUI (app/gui.py).

Each test guards a bug that actually shipped and made the app look dead:

  1. A worker that fails to START never emits finished() -> the UI used to stay
     "running" with every button disabled, forever. (CRITICAL)
  2. In a frozen build, logs/reports were written inside the bundle (_internal)
     instead of next to the executable, so users never found them.
  3. A real key find had its SOLVED status clobbered by the finish handler.
  4. There was no way to stop a task from a different page.

Run:  python tests/test_app_gui.py
"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication          # noqa: E402
from PySide6.QtCore import QTimer                   # noqa: E402

import app.gui as gui                               # noqa: E402

APP = QApplication.instance() or QApplication([])
FAILS = []


def check(name, cond):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILS.append(name)


def pump(predicate, timeout=20.0):
    """Run the Qt event loop until predicate() or timeout."""
    end = time.time() + timeout
    while time.time() < end and not predicate():
        APP.processEvents()
        time.sleep(0.01)
    return predicate()


# ---------------------------------------------------------------------------
def test_failed_start_releases_ui():
    """BUG 1: a worker that cannot start must not freeze the UI forever."""
    print("\n--- failed worker start releases the UI ---")
    w = gui.MainWindow(); w.show(); APP.processEvents()   # show(): isVisible() is meaningless otherwise
    btn, other = w.run_buttons[0], w.run_buttons[1]
    w.active_btn = btn
    w.start(os.path.join(os.sep, "no", "such", "program_xyz.exe"), ["--nope"], "bogus")

    released = pump(lambda: w.proc is None, timeout=15)
    check("UI released (proc cleared) after failed start", released)
    check("other buttons re-enabled", other.isEnabled())
    check("active button restored to Run", btn.text().strip().startswith("▶"))
    check("status-bar Stop hidden again", not w.stop_bar.isVisible())
    w.close()


def test_found_status_survives_finish():
    """BUG 3: a real find must keep SOLVED, not be overwritten by 'done'."""
    print("\n--- SOLVED status survives process finish ---")
    w = gui.MainWindow()
    w.found_key = False
    w._parse("[!] Puzzle #71 SOLVED! Key = 0xdeadbeef")
    check("banner shows the key", "0xdeadbeef" in w.found.text())
    check("found_key flag set", w.found_key is True)
    w._release("done", ok=True)          # simulate the finish handler
    check("status still SOLVED after release", w.stat_status.text() == "SOLVED")
    w.close()


def test_status_listing_does_not_false_trigger():
    """A puzzle-status listing prints 'SOLVED' but must NOT claim a key find."""
    print("\n--- status listings do not fake a key find ---")
    w = gui.MainWindow()
    for line in ("  #  6  SOLVED  balance=0.0000 BTC 1Pit...",
                 "  Solved: 64   Unsolved: 86"):
        w._parse(line)
    check("no banner text", w.found.text() == "")
    check("found_key not set", w.found_key is False)
    w.close()


def test_data_root_separates_from_bundle():
    """BUG 2: frozen builds must write user output next to the exe."""
    print("\n--- frozen data root is next to the executable ---")
    real_frozen = getattr(sys, "frozen", False)
    real_exe, real_meipass = sys.executable, getattr(sys, "_MEIPASS", None)
    try:
        sys.frozen = True
        sys._MEIPASS = os.path.join("X:", os.sep, "app", "_internal")
        sys.executable = os.path.join("X:", os.sep, "app", "BitcoinPuzzle.exe")
        code, data = gui._code_root(), gui._data_root()
        check("code root points into the bundle", code.endswith("_internal"))
        check("data root is the exe folder (not _internal)",
              data == os.path.join("X:", os.sep, "app") and "_internal" not in data)
    finally:
        if not real_frozen:
            del sys.frozen
        sys.executable = real_exe
        if real_meipass is None:
            if hasattr(sys, "_MEIPASS"):
                del sys._MEIPASS
        else:
            sys._MEIPASS = real_meipass


def test_busy_guard_does_not_start_second_process():
    """Clicking another action while busy must not spawn a second worker."""
    print("\n--- busy guard ---")
    w = gui.MainWindow(); w.show(); APP.processEvents()
    btn = [b for b in w.run_buttons if b._label == "List OpenCL devices"][0]
    w._toggle(btn)
    first = w.proc
    check("first task started", first is not None)
    check("status-bar Stop visible while running", w.stop_bar.isVisible())
    w.start("whatever", [], "second")           # must be ignored while busy
    check("no second process replaced the first", w.proc is first)
    w.stop()
    pump(lambda: w.proc is None, timeout=15)
    w.close()


if __name__ == "__main__":
    print("=" * 60)
    print("  Desktop GUI regression tests")
    print("=" * 60)
    test_failed_start_releases_ui()
    test_found_status_survives_finish()
    test_status_listing_does_not_false_trigger()
    test_data_root_separates_from_bundle()
    test_busy_guard_does_not_start_second_process()
    print("\n" + "=" * 60)
    if FAILS:
        print(f"  {len(FAILS)} FAILED: {FAILS}")
        sys.exit(1)
    print("  ALL GUI REGRESSION TESTS PASSED [OK]")
