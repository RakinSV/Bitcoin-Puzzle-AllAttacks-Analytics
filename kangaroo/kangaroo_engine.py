"""
GPU Kangaroo Engine — Python orchestrator for gpu_kangaroo.cl

Implements Pollard's Kangaroo on AMD RX 6600 via PyOpenCL.
Requires the TARGET PUBLIC KEY (x, y).

Usage:
    engine = KangarooEngine(pubkey=(x,y), k_start=2**70, k_end=2**71-1)
    k = engine.solve()   # returns int or None

Speed estimate:
    Base Kangaroo:    ~150 Msteps/sec (GPU point additions)
    + Negation map:   x2  -> ~300 Msteps/sec effective
    + GLV in kernel:  x1.7 (faster scalar init)
    Expected: O(2.5 * sqrt(range)) steps / speed => time

For puzzle #71 (range 2^70):
    sqrt(2^70) ~ 2^35 = 34.4 billion steps
    At 300 Msteps/sec => ~115 seconds expected (if pubkey known)
"""

import sys
import os
import time
import numpy as np
import pyopencl as cl
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ecc.curve   import scalar_mul, point_add, point_double, point_neg, G, N, INF
from ecc.glv     import scalar_mul_glv   # 1.5-1.7x faster scalar mul
from utils.dp_table import DPTable

_HERE   = Path(__file__).parent
_KERNEL = _HERE / 'gpu_kangaroo.cl'

# ---- GPU configuration ----
# The herds are spread randomly across the interval (see initialize()), giving
# bounded ~10*sqrt(W) work (verified on a 40->58 bit ladder). Offset points are
# computed ON THE GPU (off*G by summing 2^j*G over set bits), so a large herd
# still initialises in ~0.1s — and a large herd both saturates the GPU (much
# higher hop-rate) and cuts run-to-run variance. Measured: #50 10s, #55 70s,
# #58 ~5min on one RX 6600.
N_TAME      = 8192     # tame kangaroos
N_WILD      = 8192     # wild kangaroos (+ same for neg)
W_SIZE      = 32       # jump table size
# Kernel geometry — MUST mirror gpu_kangaroo.cl.
# A kangaroo's affine x only exists after the deferred inversion at a batch
# boundary, so DP is sampled every STEPS_BATCH hops, not every hop. A large
# STEPS_BATCH (e.g. 2048) made a genuine collision detectable only ~1/STEPS_BATCH
# of the time (phase-alignment) so the solver never reported. 32 keeps DP
# sampling frequent enough to detect collisions while amortising the inversion.
STEPS_BATCH = 32       # hops between affine conversions (= DP sampling points)
N_BATCHES   = 64       # batches per kernel call  (STEPS_CALL = 2048)
STEPS_CALL  = STEPS_BATCH * N_BATCHES   # hops per kernel call
DP_BITS     = 0        # 0 = auto-pick from the range (see _auto_dp_bits)
MAX_DP_OUT  = 4096     # max DP results per kernel call


def _auto_dp_bits(n_total: int, rng_size: int) -> int:
    """Choose dp_bits so DP detection doesn't dominate the solve.

    A kangaroo records a DP roughly every STEPS_BATCH * 2^dp_bits hops, so after
    the herds collide it takes about n_total * STEPS_BATCH * 2^dp_bits hops for
    the collision to actually be *noticed*. The collision itself costs only
    ~2*sqrt(rng_size). With a fixed dp_bits=14 that detection tail was ~100x the
    collision cost on mid-size puzzles — the search worked but never reported.

    Aim for detection ~15% of the collision cost, clamped to a sane range.
    """
    import math
    collision = 2.0 * math.sqrt(max(rng_size, 2))
    target    = 0.15 * collision / max(1, n_total * STEPS_BATCH)
    return int(max(1, min(24, round(math.log2(max(target, 2.0))))))


def _int_to_u256(k: int) -> np.ndarray:
    arr = np.zeros(8, dtype=np.uint32)
    for i in range(7, -1, -1):
        arr[i] = k & 0xFFFFFFFF
        k >>= 32
    return arr


def _u256_to_int(arr) -> int:
    v = 0
    for x in arr:
        v = (v << 32) | int(x)
    return v


