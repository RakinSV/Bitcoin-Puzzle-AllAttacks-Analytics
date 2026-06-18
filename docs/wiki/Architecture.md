# Architecture

## Package layout

```
ecc/                 secp256k1 from scratch — field, curve, GLV endomorphism
kangaroo/            Pollard's Kangaroo: CPU reference + custom OpenCL GPU engine
  gpu_kangaroo.cl      hand-written secp256k1 kernel (Jacobian, deferred inversion)
  bitcrack.cl          vendored BitCrack kernel (MIT) for the brute-force mode
  kangaroo_engine.py   GPU orchestrator (3-herd tame/wild/neg, distinguished points)
  gpu_search.py        GPU brute-force / BSGS mode + benchmarking
analysis/            nine independent cryptanalytic attacks
utils/               puzzle registry (all 150), address derivation, DP table, checkpoints
monitor.py           live mempool watcher (HTTP + WebSocket)
multi_sniper.py      watch ALL unsolved puzzles, snipe a pubkey, auto-fire Kangaroo
run_all_analyses.py  one command -> every analysis over all 150 puzzles -> reports/
main.py              unified solver CLI (gpu | cpu | kangaroo, any puzzle, bench)
app/gui.py           PySide6 desktop application
app_entry.py         single entry point: GUI by default, worker via --module/--cli
```

Pure **Python 3 + PyOpenCL**. No SciPy, no ML stack — even the statistics (the regularized incomplete gamma behind every χ² p-value) are implemented by hand.

## The one-binary GUI/worker model

The desktop app and the packaged executable share **one entry point**, `app_entry.py`, which plays two roles:

- **Launched normally** → opens the GUI (`app/gui.py`).
- **Launched with a worker marker** (`--cli`, `--run-analyses`, or `--module <name>`) → runs that tool and exits.

The GUI never runs heavy work in its own process. Instead it launches a **child worker** with `QProcess`, pointing at *itself*:

```
GUI  ──QProcess──►  <same binary> --module analysis.nist_randomness
                    <same binary> --module main --puzzle 71 --mode kangaroo --pubkey …
```

Why this matters:

1. **The UI never freezes** — long GPU runs happen in a separate process; output streams back over a pipe.
2. **It works identically in dev and frozen.** In dev the prefix is `python app_entry.py --module …`; in the PyInstaller build it's `<app>.exe --module …`. The frozen `.exe` is fully self-contained — no separate Python needed, because the GUI and every tool are the same binary.
3. **Uniform dispatch.** Every tool (solver, all analyses, sniper, monitor, bench) is reachable through one mechanism, so the GUI wiring is trivial: each button just builds an argv.

`--module <name>` uses `runpy.run_module(name, run_name="__main__")`, so any module with a normal `if __name__ == "__main__": main()` guard becomes runnable inside the frozen bundle — which is how the analysis scripts run with no interpreter present.

## Data & outputs

- **Reference data** (`known_keys.json`, `puzzle_pubkeys.json`, the puzzle registry) ships with the repo.
- **Caches** (puzzle status, fingerprints, DP tables) are written at runtime and git-ignored.
- **`reports/<timestamp>/`** — full analysis sweeps.
- **`logs/<timestamp>_<task>.log`** — every GUI run is mirrored to disk.

See **[GPU Kangaroo Engine](GPU-Kangaroo-Engine.md)** for the compute core and **[Problems & Solutions](Problems-and-Solutions.md)** for the non-obvious engineering decisions.
