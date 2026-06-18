# Desktop App

A native PySide6/Qt application that exposes the **entire** toolkit — solver, every attack, on-chain recon, live watchers, and GPU tooling — with live status, streaming logs, and disk logging.

![Dashboard](https://raw.githubusercontent.com/RakinSV/Bitcoin-Puzzle-AllAttacks-Analytics/main/docs/screens/dashboard.png)

## Sections

| Section | What's in it |
|---|---|
| **Dashboard** | Data-status checks + one-click "first-time full research" |
| **Solve** | GPU lottery · Pollard's Kangaroo (known pubkey) · CPU reference |
| **Offline analyses** | RNG (quick/predict/segments), BIP32, brainwallet, NIST, run-all-150 |
| **On-chain recon** | Puzzle status, ghost-solved, creator fingerprint (deep), nonce attack, pubkey patterns |
| **Live watch** | Multi-puzzle mempool sniper · single-puzzle monitor (WebSocket) |
| **GPU tools** | List devices · benchmark · benchmark sweep |
| **Reports & logs** | Open the reports/ and logs/ folders, list recent runs |

![Solve](https://raw.githubusercontent.com/RakinSV/Bitcoin-Puzzle-AllAttacks-Analytics/main/docs/screens/solve.png)
![On-chain recon](https://raw.githubusercontent.com/RakinSV/Bitcoin-Puzzle-AllAttacks-Analytics/main/docs/screens/onchain.png)

## Behaviors worth knowing

- **The action's own button becomes Stop.** When you start a task, that card's button turns red ("■ Stop") and the others disable — there is no separate global stop. Click it again to stop that task.
- **Everything is logged to disk.** Every run streams to the panel *and* to `logs/<timestamp>_<task>.log`.
- **First-run research.** On launch with no data (no reports, no status cache), the app offers to run the full sweep across all 150 puzzles automatically.
- **Live status bar** — status, speed (Mhop/s or Mkeys/s), hops/keys, distinguished points, elapsed time, and the current task, parsed live from the worker output.

## How it runs work (the one-binary model)

The GUI never does heavy work in-process. It launches a **child worker** via `QProcess`, pointing at *itself* with a `--module <name>` marker (see [Architecture](Architecture.md)). This keeps the UI responsive, streams output over a pipe, and — crucially — means the packaged `.exe` is fully self-contained: GUI and every tool are the same binary, no separate Python at runtime.

## Packaging & distribution

- **PyInstaller** (`BitcoinPuzzle.spec`, onedir) builds a ~160 MB bundle. An aggressive `excludes` list keeps unrelated heavy libraries out (see [Problems & Solutions](Problems-and-Solutions.md) — it was 5.5 GB before that).
- **GitHub Actions** (`.github/workflows/build.yml`) builds Windows `.exe` and Linux binaries on every `v*` tag and attaches them to a Release. Windows can't cross-compile a Linux binary, so each OS builds on its own native runner.
- **End users need only an OpenCL GPU driver** (AMD/NVIDIA) — no Python install required.

Run from source: `pip install PySide6 pyopencl numpy requests` then `python app_entry.py` (or `RUN_APP.bat`).
