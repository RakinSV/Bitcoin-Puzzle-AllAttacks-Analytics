# Problems & Solutions

The engineering war stories — the non-obvious problems this project hit and how each was solved. This is where most of the real work lived.

## 1. The VRAM "performance cliff"

**Problem.** GPU throughput didn't scale monotonically with parallelism — past a certain point it *collapsed ~4×*.
**Diagnosis.** A `threads × blocks × points` sweep revealed a hard knee around **~33M work-items**: below it, ~406 Mkeys/s at the peak; just above it, ~110. The point working-set had blown the cache/allocator budget. The shipped defaults sat on the downslope past the peak.
**Solution.** Re-tuned the defaults to the safe side of the cliff (+12%), and made `--bench-sweep` map the curve and skip guaranteed-loser configs.

## 2. Kangaroo herd "saturation" myth

**Problem.** Intuition said more kangaroos = faster. **Measurement said otherwise:** 8× the herd (24,576 → 196,608) bought only **+3%**.
**Why.** Each work-item runs 2,048 hops per call, so the kernel saturates the GPU at the default herd. More kangaroos parallelize the *same* √-bounded total work — they don't reduce it.
**Solution.** Kept the herd modest; spent the effort on per-hop cost (inversion batching, +6%) instead.

## 3. Lottery kernel depended on a gitignored third-party tool

**Problem.** The brute-force mode loaded `BitCrack/CLKeySearchDevice/bitcrack.cl` — a path inside a third-party checkout we (correctly) gitignored. The published repo's lottery was silently broken, and it couldn't be packaged.
**Solution.** BitCrack is MIT-licensed, so we **vendored `bitcrack.cl` into `kangaroo/`** with attribution in `THIRD_PARTY_NOTICES.md`, and pointed the loader at the local copy (with a fallback). Repo and `.exe` are now self-contained.

## 4. PyInstaller bundle was 5.5 GB

**Problem.** The first packaged build was **5.5 GB**. PyInstaller had vacuumed up the entire global site-packages — **torch (4.4 GB)**, onnxruntime, cv2, transformers, scipy, pandas…
**Solution.** The app only needs PySide6 + pyopencl + numpy + requests. An aggressive `excludes` list in the spec dropped it to **~160 MB** (60 MB zipped). Confirmed none of the excluded libs are imported by app code first.

## 5. `OSError: [Errno 22] Invalid argument` on on-chain tools (frozen app)

**Problem.** In the packaged app, on-chain tools crashed at a plain `print()` with Errno 22 — but only when launched *from the GUI*, never from a console.
**Diagnosis.** A PyInstaller `--windowed` (no-console) build sets up fragile std streams. When the windowed GUI spawns a child worker via `QProcess`, writing to those streams can EINVAL on Windows. It worked from a real console (which provides valid stdio) but not on the GUI→child path.
**Solution.** In the worker branches of `app_entry.py`, re-open `stdout`/`stderr` as clean line-buffered UTF-8 streams over the real file descriptors, with a devnull fallback so a `print` can never crash a worker. Validated by reproducing the exact GUI→child path with a `QProcess` harness (exit 0, no error).

## 6. Running bundled scripts with no interpreter

**Problem.** `run_all_analyses` spawned `python analysis/foo.py` — but a frozen `.exe` has no Python to run arbitrary `.py` files.
**Solution.** A unified `--module <name>` dispatch in `app_entry.py` that uses `runpy.run_module(name, run_name="__main__")`. Any module with a normal `if __name__ == "__main__"` guard becomes runnable inside the bundle. The GUI and the sweep both invoke every tool this way, dev and frozen alike.

## 7. False-positive "KEY FOUND" banner

**Problem.** Found during live testing: running the on-chain *puzzle status* tool lit up the green "KEY FOUND" banner. The detector matched the bare word "SOLVED", which the status listing prints for every already-solved puzzle.
**Solution.** Tightened the detector to fire only on an actual recovered scalar (`Key = 0x…` / `FOUND k = 0x…` / `Private key (hex): 0x…`). Status listings no longer trigger it.

## 8. Per-card Run/Stop, not one global Stop

**Problem.** A single shared Stop button at the bottom was ambiguous with many actions on screen.
**Solution.** Each action's own button toggles to a red "■ Stop" while it runs (and siblings disable); it restores to "▶ Run" on completion. One source of truth per task.

## 9. Windows console encoding (cp1251)

**Problem.** Analysis scripts print Russian text; captured through subprocess pipes it mojibaked, and em-dashes showed as `?`.
**Solution.** Force `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8` in the worker environment and decode captured bytes as UTF-8 (cp1251 fallback). Reports and the log panel are clean UTF-8.

## 10. The `!` in the project path

**Problem.** The project lives under `C:\!Ai-My!\!bitcoin-search`. Windows batch `enabledelayedexpansion` mangles `!` in paths.
**Solution.** Avoided delayed expansion in the batch files entirely.

See **[Future Ideas](Future-Ideas.md)** for what's next.
