# Attacks & Theories

Nine independent attacks, each a falsifiable hypothesis about how the puzzle keys *might* be weak. The full write-ups (math + method + verdict) live in [`docs/THEORIES.md`](https://github.com/RakinSV/Bitcoin-Puzzle-AllAttacks-Analytics/blob/main/docs/THEORIES.md); this is the map.

| # | Attack | Hypothesis | Verdict |
|---|--------|-----------|---------|
| 1 | **RNG analysis & prediction** | Keys from a seeded PRNG (Mersenne Twister / LCG) | ❌ uniform, no seed reproduces them |
| 2 | **BIP32 / HD-wallet** | Keys are children of one master seed (`m/0/N`) | ❌ no derivation relation |
| 3 | **Brainwallet** | `privkey = SHA256(passphrase)` | ❌ zero of 70 known keys match |
| 4 | **ECDSA nonce reuse** | A signing nonce `k` was reused/leaked → lattice/LLL recovery | ❌ no reused/biased nonces |
| 5 | **Pubkey EC-point patterns** | Public keys are linearly/multiplicatively related | ❌ no structural relation |
| 6 | **Creator fingerprinting** | Which keys share an owner (common-input-ownership) | ⚠️ proves shared ownership of *solved* keys; nothing about unsolved |
| 7 | **NIST SP 800-22 battery** | The key bits are non-random | ❌ all tests pass (p ≥ 0.01) |
| 8 | **Ghost-solved re-verification** | A "solved" puzzle still holds BTC / exposed a pubkey | ⚠️ #125 & #130 expose pubkeys but are 100+ bits |
| 9 | **Multi-puzzle mempool sniper** | Win the race when a rival exposes a pubkey | ✅ the one realistically winnable path |

## Why the negative results matter

Eight of nine are **falsified with evidence**; the ninth is an operational tactic, not a cryptographic break. That's the whole point: the puzzle creator used genuine randomness, so the keys are exactly as hard as the math says. Knowing this *rigorously* — with real p-values (NIST), cryptographic proof (common-input-ownership), and direct on-chain checks — saves you from burning ~35,000 GPU-years chasing a shortcut that doesn't exist.

## Techniques on display

- **Statistical cryptanalysis** — a full NIST SP 800-22 battery with χ² p-values from a hand-implemented regularized incomplete gamma function (no SciPy).
- **Lattice reduction** — the hidden-number-problem / LLL formulation for partial-nonce ECDSA recovery.
- **On-chain forensics** — common-input-ownership as cryptographic proof of shared control, plus fee/timing fingerprints.
- **Number theory** — seeded-PRNG state recovery, BIP32 child-key derivation, EC point-relation testing.

## What ties them together

Each attack is a standalone CLI module under `analysis/`, runnable on its own, from the desktop app, or in bulk via `run_all_analyses.py` (which sweeps every attack across all 150 puzzles and writes the results to `reports/`). See **[Desktop App](Desktop-App.md)** for the GUI and **[GPU Kangaroo Engine](GPU-Kangaroo-Engine.md)** for the compute core that the sniper relies on.
