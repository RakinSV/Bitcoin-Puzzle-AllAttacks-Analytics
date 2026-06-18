"""
CoverageMap - tracks which segments of the search range have been explored.

Divides [range_start, range_end] into segments of SEGMENT_SIZE keys.
Saves a JSON file listing covered segment indices so restarts avoid duplication.

Default segment = 2^50 keys  (~49 min at 381 Mkeys/sec per segment).
Total segments for puzzle #71: 2^70 / 2^50 = 2^20 = 1,048,576.
"""

import json
import random
import time
from pathlib import Path


SEGMENT_BITS = 50                    # keys per segment = 2^SEGMENT_BITS
SEGMENT_SIZE = 1 << SEGMENT_BITS     # 1,125,899,906,842,624


class CoverageMap:
    def __init__(self, path: str, range_start: int, range_end: int):
        self.path         = Path(path)
        self.range_start  = range_start
        self.range_end    = range_end
        self.total_segs   = (range_end - range_start + SEGMENT_SIZE) // SEGMENT_SIZE
        self.done: set    = set()   # set of completed segment indices
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
            self.done = set(data.get('done', []))
        except Exception:
            self.done = set()

    def _save(self):
        pct = 100.0 * len(self.done) / max(self.total_segs, 1)
        data = {
            'range_start':   hex(self.range_start),
            'range_end':     hex(self.range_end),
            'segment_bits':  SEGMENT_BITS,
            'total_segments': self.total_segs,
            'done_count':    len(self.done),
            'pct_covered':   round(pct, 6),
            'updated_at':    time.strftime('%Y-%m-%d %H:%M:%S'),
            'done':          sorted(self.done),
        }
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.path)

    # ------------------------------------------------------------------
    # Segment operations
    # ------------------------------------------------------------------

    def _seg_bounds(self, idx: int) -> tuple:
        start = self.range_start + idx * SEGMENT_SIZE
        end   = min(start + SEGMENT_SIZE - 1, self.range_end)
        return start, end

    def pick_random(self) -> tuple:
        """Return (seg_start, seg_end, seg_idx) for a random uncovered segment.

        Returns None if all segments are covered.
        """
        remaining = [i for i in range(self.total_segs) if i not in self.done]
        if not remaining:
            return None
        idx = random.choice(remaining)
        start, end = self._seg_bounds(idx)
        return start, end, idx

    def mark_done(self, seg_idx: int):
        self.done.add(seg_idx)
        self._save()

    def is_done(self, seg_idx: int) -> bool:
        return seg_idx in self.done

    def seg_index(self, k: int) -> int:
        return (k - self.range_start) // SEGMENT_SIZE

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def print_status(self):
        pct = 100.0 * len(self.done) / max(self.total_segs, 1)
        remaining = self.total_segs - len(self.done)
        print(f"Coverage file:  {self.path}")
        print(f"Range:          [{hex(self.range_start)}, {hex(self.range_end)}]")
        print(f"Segment size:   2^{SEGMENT_BITS} = {SEGMENT_SIZE:,} keys")
        print(f"Total segments: {self.total_segs:,}")
        print(f"Covered:        {len(self.done):,} ({pct:.4f}%)")
        print(f"Remaining:      {remaining:,}")
        # Time estimate at 381 Mkeys/sec
        sec_each = SEGMENT_SIZE / 381e6
        sec_left  = remaining * sec_each
        if sec_left < 3600:
            eta = f"{sec_left/60:.0f}m"
        elif sec_left < 86400:
            eta = f"{sec_left/3600:.1f}h"
        else:
            eta = f"{sec_left/86400:.1f}d"
        print(f"ETA (1x GPU):   {eta} for uncovered segments")
