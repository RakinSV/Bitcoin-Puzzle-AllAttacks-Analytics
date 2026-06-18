"""
Checkpoint — сохранение и восстановление прогресса поиска.
Формат JSON, атомарная запись через временный файл.
"""

import json
import os
import time
from pathlib import Path


class Checkpoint:
    def __init__(self, path: str = 'checkpoint.json'):
        self.path = Path(path)

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
