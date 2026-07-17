#!/usr/bin/env python3
"""
Regression tests for lottery data collection.

The bug: the GPU lottery is always launched with --pure-random (both the GUI and
START_LOTTERY.bat do this), and that code path saved *nothing* — no checkpoint,
no coverage. The --checkpoint/--coverage flags were accepted but silently inert,
so closing the app threw away every record of the work done.

Random search has no meaningful resume point, so the fix records cumulative work
(keys tried, windows, elapsed) and accumulates it across restarts.

Run:  python tests/test_lottery_stats.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.checkpoint import Checkpoint          # noqa: E402

FAILS = []
ADDR = "1PWo3JeB9jrGwfHDNpdGK54CRas7fsVzXU"
LO, HI = 0x400000000000000000, 0x7fffffffffffffffff


def check(name, cond):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILS.append(name)


def test_round_trip():
    print("\n--- lottery stats round-trip ---")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "lot.json")
        chk = Checkpoint(p)
        check("no prior totals on a fresh file", chk.load_lottery_totals() == (0, 0, 0.0))
        chk.save_lottery_stats(ADDR, LO, HI, keys_total=1_000, windows=2,
                               elapsed=30.0, speed=400.0)
        check("stats file created", os.path.exists(p))
        d1 = json.load(open(p))
        check("tagged as pure-random mode", d1.get("mode") == "pure-random")
        check("keys recorded", d1.get("keys_searched") == 1_000)
        check("windows recorded", d1.get("windows") == 2)
        check("address recorded", d1.get("address") == ADDR)
        # a random search has no linear progress — must not claim one
        check("no misleading progress_pct", "progress_pct" not in d1)
        check("totals read back", chk.load_lottery_totals() == (1_000, 2, 30.0))


def test_accumulates_across_restarts():
    """A restart must add to prior work, not reset it."""
    print("\n--- totals accumulate across restarts ---")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "lot.json")
        chk = Checkpoint(p)
        chk.save_lottery_stats(ADDR, LO, HI, 5_000, 1, 10.0, 400.0)
        prior_keys, prior_windows, prior_elapsed = Checkpoint(p).load_lottery_totals()
        # simulate a second session doing 3_000 more keys / 1 more window / 10s
        Checkpoint(p).save_lottery_stats(ADDR, LO, HI,
                                         prior_keys + 3_000,
                                         prior_windows + 1,
                                         prior_elapsed + 10.0, 400.0)
        keys, windows, elapsed = Checkpoint(p).load_lottery_totals()
        check("keys accumulated", keys == 8_000)
        check("windows accumulated", windows == 2)
        check("elapsed accumulated", elapsed == 20.0)


def test_ignores_foreign_checkpoint():
    """A linear-mode checkpoint must not be read as lottery totals."""
    print("\n--- does not misread a linear checkpoint ---")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "chk.json")
        chk = Checkpoint(p)
        chk.save(k_current=LO + 5, k_start=LO, k_end=HI, address=ADDR,
                 keys_total=999, speed=1.0)          # linear-mode record
        check("linear checkpoint yields no lottery totals",
              chk.load_lottery_totals() == (0, 0, 0.0))
        check("linear checkpoint still resumes", chk.get_resume_key(0) == LO + 5)


def test_corrupt_file_is_survivable():
    print("\n--- corrupt stats file does not crash ---")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "lot.json")
        open(p, "w").write("{ this is not json")
        check("corrupt file -> zero totals", Checkpoint(p).load_lottery_totals() == (0, 0, 0.0))


if __name__ == "__main__":
    print("=" * 60)
    print("  Lottery data-collection regression tests")
    print("=" * 60)
    test_round_trip()
    test_accumulates_across_restarts()
    test_ignores_foreign_checkpoint()
    test_corrupt_file_is_survivable()
    print("\n" + "=" * 60)
    if FAILS:
        print(f"  {len(FAILS)} FAILED: {FAILS}")
        sys.exit(1)
    print("  ALL LOTTERY STATS TESTS PASSED [OK]")
