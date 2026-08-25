"""
Checkpoint — сохранение и восстановление прогресса поиска.
Формат JSON, атомарная запись через временный файл.
"""

import json
import os
import time
from pathlib import Path


class Checkpoint:
    """Resume checkpoints and cumulative lottery stats, kept in SEPARATE files.

    They used to share one file, and the two writers disagree about what it
    means: save() records a resume position and omits `mode`, while the lottery
    records cumulative totals under `mode: pure-random`. load_lottery_totals()
    rejects any file without that mode, so a single CPU or linear-mode run —
    including the one the GUI button test performs — silently reset a lottery
    counter that had been accumulating for days.

    The lottery now writes alongside the checkpoint as `<name>_lottery.json`, so
    neither writer can destroy the other. An existing lottery-format checkpoint
    is imported once, so upgrading does not lose the totals already banked.
    """

    def __init__(self, path: str = 'checkpoint.json', puzzle: int = None):
        self.path = Path(path)
        self.puzzle = puzzle
        # Lottery totals are PER PUZZLE. One shared file meant switching target
        # silently poured the new puzzle's work into the old one's counter --
        # #89's keys landed on #71's tally, and neither number meant anything
        # afterwards. A file per puzzle keeps each history honest and lets you
        # go back to a target without having lost what you already did on it.
        suffix = '_lottery' if puzzle is None else '_lottery_p%d' % puzzle
        self.lottery_path = self.path.with_name(
            self.path.stem + suffix + self.path.suffix)
        self._migrate_legacy_lottery()

    def _migrate_legacy_lottery(self):
        """Adopt totals from an older, less specific file -- once.

        Two generations to inherit from: the original shared checkpoint.json, and
        the puzzle-agnostic <name>_lottery.json that replaced it. Either is only
        adopted when its recorded address matches this puzzle, so a mixed-target
        tally is never silently attributed to the wrong puzzle.
        """
        if self.lottery_path.exists():
            return
        want_addr = None
        if self.puzzle is not None:
            try:
                from utils.puzzle_registry import PUZZLE_ADDRESSES
                want_addr = PUZZLE_ADDRESSES.get(self.puzzle)
            except Exception:
                want_addr = None

        legacy = [self.path.with_name(self.path.stem + '_lottery'
                                      + self.path.suffix),
                  self.path]
        for src in legacy:
            if not src.exists():
                continue
            try:
                d = json.loads(src.read_text())
            except Exception:
                continue
            if not isinstance(d, dict) or d.get('mode') != 'pure-random':
                continue
            if want_addr and d.get('address') != want_addr:
                continue          # belongs to a different puzzle -- leave it
            try:
                self.lottery_path.write_text(json.dumps(d, indent=2))
            except Exception:
                pass
            return

    def save(self, k_current: int, k_start: int, k_end: int,
             address: str, keys_total: int, speed: float = 0.0):
        data = {
            'address':          address,
            'range_start':      hex(k_start),
            'range_end':        hex(k_end),
            'k_current':        hex(k_current),
            'k_current_dec':    k_current,
            'keys_searched':    keys_total,
            'progress_pct':     round(100.0 * (k_current - k_start) / max(k_end - k_start, 1), 6),
            'speed_mkeys_sec':  round(speed, 2),
            'saved_at':         time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        # Атомарная запись
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.path)

    def save_lottery_stats(self, address: str, k_start: int, k_end: int,
                           keys_total: int, windows: int, elapsed: float,
                           speed: float = 0.0):
        """Record cumulative work for pure-random lottery mode.

        Random sampling has no resume point and no linear progress, so storing
        `k_current`/`progress_pct` (as save() does) would be meaningless here.
        We record what was actually done instead, so the totals survive restarts.
        """
        data = {
            'mode':             'pure-random',
            'address':          address,
            'range_start':      hex(k_start),
            'range_end':        hex(k_end),
            'keys_searched':    keys_total,
            'windows':          windows,
            'elapsed_sec':      round(elapsed, 1),
            'speed_mkeys_sec':  round(speed, 2),
            'saved_at':         time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        # Own file: a resume-checkpoint write must never destroy these totals.
        tmp = self.lottery_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.lottery_path)

    def load_lottery_totals(self) -> tuple:
        """Prior (keys_searched, windows, elapsed_sec) so totals accumulate."""
        d = None
        if self.lottery_path.exists():
            try:
                d = json.loads(self.lottery_path.read_text())
            except Exception:
                d = None
        if d is None:                     # pre-split file, still lottery-shaped
            d = self.load()
        if not d or d.get('mode') != 'pure-random':
            return 0, 0, 0.0
        # The pre-split fallback is puzzle-agnostic, so it happily handed #71's
        # tally to #89. Whatever it returns must belong to THIS puzzle: a wrong
        # total is worse than none, because it looks authoritative.
        if self.puzzle is not None and d.get('address'):
            try:
                from utils.puzzle_registry import PUZZLE_ADDRESSES
                want = PUZZLE_ADDRESSES.get(self.puzzle)
            except Exception:
                want = None
            if want and d['address'] != want:
                return 0, 0, 0.0
        try:
            return (int(d.get('keys_searched', 0)), int(d.get('windows', 0)),
                    float(d.get('elapsed_sec', 0.0)))
        except Exception:
            return 0, 0, 0.0

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return None

    def get_resume_key(self, default: int) -> int:
        data = self.load()
        if data is None:
            return default
        try:
            return data.get('k_current_dec', int(data['k_current'], 16))
        except Exception:
            return default

    def print_status(self):
        data = self.load()
        if data is None:
            print("No checkpoint found.")
            return
        print(f"Checkpoint: {self.path}")
        print(f"  Address:   {data.get('address')}")
        print(f"  Progress:  {data.get('progress_pct', 0):.4f}%")
        print(f"  Current:   {data.get('k_current')}")
        print(f"  Speed:     {data.get('speed_mkeys_sec', 0):.1f} Mkeys/sec")
        print(f"  Saved at:  {data.get('saved_at')}")
