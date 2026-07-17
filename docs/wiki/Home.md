# Bitcoin Puzzle — All Attacks & Analytics

A from-scratch research toolkit for the [Bitcoin Puzzle Transaction](https://privatekeys.pw/puzzles/bitcoin-puzzle-tx): 150 addresses, each hiding a private key inside a known numeric range (puzzle **#N** → key in `[2^(N-1), 2^N)`). This project treats the puzzle as an applied exercise in **elliptic-curve cryptography, parallel GPU computing, and statistical cryptanalysis** — and attacks it from every honest angle at once.

It is also a study in **intellectual honesty**: most "shortcuts" people imagine for these puzzles don't exist, and this toolkit *proves* they don't, with real tests, real p-values, and real on-chain evidence.

## Wiki contents

- **[Architecture](Architecture.md)** — how the codebase is organized and how the one-binary GUI/worker model works.
- **[GPU Kangaroo Engine](GPU-Kangaroo-Engine.md)** — the custom OpenCL secp256k1 kernel, the optimizations, and the VRAM "performance cliff."
- **[Attacks & Theories](Attacks-and-Theories.md)** — the nine independent cryptanalytic attacks and their verdicts.
- **[Desktop App](Desktop-App.md)** — the PySide6 application, packaging, and CI.
- **[Problems & Solutions](Problems-and-Solutions.md)** — the real engineering problems we hit and how we solved them.
- **[Future Ideas](Future-Ideas.md)** — where this could go next.

## TL;DR results

- A **hand-written OpenCL Pollard's Kangaroo engine** runs at **~631 Mhop/s on an old AMD RX 6600**. ⚠️ **Known issue:** it converges up to ~40 bits today (verified: #30/#37/#40 solve — #40 in ~20s after a reconstruction fix; #45+ do not, see issue #1). The often-quoted "71 bits in 2–3 minutes" was extrapolated from hop rate and is **not currently true**.
- **Nine attacks** all agree the puzzle creator used **genuine randomness** — no RNG/HD-wallet/brainwallet/nonce shortcut exists. Knowing that *rigorously* is the real payoff.
- The only realistically winnable scenario on one consumer GPU is **sniping a freshly-exposed public key** from the mempool — which is exactly why the kernel was tuned so hard.

> **Disclaimer.** The Bitcoin Puzzle is a public, intentional challenge — the creator funded these addresses specifically to be solved. This project is for education and security research only.
