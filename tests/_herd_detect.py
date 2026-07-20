#!/usr/bin/env python3
"""
Isolate the DETECTION penalty. The geometry model (_herd_bigm) shows random
spread is ~5*sqrtW at m=8192 with per-hop DP at dp~4. But the GPU measures
~234*sqrtW on #52. The difference must be DETECTION:
  (a) STEPS_BATCH=32 -> DP is only sampled at batch boundaries (phase penalty).
  (b) dp is force-floored to 9 by MAX_DP_OUT=4096 (denser DP needs a bigger buf).

This reruns the SAME random-spread geometry but tests DP only every `steps_batch`
hops (mirroring the GPU's deferred inversion), sweeping (steps_batch, dp) so we
can read off exactly how many sqrtW each configuration costs. If (32, 9) ~ 234
and (1, 4) ~ 5, then per-hop DP + denser dp (batch inversion + bigger buffer) is
the real, large win.  Run:  python tests/_herd_detect.py
"""
import os, sys, time, random, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ecc.curve import N as ORDER
from tests._herd_model import xr, build_dists, _mix, _recover

_HALF = ORDER // 2
N_JUMP = 32


def run_det(bits, m, dp_bits, steps_batch, cap_mult, k):
    """Random spread; DP tested only when a kangaroo's hop index % steps_batch==0."""
    k_start, k_end = 2 ** (bits - 1), 2 ** bits - 1
    W = k_end - k_start + 1
    dists = build_dists(W)
    dp_mask = (1 << dp_bits) - 1
    tame_base = k_start
    offs = [random.randrange(0, W) for _ in range(m)]

    kang = []  # [scalar, kind, hopcount]
    for off in offs:
        kang.append([(tame_base + off) % ORDER, 'tame', 0])
        kang.append([(k + off) % ORDER, 'wild', 0])
        kang.append([(ORDER - k + off) % ORDER, 'neg', 0])

    def origin(kind):
        return {'tame': tame_base, 'wild': k, 'neg': ORDER - k}[kind]

    table = {}
    hops = 0
    cap = int(cap_mult * (W ** 0.5))
    while hops < cap:
        for kg in kang:
            s, kind, hc = kg
            if hc % steps_batch == 0:            # DP only sampled at batch bound.
                r = xr(s)
                h = _mix(r)
                if (h & dp_mask) == 0:
                    prev = table.get(r)
                    if prev is not None and prev[1] != kind:
                        kk = _recover(prev, (s - origin(kind), kind), tame_base, k)
                        if kk == k:
                            return True, hops
                    elif prev is None:
                        table[r] = (s - origin(kind), kind)
            h2 = _mix(xr(s))
            idx = (h2 >> 17) % N_JUMP
            kg[0] = (s + dists[idx]) % ORDER
            kg[2] = hc + 1
            hops += 1
    return False, hops


def main():
    random.seed(11)
    m = 8192
    bits = 34
    W = 2 ** (bits - 1)
    s = W ** 0.5
    print("=" * 74)
    print(f"  DETECTION sweep — random spread, m={m}, {bits} bits (sqrtW={s:,.0f})")
    print(f"  cost in *sqrtW for (steps_batch, dp).  GPU currently runs (32, 9).")
    print("=" * 74, flush=True)
    configs = [
        (1, 4), (1, 6), (1, 9),
        (8, 6), (8, 9),
        (32, 6), (32, 9),
        (32, 4),
    ]
    for sb, dp in configs:
        mult, uns = [], 0
        t = time.time()
        for _ in range(2):
            k = random.randrange(2 ** (bits - 1), 2 ** bits)
            ok, hops = run_det(bits, m, dp, sb, cap_mult=500, k=k)
            (mult.append(hops / s) if ok else 0)
            uns += (0 if ok else 1)
            if time.time() - t > 100:
                break
        tag = f"steps_batch={sb:<3} dp={dp}"
        if mult:
            print(f"  {tag:<22}: {statistics.mean(mult):7.1f}*sqrtW "
                  f"(n={len(mult)}, {uns} uns)  [{time.time()-t:.0f}s]", flush=True)
        else:
            print(f"  {tag:<22}: UNSOLVED @500*sqrtW  [{time.time()-t:.0f}s]",
                  flush=True)


if __name__ == "__main__":
    main()
