# Theories Tested — Methodology & Verdicts

Every idea anyone has ever floated for "shortcutting" the Bitcoin Puzzle, tested properly and recorded honestly. Each section states the **hypothesis**, the **math/method** used to test it, the **tool** in this repo, and the **verdict**.

The headline result: **the puzzle creator used genuine cryptographic randomness.** None of the shortcuts exist. The value of this document is that it says so with evidence, not vibes — and it shows the work.

---

## 1. Weak RNG / predictable seed

**Hypothesis.** The creator generated all keys from a single seeded pseudo-random generator — `random.Random(seed)`, an LCG, or similar. If so, recovering the seed (or the generator's internal state) yields *every* key at once.

**Method.**
- Treat each known key as a draw and inspect the distribution of its *normalized position* within its interval `[2^(N-1), 2^N)`. A seeded PRNG often leaves detectable structure (mean drift, serial correlation, low-entropy seeds).
- Brute-search small seed spaces for `random.Random(seed)` and common LCG parameterizations, reproducing the first known keys.
- Look for arithmetic/geometric relations between consecutive keys (`k_n = a·k_{n-1} + b`).

**Tool.** `analysis/rng_analysis.py` (`--quick`, `--predict`, `--segments`).

**Verdict.** ❌ No predictable seed. Normalized positions are uniform (mean ≈ 0.52, no serial correlation), no small seed reproduces the sequence, no linear recurrence fits. Keys are independent and uniform within their intervals.

---

## 2. BIP32 / HD-wallet derivation

**Hypothesis.** The keys are children of a single BIP32 master seed — e.g. `m/0/N` gives puzzle #N. Recover the master and derive everything.

**Method.** Test whether known keys satisfy BIP32 child-derivation relations (hardened and non-hardened) for plausible paths; check whether key #N is consistent with being the N-th child of any candidate master.

**Tool.** `analysis/bip32_analysis.py` (`--test-all`, `--target N`, `--master-key`).

**Verdict.** ❌ No HD structure. The keys are not BIP32 children of any common master under the tested paths. (This matches the puzzle creator's own later statements that keys were chosen by truncating a single random draw, not derived.)

---

## 3. Brainwallet / passphrase

**Hypothesis.** `privkey = SHA256(passphrase)` for some human-memorable passphrase ("bitcoin71", "puzzle", etc.).

**Method.** A dictionary attack: hash a large list of candidate passphrases and transformations, derive the address, and compare. Crucially, the attack is **first validated against all 70 known keys** — if the method can't recover a single known puzzle key, it won't recover an unknown one either.

**Tool.** `analysis/brainwallet_attack.py` (`--target N`, `--wordlist`, `--validate-only`). The wordlist is public-domain common-knowledge passphrases, not reproduced from any single copyrighted source.

**Verdict.** ❌ No brainwallet. Zero of the 70 known keys are the SHA-256 of any tested passphrase. The keys are raw random integers, not hashes of words.

---

## 4. ECDSA nonce reuse / leakage

**Hypothesis.** When the creator (or solvers) *spent* from puzzle addresses, they signed with ECDSA. If two signatures reused the same nonce `k`, the private key is recoverable in closed form. Even partial nonce leakage (a few known bits across many signatures) is exploitable via a **lattice attack**.

**Method.**
- Harvest the creator's / solvers' signatures from the blockchain (`r`, `s`, message hash).
- Check for repeated `r` values (full nonce reuse → instant key recovery).
- Build a hidden-number-problem lattice and run **LLL reduction** to recover keys from biased/partially-known nonces.

**Tool.** `analysis/nonce_attack.py` (`--quick`, `--lll`, `--lll-bits`, `--txid`).

**Verdict.** ❌ No reused or detectably-biased nonces in the harvested signatures. The signers used proper RFC-6979-style deterministic nonces (or otherwise unbiased randomness).

---

## 5. Public-key EC-point patterns

**Hypothesis.** The *public* keys (available for solved/spent puzzles) are related as curve points — e.g. `P_{N+1} = 2·P_N`, or `P_N = N·P_1`, or some linear/multiplicative relation that would let you compute an unknown pubkey and then Kangaroo it.

**Method.** Harvest exposed public keys from chain, then test for additive/multiplicative/doubling relations between consecutive and arbitrary pairs.

**Tool.** `analysis/pubkey_pattern.py` (`--collect`, `--analyze-only`).

**Verdict.** ❌ No structural relation. The public keys are exactly what independent random scalars produce — no exploitable EC-point pattern.

---

## 6. Creator fingerprinting — who owns what

**Hypothesis.** Even without breaking a key, on-chain behavior reveals *which keys share an owner*, and the creator's funding/spending patterns might leak timing or structural hints.

**Method.** Two tiers of evidence:
- **Heuristic clustering** — destination-address reuse, fee fingerprints, and spend-timing histograms.
- **Common-input-ownership (cryptographic proof)** — if two puzzle keys ever appear as inputs to the *same* transaction, the same entity provably controlled both at signing time. This is not a guess; it's a property of how Bitcoin transactions are authorized.

**Tool.** `analysis/creator_fingerprint.py` (`--deep`).

**Verdict.** ⚠️ Informative, not exploitable. The deep pass found genuine co-spent clusters (provable shared ownership of several solved keys) and a strong temporal fingerprint (spends heavily concentrated in one UTC hour). This tells a story about *who solved what and when* — but it yields **no information about unsolved keys**, which is the cryptographically correct outcome.

---

## 7. NIST SP 800-22 randomness battery

**Hypothesis.** The key bits, taken as a bitstream, are non-random in a way a formal test can detect (and therefore exploit).

**Method.** Run the standard NIST statistical test suite on the concatenated free bits of the 70 known keys:
- **Monobit** (frequency), **Runs**, **Poker / block-frequency**, **Serial autocorrelation**, plus position-uniformity (χ²) and runs-about-median tests.
- All p-values computed from a **hand-implemented regularized incomplete gamma function** (`Q(a,x)` via series + continued-fraction expansions) — no `scipy` dependency. This was a deliberate exercise in implementing the numerics correctly.

**Tool.** `analysis/nist_randomness.py`.

**Verdict.** ❌ Indistinguishable from random. All tests pass at p ≥ 0.01 across 2,415 free bits. There is no statistical bias to exploit.

---

## 8. "Ghost-solved" re-verification

**Hypothesis.** A puzzle widely *listed* as solved might (a) still hold its BTC (the prize was never actually swept), and/or (b) already have an **exposed public key** from a spend — which would make it Kangaroo-able even at higher bit-widths.

**Method.** Ignore third-party "solved" lists; query the blockchain directly for each of #75…#130. `balance == 0` → genuinely swept; `balance > 0` → still claimable; any spend-from → pubkey exposed.

**Tool.** `analysis/ghost_solved_check.py`.

**Verdict.** ⚠️ All re-checked puzzles still hold their funds, and #125 (≈13.5 BTC) and #130 (≈14.0 BTC) **do** have exposed public keys. But at 125–130 bits, Pollard's Kangaroo needs ~2^62–2^65 operations — roughly **hundreds to thousands of years** on a single consumer GPU. Real, but out of reach without a cluster.

---

## 9. Multi-puzzle mempool sniper

**Hypothesis.** This isn't a weakness in the keys — it's a *race*. Whenever anyone spends from an unsolved puzzle address, its public key is broadcast to the mempool ~10 minutes before the transaction confirms. With a known pubkey in the 71–90 range, a pre-warmed Kangaroo can recover the key and broadcast a competing transaction **first**.

**Method.** A WebSocket watcher subscribes to mempool activity for *all* unsolved puzzle addresses simultaneously. On a pubkey exposure it instantly hands off to the pre-compiled, pre-warmed GPU Kangaroo (zero init latency). Detection latency < 1 second.

**Tool.** `multi_sniper.py`, `monitor.py`, `run_all.py`.

**Verdict.** ✅ This is the *one* scenario where a single RX 6600 can realistically win — which is exactly why the GPU kernel was tuned so hard. For 71–90-bit pubkeys, recovery (2–3 min to ~hours) fits inside the block race.

---

## The bottom line

Eight of nine theories are **falsified with evidence**; the ninth (sniping) is an operational tactic, not a cryptographic break. The puzzle is honest: the keys are genuinely random, and the only doors are brute force (a lottery), Kangaroo-on-exposed-pubkey (a race), or a cluster you don't have. Knowing this — rigorously — is worth more than another year of blind brute force.
