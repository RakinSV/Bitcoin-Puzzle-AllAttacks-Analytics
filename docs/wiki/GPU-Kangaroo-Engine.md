# GPU Kangaroo Engine

The compute core: a hand-written OpenCL implementation of **Pollard's Kangaroo** for the interval ECDLP on secp256k1. Given a public key `Q = k·G` with `k ∈ [a, b]`, it recovers `k` in `~2·√(b−a)` group operations instead of `b−a`.

Measured: **~631 Mhop/s sustained on an AMD RX 6600** (raw hop throughput).

> **⚠️ Known issue — the engine does not converge above ~37 bits.** Verified against
> real puzzles with their public keys: #30/#35/#37 are recovered correctly; #40, #45,
> #50 and #60 are not, each burning ~30–40x the required work without reporting a key.
> The "2–3 minutes for 71 bits" figure below was extrapolated from hop rate and was
> **never verified end-to-end** — it is not currently achievable. Under investigation.

## The kernel (`kangaroo/gpu_kangaroo.cl`)

256-bit modular arithmetic on a GPU that has no native big-integer support:

- **32×32→64 limb multiplication** via `mul_hi` / `mad_hi`, with the secp256k1 fast reduction (`lo += hi·(2³²+977)`, since `P = 2²⁵⁶ − 2³² − 977`).
- **Jacobian coordinates** — a point hop costs **11 field multiplies**, versus ~258 for a naive affine addition (which needs a modular inversion every hop).
- **Deferred / amortized inversion** — the single most expensive field op (a Fermat inversion ≈ 255 squarings) is done **once per 2,048 hops** by batching the affine conversion. Tuning this batch size (`STEPS_BATCH`) was worth a measured **+6%** (512 → 595 Mhop/s, 2048 → 631).
- **Negation map** — the map `(x,y) → (x,−y)` folds the search space in half for a **√2 speedup**, essentially free on secp256k1. The engine runs three herds: tame, wild, and negated-wild.
- **Distinguished Points** — trails are recorded only at points whose x has `dp_bits` trailing zero bits; the DP-bit budget is auto-tuned to the herd size to keep the GPU output buffer from overflowing.
- **Jump table in local memory (LDS)** — the precomputed jump points live in on-chip shared memory, not global VRAM.

The brute-force / BSGS mode (`kangaroo/gpu_search.py`) uses a vendored BitCrack kernel (`bitcrack.cl`, MIT) for secp256k1 + SHA-256 + RIPEMD-160 address derivation.

## The VRAM "performance cliff"

The most interesting discovery. A sweep over `threads × blocks × points-per-thread` showed throughput climbing smoothly to a peak around **31M parallel walkers (~406 Mkeys/s)** — then **collapsing ~4×** (to ~110 Mkeys/s) the instant the working set crossed **~33M** and blew the cache/allocator budget.

![VRAM cliff](https://raw.githubusercontent.com/RakinSV/Bitcoin-Puzzle-AllAttacks-Analytics/main/docs/vram_cliff_rx6600.png)

The shipped defaults had been sitting *past* the peak, on the downslope. Re-tuning to the safe side of the cliff was a free **+12%**. The bundled `--bench-sweep` now maps this curve and refuses to bench configurations beyond the cliff.

A counter-intuitive finding: raising the kangaroo herd 8× (24,576 → 196,608) only gained **+3%** — the kernel is so compute-heavy (2,048 hops per work-item per call) that the GPU is already saturated at the default herd. More kangaroos parallelize the *same* √-bounded total work; they don't reduce it.

## Feasibility, honestly

| Scenario | Work | Time on one RX 6600 |
|---|---|---|
| #71 with known pubkey | ~2³⁶ hops | *theoretical* ~2–3 min — **not achieved; engine stalls >37 bits** |
| #80 with known pubkey | ~2⁴⁰ hops | ~30 minutes |
| #90 with known pubkey | ~2⁴⁵ hops | ~hours–days |
| #125 / #130 (pubkeys exposed) | ~2⁶²⁺ hops | centuries |
| #71 blind brute force (no pubkey) | ~2⁶⁹ effort | ~tens of thousands of years |

This is why the realistic play is **sniping a freshly-exposed pubkey** in the 71–90 range — and why the kernel was tuned so hard for that block-race window.
