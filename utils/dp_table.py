"""
Distinguished Points (DP) table for Pollard's Kangaroo algorithm.

Idea (from Pons's HashTable + docx): instead of storing every visited point,
store only points where the lower DP_BITS bits of the x-coordinate are zero.
This reduces memory by 2^DP_BITS while only slightly increasing expected steps.

Entry: {x_truncated -> (distance_travelled, kangaroo_type)}
  distance_travelled: integer steps from start
  kangaroo_type: 'tame' or 'wild'

Collision detection:
  - Two entries with same x but different types → key found.
  - k = tame_dist - wild_dist + tame_start  (for tame starting at tame_start*G)
"""

import json
import time
from pathlib import Path


# Default: store points where x % 2^DP_BITS == 0
# DP_BITS=14 → 1/16384 points stored, memory ~N/16384 entries
DEFAULT_DP_BITS = 14
_DP_MASK_DEFAULT = (1 << DEFAULT_DP_BITS) - 1


class DPTable:
    """
    Distinguished Points table.

    is_dp(x)  → True if x & dp_mask == 0
    add(x, dist, kind) → None | (collision_dist, collision_kind)
    """

    def __init__(self, dp_bits: int = DEFAULT_DP_BITS, path: str | None = None):
        self.dp_bits  = dp_bits
        self.dp_mask  = (1 << dp_bits) - 1
        # table: x_coord (int) -> (distance, kind)
        self._table: dict[int, tuple[int, str]] = {}
        self.collisions = 0
        self.entries    = 0
        self.path       = Path(path) if path else None
        if self.path and self.path.exists():
            self._load()

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def is_dp(self, x: int) -> bool:
        """Return True if x is a Distinguished Point."""
        return (x & self.dp_mask) == 0

    def add(self, x: int, dist: int, kind: str) -> tuple | None:
        """
        Store a Distinguished Point. Returns collision tuple or None.

        Returns (other_dist, other_kind) if x was already in the table
        with a DIFFERENT kind (tame vs wild collision → key found).
        Returns None if same-kind duplicate (ignore) or new entry.
        """
        if x in self._table:
            other_dist, other_kind = self._table[x]
            if other_kind != kind:
                self.collisions += 1
                return (other_dist, other_kind)
            # Same kind — restart this kangaroo (pseudo-collision)
            return None
        self._table[x] = (dist, kind)
        self.entries += 1
        return None

    def resolve_key(self, tame_start: int,
                    tame_dist: int, wild_dist: int) -> int:
        """
        Given a tame-wild collision, compute the private key k.

        Math (standard Kangaroo):
          tame_pos = tame_start + tame_dist
          wild_pos = k + wild_dist   (wild starts at k*G = target Q)
          At collision: tame_pos == wild_pos
          => k = tame_start + tame_dist - wild_dist
        """
        return tame_start + tame_dist - wild_dist

    def clear(self):
        self._table.clear()
        self.entries    = 0
        self.collisions = 0

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return self.entries

    def stats(self) -> str:
        return (f"DP table: {self.entries:,} entries, "
                f"{self.collisions} collisions, "
                f"dp_bits={self.dp_bits} (1/{2**self.dp_bits} points)")

    # ------------------------------------------------------------------
    # Persistence  (optional, for checkpoint/resume of Kangaroo)
    # ------------------------------------------------------------------

    def save(self):
        if self.path is None:
            return
        data = {
            'dp_bits':    self.dp_bits,
            'entries':    self.entries,
            'collisions': self.collisions,
            'saved_at':   time.strftime('%Y-%m-%d %H:%M:%S'),
            # Store x as hex string, dist as int, kind as str
            'table': {hex(x): [d, k] for x, (d, k) in self._table.items()},
        }
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data))
        tmp.replace(self.path)

    def _load(self):
        try:
            data = json.loads(self.path.read_text())
            self.dp_bits    = data.get('dp_bits', self.dp_bits)
            self.dp_mask    = (1 << self.dp_bits) - 1
            self.collisions = data.get('collisions', 0)
            raw             = data.get('table', {})
            self._table     = {int(k, 16): (v[0], v[1]) for k, v in raw.items()}
            self.entries    = len(self._table)
        except Exception:
            self._table = {}
