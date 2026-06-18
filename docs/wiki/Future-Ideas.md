# Future Ideas

Where this project could go next — a mix of performance, scale, and product ideas.

## Performance (the GPU core)

- **Dedicated modular squaring.** A specialized `sqrModP` (diagonal terms once, off-diagonal doubled) is ~30–40% cheaper than a general multiply. With 3 squarings in each mixed addition and 255 in every inversion, this is a realistic few-percent per-hop win and a bigger win for inversion.
- **Montgomery batched inversion.** Instead of one deferred inversion per batch, invert *many* points at once with the Montgomery trick (one inversion + 3 muls per element). Would let the affine conversion happen more often without the inversion cost.
- **Multi-GPU.** The herd partitions trivially across devices; distinguished points already give a clean merge point. A second GPU ≈ 2× throughput.
- **Auto-tuning at startup.** Ship the `--bench-sweep` curve detection as a one-time auto-calibration so each card runs at its own peak (and stays off its own VRAM cliff).

## Scale (distributed Kangaroo)

- **Client/server distinguished-point pool.** A lightweight server collects DPs from many workers (different machines) and watches for a tame/wild collision. This is how large puzzles (#100+) actually get solved — by pooling, not by one card. The DP table and serialization are already in place; it needs a network protocol and a coordinator.
- **Resumable / checkpointed runs.** Persist the DP set so a multi-day run survives restarts (partial support exists via the checkpoint module).

## The sniper / mempool race

- **Sub-second WebSocket everywhere.** Generalize the single-puzzle WebSocket monitor to the multi-puzzle sniper so *all* unsolved addresses are watched in real time, not polled.
- **Pre-warmed multi-target Kangaroo.** Keep kernels compiled and VRAM allocated for several bit-widths so the handoff from "pubkey seen" to "solving" is truly zero-latency.
- **Fee/replacement strategy.** Once a key is recovered mid-race, craft and broadcast a competing transaction with an appropriate fee — the actual "winning" step — with explicit human confirmation.

## Product / polish

- **Signed binaries + auto-update.** Code-sign the Windows `.exe` (no SmartScreen warning) and add an update check against the Releases API.
- **Charts in the GUI.** A live throughput sparkline and a DP-accumulation curve in the status bar (the data is already streamed).
- **In-app report viewer.** Render `reports/` summaries inside the app instead of opening the folder.
- **Config profiles.** Save/restore GPU parameter sets per device.

## Research directions

- **Endomorphism for rho-on-subgroup.** GLV doesn't speed up interval Kangaroo, but it does help Pollard's rho on the full group order — worth exploring for non-interval targets.
- **Smarter jump functions.** Adaptive mean jump distance tuned to the interval width, and experiments with the number of jump-table entries vs. collision efficiency.
- **More on-chain heuristics.** Extend the creator fingerprint with change-address heuristics and clustering across exchanges to better characterize who is solving what, when.

> Contributions welcome — the codebase is modular (each attack is a standalone CLI module, the engine is isolated, the GUI is a thin front-end), so most of these can be added without touching the core.