class KangarooEngine:
    """
    GPU Kangaroo solver.

    Parameters
    ----------
    pubkey    : (x, y) int tuple — the target EC point.
                Pass None for pre-warm mode (compile kernel without pubkey).
                Call solve(pubkey=...) later when pubkey is known.
    k_start   : lower bound of search range
    k_end     : upper bound of search range
    device_idx: OpenCL GPU device index
    n_tame    : number of tame kangaroos (default 8192)
    n_wild    : number of wild kangaroos (default 8192; same for neg)
    dp_bits   : distinguished point filter bits (default 14)

    Pre-warm usage (fastest response when pubkey found):
        engine = KangarooEngine(pubkey=None, k_start=2**70, k_end=2**71-1,
                                n_tame=16384, n_wild=16384)
        # ... later when pubkey is discovered:
        k = engine.solve(pubkey=(x, y))
    """

    def __init__(self, pubkey,   # tuple or None
                 k_start: int, k_end: int,
                 device_idx: int = 0,
                 n_tame: int = N_TAME, n_wild: int = N_WILD,
                 dp_bits: int = DP_BITS):
        self.pubkey   = pubkey
        self.k_start  = k_start
        self.k_end    = k_end
        self.n_tame   = n_tame
        self.n_wild   = n_wild
        self.n_total  = n_tame + n_wild * 2   # tame + wild + neg

        # dp_bits=0 (the default) means "pick a good one for this range".
        if not dp_bits:
            dp_bits = _auto_dp_bits(self.n_total, k_end - k_start + 1)
            print(f"[KangarooGPU] dp_bits auto-selected: {dp_bits} "
                  f"(DP every ~{STEPS_BATCH * (1 << dp_bits):,} hops/kangaroo)")

        # Guard the GPU output buffer. DPs are emitted only at batch boundaries,
        # so a call produces at most n_total * N_BATCHES / 2^dp_bits of them.
        # (The old constraint used STEPS_CALL here, as if every hop were sampled.
        # That demanded ~11 bits more than necessary, made DPs ~2000x too sparse
        # and let post-collision detection dominate the whole solve.)
        import math as _math
        _min_dp = max(1, _math.ceil(_math.log2(
            max(1, self.n_total * N_BATCHES / MAX_DP_OUT))))
        if dp_bits < _min_dp:
            print(f"[KangarooGPU] dp_bits={dp_bits} too small for "
                  f"n_total={self.n_total} — auto-adjusted to {_min_dp}")
            dp_bits = _min_dp
        self.dp_bits  = dp_bits
        self.dp_mask  = (1 << dp_bits) - 1   # lower dp_bits mask

        # OpenCL setup
        platforms = cl.get_platforms()
        devices   = [d for p in platforms for d in p.get_devices(cl.device_type.GPU)]
        if device_idx >= len(devices):
            raise RuntimeError(f"No GPU device {device_idx}")
        self.device = devices[device_idx]
        self.ctx    = cl.Context([self.device])
        self.queue  = cl.CommandQueue(self.ctx)

        print(f"[KangarooGPU] {self.device.name}")
        print(f"[KangarooGPU] n_tame={n_tame}  n_wild={n_wild}  "
              f"n_neg={n_wild}  total={self.n_total}")
        print(f"[KangarooGPU] dp_bits={dp_bits}  W={W_SIZE}  "
              f"steps/call={STEPS_CALL}")

        self._compile()
        self._build_jump_table()
        self._alloc_buffers()

    # ------------------------------------------------------------------
    # Kernel compilation
    # ------------------------------------------------------------------

    def _compile(self):
        src = _KERNEL.read_text(encoding='utf-8')
        try:
            self.prog = cl.Program(self.ctx, src).build(
                options='-cl-mad-enable -cl-fast-relaxed-math'
            )
        except cl.RuntimeError as e:
            print(f"[KangarooGPU] Build error: {e}")
            raise
        self._kern_step = cl.Kernel(self.prog, 'kangarooStep')
        self._kern_init = cl.Kernel(self.prog, 'initKangaroos')
        print("[KangarooGPU] Kernel compiled OK.")

    # ------------------------------------------------------------------
    # Jump table: j*G for j=1..W_SIZE
    # ------------------------------------------------------------------

    def _build_jump_table(self):
        """
        Jump distances scaled to sqrt(range)/2 — theoretically optimal for Kangaroo.
        W evenly-spaced values from mean/W to 2*mean - mean/W, mean = sqrt(range)/2.
        """
        rng_size = self.k_end - self.k_start + 1
        mean     = max(W_SIZE, int(rng_size ** 0.5) // 2)
        print(f"[KangarooGPU] Building jump table ({W_SIZE} points, "
              f"mean_dist=2^{mean.bit_length()-1})...")

        jx = np.zeros(W_SIZE * 8, dtype=np.uint32)
        jy = np.zeros(W_SIZE * 8, dtype=np.uint32)
        jd = np.zeros(W_SIZE, dtype=np.uint64)

        for j in range(W_SIZE):
            d  = max(1, mean * (2 * j + 1) // W_SIZE)
            pt = scalar_mul(d, G)        # GLV neutral in Python; gains only in OCL kernel
            jx[j*8:(j+1)*8] = _int_to_u256(pt[0])
            jy[j*8:(j+1)*8] = _int_to_u256(pt[1])
            jd[j] = d

        self.jx_host = jx
        self.jy_host = jy
        self.jd_host = jd

    # ------------------------------------------------------------------
    # Buffer allocation
    # ------------------------------------------------------------------

    def _alloc_buffers(self):
        mf = cl.mem_flags
        N  = self.n_total

        # Per-kangaroo state
        self.px_buf   = cl.Buffer(self.ctx, mf.READ_WRITE, N * 8 * 4)
        self.py_buf   = cl.Buffer(self.ctx, mf.READ_WRITE, N * 8 * 4)
        self.dist_buf = cl.Buffer(self.ctx, mf.READ_WRITE, N * 8)   # ulong
        self.kind_buf = cl.Buffer(self.ctx, mf.READ_WRITE, N * 4)   # int

        # Jump table (constant)
        self.jx_buf   = cl.Buffer(self.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR,
                                   hostbuf=self.jx_host)
        self.jy_buf   = cl.Buffer(self.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR,
                                   hostbuf=self.jy_host)
        self.jd_buf   = cl.Buffer(self.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR,
                                   hostbuf=self.jd_host)

        # DP results
        dp_size = MAX_DP_OUT * (8*4 + 8 + 4 + 4)   # x[8]+dist+kind+tid
        self.dp_buf  = cl.Buffer(self.ctx, mf.WRITE_ONLY, dp_size)
        self.cnt_buf = cl.Buffer(self.ctx, mf.READ_WRITE, 4)  # int n_results

        mb = (N * 8 * 4 * 2 + N * 8 + N * 4 + W_SIZE * 8 * 4 * 2 + dp_size) / 1024 / 1024
        print(f"[KangarooGPU] VRAM allocated: {mb:.1f} MB")

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self):
        """Random-spread initialisation.

        Each kangaroo gets an INDEPENDENT random offset across the interval:
            tame[tid] = k_start + off ,  wild = Q + off ,  neg = -Q + off
        so the herds are scattered over the whole range. Validated in the herd
        model (tests/_herd_model.py): random spread gives BOUNDED ~10*sqrt(W)
        work, while the old clustered/uniform layout did not scale past ~40 bits.
        Each kangaroo's initial distance is exactly its offset, so the
        reconstruction invariant position == (origin + dist)*G still holds.
        """
        import random
        print("[KangarooGPU] Initializing kangaroos (random spread)...")
        rng_size  = self.k_end - self.k_start + 1
        tame_base = self.k_start
        self._tame_base = tame_base

        tb_pt = scalar_mul(tame_base, G)
        tb_x  = _int_to_u256(tb_pt[0]); tb_y = _int_to_u256(tb_pt[1])
        qx = _int_to_u256(self.pubkey[0]); qy = _int_to_u256(self.pubkey[1])

        # Precompute the 2^j*G table on the host (just nbits doublings). The GPU
        # then builds each kangaroo's off*G by summing table entries over off's
        # set bits — so init is O(nbits) on the host regardless of herd size,
        # and a large herd no longer means a slow init.
        nbits = rng_size.bit_length()
        p2x = np.zeros(nbits * 8, dtype=np.uint32)
        p2y = np.zeros(nbits * 8, dtype=np.uint32)
        pt = G
        for j in range(nbits):
            p2x[j*8:(j+1)*8] = _int_to_u256(pt[0])
            p2y[j*8:(j+1)*8] = _int_to_u256(pt[1])
            pt = point_double(pt)

        # Per-kangaroo random offsets (fast — no EC math on the host).
        n = self.n_total
        print(f"[KangarooGPU] Random offsets for {n} kangaroos (GPU-side off*G)...")
        idist = np.array([random.randrange(1, rng_size) for _ in range(n)],
                         dtype=np.uint64)

        mf = cl.mem_flags
        tb_x_buf  = cl.Buffer(self.ctx, mf.READ_ONLY|mf.COPY_HOST_PTR, hostbuf=tb_x)
        tb_y_buf  = cl.Buffer(self.ctx, mf.READ_ONLY|mf.COPY_HOST_PTR, hostbuf=tb_y)
        qx_buf    = cl.Buffer(self.ctx, mf.READ_ONLY|mf.COPY_HOST_PTR, hostbuf=qx)
        qy_buf    = cl.Buffer(self.ctx, mf.READ_ONLY|mf.COPY_HOST_PTR, hostbuf=qy)
        p2x_buf   = cl.Buffer(self.ctx, mf.READ_ONLY|mf.COPY_HOST_PTR, hostbuf=p2x)
        p2y_buf   = cl.Buffer(self.ctx, mf.READ_ONLY|mf.COPY_HOST_PTR, hostbuf=p2y)
        id_buf    = cl.Buffer(self.ctx, mf.READ_ONLY|mf.COPY_HOST_PTR, hostbuf=idist)

        self._kern_init.set_args(
            np.int32(self.n_tame), np.int32(self.n_wild), np.int32(nbits),
            tb_x_buf, tb_y_buf, qx_buf, qy_buf,
            p2x_buf, p2y_buf,
            self.px_buf, self.py_buf, self.dist_buf, self.kind_buf,
            id_buf
        )
        cl.enqueue_nd_range_kernel(self.queue, self._kern_init,
                                   (self.n_total,), None)
        self.queue.finish()
        self._iteration  = 0
        print(f"[KangarooGPU] Initialized. tame_base={hex(tame_base)}")

    # ------------------------------------------------------------------
    # One search step
    # ------------------------------------------------------------------

    def step(self) -> list:
        """
        Run STEPS_CALL hops for all kangaroos.
        Returns list of DPResult dicts for any DP hits.
        """
        # Reset DP counter
        zero = np.zeros(1, dtype=np.int32)
        cl.enqueue_copy(self.queue, self.cnt_buf, zero)

        self._kern_step.set_args(
            np.int32(self.n_total),
            self.px_buf, self.py_buf, self.dist_buf, self.kind_buf,
            self.jx_buf, self.jy_buf, self.jd_buf,
            np.uint32(self.dp_mask & 0xFFFFFFFF),
            self.dp_buf, self.cnt_buf
        )
        cl.enqueue_nd_range_kernel(self.queue, self._kern_step,
                                   (self.n_total,), None)
        self.queue.finish()
        self._iteration += 1
        return self._read_dp()

    # ------------------------------------------------------------------
    # Read DP results from GPU
    # ------------------------------------------------------------------

    def _read_dp(self) -> list:
        cnt_host = np.zeros(1, dtype=np.int32)
        cl.enqueue_copy(self.queue, cnt_host, self.cnt_buf)
        self.queue.finish()
        n = int(cnt_host[0])
        if n == 0:
            return []
        n = min(n, MAX_DP_OUT)

        # Each DPResult: x[8] uint32 + dist ulong + kind int + tid int
        # = 32 + 8 + 4 + 4 = 48 bytes
        entry_bytes = 8*4 + 8 + 4 + 4   # DPResult: x[8] + dist + kind + tid = 48 bytes
        buf_host = np.zeros(n * entry_bytes, dtype=np.uint8)
        # pyopencl >= 2024: byte_count parameter removed;
        # copy size is determined by hostbuf size (n * entry_bytes here).
        cl.enqueue_copy(self.queue, buf_host, self.dp_buf)
        self.queue.finish()

        results = []
        for i in range(n):
            off = i * entry_bytes
            x_arr = np.frombuffer(buf_host[off:off+32], dtype=np.uint32)
            x_val = _u256_to_int(x_arr)
            dist  = int(np.frombuffer(buf_host[off+32:off+40], dtype=np.uint64)[0])
            kind  = int(np.frombuffer(buf_host[off+40:off+44], dtype=np.int32)[0])
            results.append({'x': x_val, 'dist': dist, 'kind': kind})
        return results

    # ------------------------------------------------------------------
    # Full solver
    # ------------------------------------------------------------------

    def precompute_tame(self, save_path: str = 'tame_dps.pkl',
                        n_iters: int = 4000) -> int:
        """
        Pre-compute tame kangaroo Distinguished Points without knowing the pubkey.

        Tame kangaroos start at tame_base + i*offset and depend ONLY on
        [k_start, k_end] — NOT on the pubkey. So we can run them offline
        and save their DPs to disk.

        Load later via solve(tame_dp_file=save_path):
            - Pre-seeds DP table with saved tame DPs
            - Only wild kangaroos need to generate new DPs
            - First collision happens ~2x sooner → ~2x faster solve

        Args:
            save_path : where to save the pickle file
            n_iters   : GPU kernel call iterations (each call = n_total × STEPS_CALL hops)
                        Default 4000 → ~4000 × 24576 × 2048 ≈ 200B tame hops
        """
        import pickle
        from pathlib import Path

        print(f"\n[PrecomputeTame] Starting tame DP collection...")
        print(f"[PrecomputeTame] n_tame={self.n_tame}  dp_bits={self.dp_bits}  "
              f"n_iters={n_iters}")
        expected_dps = n_iters * self.n_tame * STEPS_CALL >> self.dp_bits
        print(f"[PrecomputeTame] Expected tame DPs: ~{expected_dps:,}")

        # Use dummy pubkey — tame kangaroos don't depend on it
        saved_pubkey = self.pubkey
        self.pubkey  = G          # any valid EC point
        self.initialize()
        self.pubkey  = saved_pubkey

        tame_dps: dict[int, int] = {}   # x_coord → distance
        t0 = time.time()

        for i in range(n_iters):
            dp_hits = self.step()
            for hit in dp_hits:
                if hit['kind'] == 0:    # tame only
                    tame_dps[hit['x']] = hit['dist']

            if (i + 1) % 200 == 0:
                elapsed = time.time() - t0
                speed   = (i + 1) * self.n_total * STEPS_CALL / elapsed / 1e6
                print(f"\r  [{i+1}/{n_iters}]  tame_dps={len(tame_dps):,}  "
                      f"speed={speed:.0f}M/s  elapsed={elapsed:.0f}s",
                      end='', flush=True)

        elapsed = time.time() - t0
        print(f"\n[PrecomputeTame] Collected {len(tame_dps):,} tame DPs in {elapsed:.1f}s")

        data = {
            'tame_dps': tame_dps,
            'k_start':  self.k_start,
            'k_end':    self.k_end,
            'dp_bits':  self.dp_bits,
            'n_tame':   self.n_tame,
            'n_iters':  n_iters,
            'saved_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        with open(save_path, 'wb') as f:
            pickle.dump(data, f, protocol=4)

        size_kb = Path(save_path).stat().st_size / 1024
        print(f"[PrecomputeTame] Saved -> {save_path}  ({size_kb:.0f} KB)")
        print(f"[PrecomputeTame] Use with: engine.solve(tame_dp_file='{save_path}')")
        return len(tame_dps)

    def solve(self, pubkey=None, max_iter: int = 0,
              checkpoint_every: int = 1000,
              tame_dp_file: str = None,
              verbose: bool = True) -> int | None:
        """
        Run Kangaroo until collision found or max_iter reached.
        Returns private key k (int) or None.

        pubkey : override the pubkey set in __init__. Useful for pre-warm mode:
                 engine = KangarooEngine(pubkey=None, ...)  # warm up
                 k = engine.solve(pubkey=(x,y))              # fire instantly
        """
        if pubkey is not None:
            self.pubkey = pubkey
        if self.pubkey is None:
            raise ValueError("[KangarooGPU] pubkey not set. "
                             "Pass pubkey to solve() or __init__.")
        self.initialize()
        dp = DPTable(dp_bits=self.dp_bits)

        # ── Pre-seed DP table with pre-computed tame DPs (optional) ──────────
        if tame_dp_file:
            from pathlib import Path as _Path
            import pickle as _pickle
            if _Path(tame_dp_file).exists():
                with open(tame_dp_file, 'rb') as _f:
                    _saved = _pickle.load(_f)
                _pre = _saved.get('tame_dps', {})
                # Validate dp_bits compatibility:
                # DPs collected at saved_dp_bits are valid as long as saved_dp_bits
                # <= current dp_bits, because any point passing the stricter
                # current dp_bits filter (more bits = 0) is also a valid DP at
                # the saved (less strict) dp_bits level — the x-coord lookup still
                # works correctly.
                _saved_dp = _saved.get('dp_bits', self.dp_bits)
                if _saved_dp > self.dp_bits:
                    print(f"[KangarooGPU] WARNING: tame_dp_file dp_bits={_saved_dp} "
                          f"> current dp_bits={self.dp_bits} — skipping "
                          f"(saved DPs too strict for current filter)")
                else:
                    if _saved_dp != self.dp_bits:
                        print(f"[KangarooGPU] NOTE: tame_dp_file dp_bits={_saved_dp} "
                              f"< current {self.dp_bits} — using anyway "
                              f"(subset compatibility OK)")
                    for _x, _d in _pre.items():
                        dp._table[_x] = (_d, 'tame')
                    dp.entries = len(dp._table)
                    print(f"[KangarooGPU] Pre-seeded {len(_pre):,} tame DPs "
                          f"from {tame_dp_file}")
                    print(f"[KangarooGPU] Wild kangaroos need only ONE collision "
                          f"with {len(_pre):,} pre-loaded tame DPs -> ~2x faster!")
            else:
                print(f"[KangarooGPU] tame_dp_file not found: {tame_dp_file} — ignoring")

        rng_size      = self.k_end - self.k_start + 1
        # Random-spread herd typically solves in ~100*sqrt(W) hops here (the
        # deferred-inversion DP phase factor inflates the textbook 2*sqrt(W)),
        # but it is a Las Vegas algorithm with a heavy tail — unlucky runs were
        # measured out past 600*sqrt(W). Budget at ~300*sqrt(W) (x5 below =
        # ~1500*sqrt(W) of headroom) so a correct pubkey reliably solves; a
        # single long run beats restarting, since DPs accumulate.
        # (The old 2.5*sqrt(W) made the solver give up before the collision —
        #  the real cause of "stalls above 40 bits".)
        expected      = int(300 * (rng_size ** 0.5))
        total_hops    = 0
        hops_per_call = self.n_total * STEPS_CALL
        # max_hops must cover both the collision-finding phase AND the DP-detection
        # phase that follows.  The kernel checks dp_mask every STEPS_BATCH=512 hops
        # (N_BATCHES=4 checks per kernel call), so after two kangaroos collide the
        # expected additional kernel calls until the DP fires is
        #   2^dp_bits / N_BATCHES = 2^dp_bits / 4
        # and that costs (2^dp_bits / 4) * hops_per_call extra total hops.
        # Without this term, max_hops is often smaller than the detection overhead,
        # causing the solver to give up before the collision is ever reported.
        # A kangaroo can only be sampled for a DP at a batch boundary, so it
        # records one every STEPS_BATCH * 2^dp_bits hops; detecting a collision
        # costs about that much for every kangaroo in the herd.
        # (This used a hardcoded STEPS_CALL // 512 — stale since STEPS_BATCH
        #  changed — which understated the cost by 4x.)
        _dp_detect_hops = self.n_total * STEPS_BATCH * (1 << self.dp_bits)
        if max_iter == 0:
            # 5× safety on (collision + detection) – P(fail) ≈ e^{-5} ≈ 0.7 %
            max_hops = max((expected + _dp_detect_hops) * 5, hops_per_call * 200)
        else:
            max_hops = max_iter * hops_per_call
        t0 = time.time()

        if verbose:
            # Rough ETA: assume ~500 Mhops/s on RX 6600 (conservative)
            _est_mhops  = 500.0
            _solve_s    = expected        / (_est_mhops * 1e6)
            _detect_s   = _dp_detect_hops / (_est_mhops * 1e6)
            _total_s    = _solve_s + _detect_s
            _max_s      = max_hops / (_est_mhops * 1e6)
            print(f"\n[Kangaroo] Solving...")
            print(f"  Range:    [{hex(self.k_start)}, {hex(self.k_end)}]  "
                  f"({rng_size.bit_length()-1} bits)")
            print(f"  Expected: ~{expected:,} collision hops  +  "
                  f"~{_dp_detect_hops:,} detect hops")
            print(f"  Kangaroos:{self.n_total} ({self.n_tame}T "
                  f"{self.n_wild}W {self.n_wild}N)")
            print(f"  ETA (RX6600 ~{_est_mhops:.0f}M/s): "
                  f"solve={_solve_s:.0f}s  detect={_detect_s:.0f}s  "
                  f"expected~{_total_s:.0f}s ({_total_s/60:.1f}min)  "
                  f"max={_max_s:.0f}s ({_max_s/60:.1f}min)")

        iteration = 0
        while total_hops < max_hops:
            dp_hits = self.step()
            total_hops += self.n_total * STEPS_CALL
            iteration  += 1

            for hit in dp_hits:
                col = dp.add(hit['x'], hit['dist'], _kind_str(hit['kind']))
                if col:
                    k = self._try_recover(hit, col, dp)
                    if k is not None:
                        elapsed = time.time() - t0
                        if verbose:
                            print(f"\n[Kangaroo] FOUND k = {hex(k)}")
                            print(f"  Hops: {total_hops:,}  Time: {elapsed:.2f}s")
                            print(f"  Speed: {total_hops/elapsed/1e6:.1f} Mhops/sec")
                        return k

            if verbose and iteration % 50 == 0:
                elapsed = time.time() - t0
                speed   = total_hops / elapsed / 1e6 if elapsed > 0 else 0
                print(f"\r  iter={iteration:,}  "
                      f"hops={total_hops:,}  "
                      f"dp={len(dp)}  "
                      f"speed={speed:.0f}M/s  ",
                      end='', flush=True)

        if verbose:
            print(f"\n[Kangaroo] Not found in {total_hops:,} hops.")
        return None

    def _herd_affine(self, kind: str, dist: int) -> tuple | None:
        """A kangaroo's discrete log expressed as (a, b) meaning a*k + b (mod N).

        Verified against the GPU state: position == (start + dist)*G exactly, and
        dist is pre-loaded with the per-kangaroo offset at init.
            tame : starts at tame_base  ->  0*k + (tame_base + dist)
            wild : starts at  Q =  k*G  ->  1*k + dist
            neg  : starts at -Q = -k*G  -> -1*k + dist
        """
        if kind == 'tame':
            return 0, (self._tame_base + dist) % N
        if kind == 'wild':
            return 1, dist % N
        if kind == 'neg':
            return N - 1, dist % N          # -1 mod N
        return None

    def _try_recover(self, hit: dict, col: tuple, dp: DPTable) -> int | None:
        """Recover k from an x-coordinate collision between two kangaroos.

        A DP records only the x-coordinate, and x is shared by both P and -P, so a
        match means the two discrete logs are equal *up to sign*:

            a1*k + b1  ==  s * (a2*k + b2)     for s = +1 or -1

        which solves to k = (s*b2 - b1) / (a1 - s*a2) mod N. Every candidate is
        then verified against the real pubkey, so a wrong branch costs nothing.

        The previous code tried a single formula per herd pair (and dropped
        wild/neg pairs entirely), so genuine collisions produced garbage keys —
        the herds met, the key was never reported, and the search ran forever.
        """
        from ecc.curve import scalar_mul as _mul, G as _G

        h1 = self._herd_affine(_kind_str(hit['kind']), hit['dist'])
        h2 = self._herd_affine(col[1], col[0])
        if h1 is None or h2 is None:
            return None
        a1, b1 = h1
        a2, b2 = h2

        for s in (1, N - 1):                     # the +P / -P ambiguity
            A = (a1 - s * a2) % N
            B = (s * b2 - b1) % N
            if A == 0:
                continue                          # no information from this pair
            k = (B * pow(A, -1, N)) % N
            if self.k_start <= k <= self.k_end and _mul(k, _G) == self.pubkey:
                return k
        return None


def _kind_str(kind_int: int) -> str:
    return ['tame', 'wild', 'neg'][kind_int] if kind_int in (0, 1, 2) else 'unknown'
