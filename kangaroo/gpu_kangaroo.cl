/**
 * GPU Kangaroo Kernel v2 -- Jacobian coordinates
 * AMD RX 6600 (RDNA2 / gfx1032) via OpenCL
 *
 * Key improvements over v1:
 *   1. Jacobian mixed addition: 11 muls/hop  (was 258 = 1 inversion + 3 muls)
 *   2. Inversion only every STEPS_BATCH hops (deferred affine conversion)
 *   3. Jump table cached in __local memory (32 KB LDS on RDNA2)
 *   4. STEPS_PER_CALL = STEPS_BATCH * N_BATCHES = 32 * 64 = 2048
 *      (STEPS_BATCH kept small so DP is sampled often enough to DETECT a
 *       collision — a large batch makes detection ~1/STEPS_BATCH likely)
 *   5. secp256k1 mulModP ported from BitCrack (proven correct)
 *   6. #pragma unroll on all 8-wide field loops
 *
 * Measured speed on RX 6600 (2026-06, puzzle #70, herd 24576):
 *   ~631 Mhops/sec sustained. STEPS_BATCH tuning: 512=595, 1024=623,
 *   2048=631 Mhop/s (inversion amortized over more hops; diminishing).
 *   Herd is already GPU-saturated: 8x more kangaroos = only +3% hop-rate.
 *   Effective cost ~ 11 + 255/2048 ~= 11.1 muls/hop.
 *
 * Memory layout (global):
 *   px[N*8], py[N*8]     : affine positions (uint32[8] each), Z=1 implicit
 *   dist[N]              : distance travelled (uint64)
 *   kind[N]              : 0=tame, 1=wild, 2=neg_wild
 *   jx[W*8], jy[W*8]     : jump table affine points (constant)
 *   jdist[W]             : jump distances (uint64)
 *   dp_results[MAX_DP]   : DP hits written by GPU
 *   n_results            : atomic counter for dp_results
 */

#pragma OPENCL EXTENSION cl_khr_int64_base_atomics : enable

/* uint and ulong are built-in OpenCL types; do not redefine them */
/* typedef unsigned int  uint;  */
/* typedef unsigned long ulong; */

/* ====================================================================
   secp256k1 field prime  P = 2^256 - 2^32 - 977
   Group order           N (for reference; not used in kernel)
   ==================================================================== */

__constant uint _P[8] = {
    0xFFFFFFFF,0xFFFFFFFF,0xFFFFFFFF,0xFFFFFFFF,
    0xFFFFFFFF,0xFFFFFFFF,0xFFFFFFFE,0xFFFFFC2F
};

/* ====================================================================
   32-bit carry helpers
   ==================================================================== */

static inline uint _addc(uint a, uint b, uint *carry) {
    uint s  = a + *carry;
    uint c1 = (s < a) ? 1u : 0u;
    s      += b;
    uint c2 = (s < b) ? 1u : 0u;
    *carry  = c1 | c2;
    return s;
}

static inline uint _subc(uint a, uint b, uint *borrow) {
    uint d   = a - *borrow;
    *borrow  = (d > a) ? 1u : 0u;
    uint d2  = d - b;
    *borrow |= (d2 > d) ? 1u : 0u;
    return d2;
}

/* madd977:  *high:*low = a*977 + c  (32*32 -> 64, plus c) */
static inline void _madd977(uint *high, uint *low, uint a, uint c) {
    *low  = a * 977u;
    uint tmp = *low + c;
    uint carry = (tmp < *low) ? 1u : 0u;
    *low  = tmp;
    *high = mad_hi(a, 977u, carry);
}

/* madd: *high:*low = a*b + c */
static inline void _madd(uint *high, uint *low, uint a, uint b, uint c) {
    *low  = a * b;
    uint tmp = *low + c;
    uint carry = (tmp < *low) ? 1u : 0u;
    *low  = tmp;
    *high = mad_hi(a, b, carry);
}

/* ====================================================================
   256-bit field arithmetic (secp256k1 prime P)
   ==================================================================== */

/* r = a + b mod P  (a,b < P) */
static void addModP(uint r[8], const uint a[8], const uint b[8]) {
    uint carry = 0;
    #pragma unroll 8
    for (int i = 7; i >= 0; i--) r[i] = _addc(a[i], b[i], &carry);
    /* if carry or r >= P: subtract P */
    bool gt = carry;
    if (!gt) {
        #pragma unroll 8
        for (int i = 0; i < 8; i++) {
            if (r[i] > _P[i]) { gt = true; break; }
            if (r[i] < _P[i]) break;
        }
    }
    if (gt) {
        uint bw = 0;
        #pragma unroll 8
        for (int i = 7; i >= 0; i--) r[i] = _subc(r[i], _P[i], &bw);
    }
}

/* r = a - b mod P */
static void subModP(uint r[8], const uint a[8], const uint b[8]) {
    uint bw = 0;
    #pragma unroll 8
    for (int i = 7; i >= 0; i--) r[i] = _subc(a[i], b[i], &bw);
    if (bw) {
        uint c = 0;
        #pragma unroll 8
        for (int i = 7; i >= 0; i--) r[i] = _addc(r[i], _P[i], &c);
    }
}

/* r = a * b mod P  --  BitCrack-style secp256k1 reduction */
static void mulModP(uint r[8], const uint a[8], const uint b[8]) {
    /* ---- full 512-bit multiply ---- */
    uint hi[8], lo[8];
    {
        uint z[16] = {0,0,0,0,0,0,0,0, 0,0,0,0,0,0,0,0};
        uint high = 0;
        /* First row */
        for (int j = 7; j >= 0; j--) {
            ulong prod = (ulong)a[7] * b[j] + high;
            z[7+j+1]   = (uint)prod;
            high        = (uint)(prod >> 32);
        }
        z[7] = high;
        /* Remaining rows */
        for (int i = 6; i >= 0; i--) {
            high = 0;
            for (int j = 7; j >= 0; j--) {
                ulong prod = (ulong)a[i] * b[j] + z[i+j+1] + high;
                z[i+j+1]  = (uint)prod;
                high       = (uint)(prod >> 32);
            }
            z[i] = high;
        }
        #pragma unroll 8
        for (int i = 0; i < 8; i++) { hi[i] = z[i]; lo[i] = z[8+i]; }
    }

    /* ---- secp256k1 reduction: lo += hi*(2^32 + 977) ---- */
    uint carry = 0;
    uint hWord = 0;

    /* Step 1: add hi*2^32 to lo (shift hi left 1 word) */
    for (int i = 6; i >= 0; i--)
        lo[i] = _addc(lo[i], hi[i+1], &carry);
    uint p7 = _addc(hi[0], 0u, &carry);
    uint p6 = carry;

    /* Step 2: add hi*977 to lo */
    carry = 0;
    for (int i = 7; i >= 0; i--) {
        uint t = 0;
        _madd977(&hWord, &t, hi[i], hWord);
        lo[i] = _addc(lo[i], t, &carry);
    }
    p7 = _addc(p7, hWord, &carry);
    p6 = _addc(p6,    0u, &carry);

    /* Step 3: second pass for the two overflow words */
    carry = 0;
    hi[7] = p7;  hi[6] = p6;
    lo[6] = _addc(lo[6], hi[7], &carry);
    lo[5] = _addc(lo[5], hi[6], &carry);
    for (int i = 4; i >= 0; i--)
        lo[i] = _addc(lo[i], 0u, &carry);
    p7 = carry;

    carry = 0; hWord = 0;
    uint t7 = 0, t6 = 0;
    _madd977(&hWord, &t7, hi[7], hWord);
    lo[7] = _addc(lo[7], t7, &carry);
    _madd977(&hWord, &t6, hi[6], hWord);
    lo[6] = _addc(lo[6], t6, &carry);
    lo[5] = _addc(lo[5], hWord, &carry);
    for (int i = 4; i >= 0; i--)
        lo[i] = _addc(lo[i], 0u, &carry);
    p7 = carry;

    /* Final conditional subtract if >= P */
    bool ge = p7;
    if (!ge) {
        #pragma unroll 8
        for (int i = 0; i < 8; i++) {
            if (lo[i] > _P[i]) { ge = true; break; }
            if (lo[i] < _P[i]) break;
        }
    }
    if (ge) {
        uint bw = 0;
        #pragma unroll 8
        for (int i = 7; i >= 0; i--) lo[i] = _subc(lo[i], _P[i], &bw);
    }
    #pragma unroll 8
    for (int i = 0; i < 8; i++) r[i] = lo[i];
}

/* Convenience: squaring */
static inline void sqrModP(uint r[8], const uint a[8]) {
    mulModP(r, a, a);
}

/* r = a^(P-2) mod P  -- Fermat inversion via square-and-multiply.
   Standard left-to-right binary method: square RES each bit, multiply by
   fixed BASE when the corresponding bit of the exponent is 1.
   Cost: 255 squarings + ~128 multiplications.
   Called once per STEPS_BATCH hops -> ~1 mul/hop amortised. */
static void invModP(uint r[8], const uint a[8]) {
    /* P-2 = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2D */
    const uint exp[8] = {
        0xFFFFFFFF,0xFFFFFFFF,0xFFFFFFFF,0xFFFFFFFF,
        0xFFFFFFFF,0xFFFFFFFF,0xFFFFFFFE,0xFFFFFC2D
    };

    uint base[8], res[8];
    #pragma unroll 8
    for (int i = 0; i < 8; i++) base[i] = a[i];

    /* Skip the leading 1-bit (bit 255 = 1): initialise res = base */
    #pragma unroll 8
    for (int i = 0; i < 8; i++) res[i] = base[i];

    /* Process bits 254 down to 0 */
    bool first = true;
    for (int w = 0; w < 8; w++) {
        uint word = exp[w];
        for (int bit = 31; bit >= 0; bit--) {
            if (first) { first = false; continue; }   /* skip leading 1 */
            sqrModP(res, res);                         /* res = res^2     */
            if ((word >> bit) & 1u)
                mulModP(res, res, base);               /* res *= a (fixed) */
        }
    }
    #pragma unroll 8
    for (int i = 0; i < 8; i++) r[i] = res[i];
}

/* ====================================================================
   EC point arithmetic
   ==================================================================== */

/**
 * Mixed addition: Jacobian(X1,Y1,Z1) + Affine(x2,y2) -> Jacobian(rx,ry,rz)
 *
 * Cost: 8 mulModP + 3 sqrModP + 4 addModP/subModP  (~= 11 muls total)
 * No modular inversion needed.
 *
 * Formulae (standard Chudnovsky):
 *   U2 = x2*Z1^2         S2 = y2*Z1^3
 *   H  = U2 - X1         R  = S2 - Y1
 *   rz = Z1*H
 *   H^2 = H*H             H^3 = H^2*H
 *   X1H2 = X1*H^2
 *   rx = R^2 - H^3 - 2*X1H2
 *   ry = R*(X1H2 - rx) - Y1*H^3
 */
static void pointAddMixed(
    uint rx[8], uint ry[8], uint rz[8],
    const uint X1[8], const uint Y1[8], const uint Z1[8],
    const uint x2[8], const uint y2[8])
{
    uint Z1sq[8], Z1cu[8], U2[8], S2[8];
    uint H[8], R[8], H2[8], H3[8], X1H2[8], tmp[8];

    sqrModP(Z1sq, Z1);                     /* Z1^2         */
    mulModP(Z1cu, Z1sq, Z1);               /* Z1^3         */
    mulModP(U2,   x2,   Z1sq);             /* U2 = x2*Z1^2 */
    mulModP(S2,   y2,   Z1cu);             /* S2 = y2*Z1^3 */
    subModP(H,    U2,   X1);               /* H  = U2-X1  */
    subModP(R,    S2,   Y1);               /* R  = S2-Y1  */
    mulModP(rz,   Z1,   H);                /* rz = Z1*H   */
    sqrModP(H2,   H);                      /* H^2          */
    mulModP(H3,   H2,   H);                /* H^3          */
    mulModP(X1H2, X1,   H2);               /* X1H^2        */
    sqrModP(tmp,  R);                      /* R^2          */
    subModP(rx,   tmp,  H3);               /* R^2-H^3       */
    subModP(rx,   rx,   X1H2);             /* -X1H^2       */
    subModP(rx,   rx,   X1H2);             /* -X1H^2       */
    subModP(tmp,  X1H2, rx);               /* X1H^2-rx     */
    mulModP(ry,   R,    tmp);              /* R*(X1H^2-rx) */
    mulModP(tmp,  Y1,   H3);               /* Y1*H^3       */
    subModP(ry,   ry,   tmp);              /* ry done     */
}

/**
 * Convert Jacobian (X:Y:Z) to affine (x,y).
 *   x = X * Z^-2,  y = Y * Z^-3
 * Cost: 1 invModP + 4 mulModP
 */
static void jacToAffine(uint ax[8], uint ay[8],
                        const uint X[8], const uint Y[8], const uint Z[8]) {
    uint Zinv[8], Zinv2[8], Zinv3[8];
    invModP(Zinv,  Z);
    sqrModP(Zinv2, Zinv);
    mulModP(Zinv3, Zinv2, Zinv);
    mulModP(ax,    X,     Zinv2);
    mulModP(ay,    Y,     Zinv3);
}

/* ====================================================================
   Kernel parameters
   ==================================================================== */

#define W_SIZE       32     /* jump table entries                     */
#define STEPS_BATCH  32   /* Jacobian hops before affine conversion  */
#define N_BATCHES    64      /* batches per kernel call -> 2048 hops    */
#define KIND_TAME    0
#define KIND_WILD    1
#define KIND_NEG     2
#define MAX_DP_RESULTS 4096

typedef struct {
    uint  x[8];
    ulong dist;
    int   kind;
    int   thread_id;
} DPResult;

/* ====================================================================
   Main Kangaroo step kernel
   ==================================================================== */

/**
 * kangarooStep -- runs N_BATCHES * STEPS_BATCH hops per call.
 *
 * Each batch:
 *   1. Load affine (cx, cy) -> start Jacobian with Z=1
 *   2. STEPS_BATCH mixed Jacobian+Affine hops (no inversion!)
 *   3. Convert final Jacobian pos back to affine (1 invModP)
 *   4. Check Distinguished Point: (cx[7] & dp_mask_lo) == 0
 *   5. If DP: write to dp_results via atomic slot
 *
 * Global args:
 *   n_threads : total kangaroos
 *   px, py    : affine positions [n_threads * 8 uint32]
 *   dist      : distances       [n_threads, uint64]
 *   kind      : kangaroo type   [n_threads, int32]
 *   jx, jy    : jump points     [W_SIZE * 8 uint32]
 *   jdist     : jump distances  [W_SIZE, uint64]
 *   dp_mask_lo: lower 32 bits of DP mask (x[7] & dp_mask_lo == 0 -> DP)
 *   dp_results: output buffer
 *   n_results : atomic counter
 */
__kernel
__attribute__((reqd_work_group_size(64, 1, 1)))
void kangarooStep(
    int             n_threads,
    __global uint  *px,
    __global uint  *py,
    __global ulong *dist,
    __global int   *kind,
    __constant uint  *jx,
    __constant uint  *jy,
    __constant ulong *jdist,
    uint            dp_mask_lo,
    __global DPResult         *dp_results,
    __global volatile int     *n_results)
{
    int tid = get_global_id(0);
    if (tid >= n_threads) return;

    /* ---- Cache jump table in LDS ---- */
    __local uint ljx[W_SIZE * 8];
    __local uint ljy[W_SIZE * 8];
    __local ulong ljd[W_SIZE];
    {
        int lid = get_local_id(0);
        int lsz = get_local_size(0);
        /* Each thread copies a slice; ceil(W_SIZE*8 / lsz) iters */
        for (int k = lid; k < W_SIZE * 8; k += lsz) {
            ljx[k] = jx[k];
            ljy[k] = jy[k];
        }
        for (int k = lid; k < W_SIZE; k += lsz)
            ljd[k] = jdist[k];
    }
    barrier(CLK_LOCAL_MEM_FENCE);

    /* ---- Load affine position and metadata ---- */
    uint cx[8], cy[8];
    #pragma unroll 8
    for (int i = 0; i < 8; i++) {
        cx[i] = px[tid*8 + i];
        cy[i] = py[tid*8 + i];
    }
    ulong d = dist[tid];
    int   kk = kind[tid];

    /* ---- N_BATCHES * STEPS_BATCH Jacobian hops ---- */
    for (int batch = 0; batch < N_BATCHES; batch++) {

        /* Start Jacobian with Z = 1 (affine input) */
        uint Jx[8], Jy[8], Jz[8];
        #pragma unroll 8
        for (int i = 0; i < 8; i++) { Jx[i] = cx[i]; Jy[i] = cy[i]; }
        Jz[0]=0; Jz[1]=0; Jz[2]=0; Jz[3]=0;
        Jz[4]=0; Jz[5]=0; Jz[6]=0; Jz[7]=1;  /* Z = 1 */

        /* STEPS_BATCH Jacobian hops */
        for (int step = 0; step < STEPS_BATCH; step++) {
            /* Jump index from lowest bits of Jacobian X (deterministic) */
            uint idx = Jx[7] & (W_SIZE - 1u);

            /* Load jump point from LDS */
            uint jxl[8], jyl[8];
            #pragma unroll 8
            for (int i = 0; i < 8; i++) {
                jxl[i] = ljx[idx*8 + i];
                jyl[i] = ljy[idx*8 + i];
            }

            /* Jacobian + Affine mixed addition */
            uint Rx[8], Ry[8], Rz[8];
            pointAddMixed(Rx, Ry, Rz, Jx, Jy, Jz, jxl, jyl);
            #pragma unroll 8
            for (int i = 0; i < 8; i++) { Jx[i]=Rx[i]; Jy[i]=Ry[i]; Jz[i]=Rz[i]; }

            d += ljd[idx];
        }

        /* ---- Convert Jacobian to affine (1 inversion per STEPS_BATCH) ---- */
        jacToAffine(cx, cy, Jx, Jy, Jz);

        /* ---- Distinguished Point check on affine x ---- */
        if ((cx[7] & dp_mask_lo) == 0) {
            int slot = atomic_add(n_results, 1);
            if (slot < MAX_DP_RESULTS) {
                #pragma unroll 8
                for (int i = 0; i < 8; i++) dp_results[slot].x[i] = cx[i];
                dp_results[slot].dist      = d;
                dp_results[slot].kind      = kk;
                dp_results[slot].thread_id = tid;
            }
        }
    }

    /* ---- Store back ---- */
    #pragma unroll 8
    for (int i = 0; i < 8; i++) {
        px[tid*8 + i] = cx[i];
        py[tid*8 + i] = cy[i];
    }
    dist[tid] = d;
}


/* ====================================================================
   Initialization kernel
   ==================================================================== */

/**
 * initKangaroos -- set starting affine positions.
 *
 * tame[tid]:     (tame_base + tid) * G  -- spread across range midpoint
 * wild[tid]:     Q + tid*G              -- Q = target pubkey
 * neg[tid]:      -Q + tid*G             -- negation trick (free x2 speedup)
 *
 * step_x/y:      precomputed i*G for i = 1..max(n_tame,n_wild)
 */
__kernel void initKangaroos(
    int             n_tame,
    int             n_wild,
    int             nbits,           /* # of 2^j*G entries in p2x/p2y            */
    __constant uint *tame_base_x,
    __constant uint *tame_base_y,
    __constant uint *qx,
    __constant uint *qy,
    __constant uint *p2x,            /* table of (2^j * G).x  for j = 0..nbits-1 */
    __constant uint *p2y,            /* table of (2^j * G).y                     */
    __global uint  *px,
    __global uint  *py,
    __global ulong *dist,
    __global int   *kind,
    __global ulong *idist)           /* per-kangaroo random offset (also = dist) */
{
    int tid   = get_global_id(0);
    int total = n_tame + n_wild * 2;
    if (tid >= total) return;

    /* Compute this kangaroo's offset point ox/oy = off*G on the GPU by summing
       2^j*G over the set bits of off. Avoids n_total host scalar-muls, so a big
       herd initialises fast. (Incomplete addition: the rare edge where the
       running sum equals +/- a table entry yields a wrong point for that one
       kangaroo — harmless, its bad DPs fail the pubkey verification.) */
    ulong off = idist[tid];
    uint  ax[8], ay[8], az[8];
    bool  have = false;
    for (int j = 0; j < nbits; j++) {
        if ((off >> j) & 1UL) {
            uint tx[8], ty[8];
            #pragma unroll 8
            for (int i = 0; i < 8; i++) { tx[i] = p2x[j*8+i]; ty[i] = p2y[j*8+i]; }
            if (!have) {
                #pragma unroll 8
                for (int i = 0; i < 8; i++) { ax[i]=tx[i]; ay[i]=ty[i]; az[i]=0; }
                az[7] = 1;               /* Jacobian Z = 1 */
                have = true;
            } else {
                /* pointAddMixed writes rz from Z1 immediately, so it cannot run
                   in-place — accumulate through a temp. */
                uint nx[8], ny[8], nz[8];
                pointAddMixed(nx, ny, nz, ax, ay, az, tx, ty);
                #pragma unroll 8
                for (int i = 0; i < 8; i++) { ax[i]=nx[i]; ay[i]=ny[i]; az[i]=nz[i]; }
            }
        }
    }
    uint ox[8], oy[8];
    jacToAffine(ox, oy, ax, ay, az);     /* ox/oy = off*G in affine */

    uint rx[8], ry[8], rz[8];
    int  kk;

    if (tid < n_tame) {
        /* Tame: tame_base*G + (tid+1)*G in affine via Jacobian */
        uint Z1[8] = {0,0,0,0,0,0,0,1};
        uint tb_x[8], tb_y[8];
        #pragma unroll 8
        for (int i = 0; i < 8; i++) { tb_x[i]=tame_base_x[i]; tb_y[i]=tame_base_y[i]; }
        pointAddMixed(rx, ry, rz, tb_x, tb_y, Z1, ox, oy);
        uint ax[8], ay[8];
        jacToAffine(ax, ay, rx, ry, rz);
        #pragma unroll 8
        for (int i = 0; i < 8; i++) { rx[i]=ax[i]; ry[i]=ay[i]; }
        kk = KIND_TAME;

    } else if (tid < n_tame + n_wild) {
        /* Wild: Q + off*G  (off*G computed above into ox/oy) */
        uint  sx[8], sy[8];
        #pragma unroll 8
        for (int i = 0; i < 8; i++) { sx[i]=ox[i]; sy[i]=oy[i]; }
        uint  qxl[8], qyl[8];
        #pragma unroll 8
        for (int i = 0; i < 8; i++) { qxl[i]=qx[i]; qyl[i]=qy[i]; }
        uint  Z1[8] = {0,0,0,0,0,0,0,1};
        pointAddMixed(rx, ry, rz, qxl, qyl, Z1, sx, sy);
        uint ax[8], ay[8];
        jacToAffine(ax, ay, rx, ry, rz);
        #pragma unroll 8
        for (int i = 0; i < 8; i++) { rx[i]=ax[i]; ry[i]=ay[i]; }
        kk = KIND_WILD;

    } else {
        /* Neg wild: -Q + off*G  (-Q: same x, y -> P-y) */
        uint  sx[8], sy[8];
        #pragma unroll 8
        for (int i = 0; i < 8; i++) { sx[i]=ox[i]; sy[i]=oy[i]; }
        uint  nqx[8], nqy[8];
        #pragma unroll 8
        for (int i = 0; i < 8; i++) nqx[i] = qx[i];
        /* nqy = P - qy
           Both _P (__constant) and qy (__constant) must be copied to
           private address space before passing to subModP. */
        uint pCopy[8], qyCopy[8];
        #pragma unroll 8
        for (int pi = 0; pi < 8; pi++) { pCopy[pi] = _P[pi]; qyCopy[pi] = qy[pi]; }
        subModP(nqy, pCopy, qyCopy);
        uint  Z1[8] = {0,0,0,0,0,0,0,1};
        pointAddMixed(rx, ry, rz, nqx, nqy, Z1, sx, sy);
        uint ax[8], ay[8];
        jacToAffine(ax, ay, rx, ry, rz);
        #pragma unroll 8
        for (int i = 0; i < 8; i++) { rx[i]=ax[i]; ry[i]=ay[i]; }
        kk = KIND_NEG;
    }

    #pragma unroll 8
    for (int i = 0; i < 8; i++) {
        px[tid*8 + i] = rx[i];
        py[tid*8 + i] = ry[i];
    }
    /* Initial distance = this kangaroo's own offset from its origin (tame_base,
       +Q or -Q). The offset POINT in step_x[tid] and this scalar idist[tid] are
       built together on the host, so position == (origin + idist)*G exactly. */
    dist[tid] = idist[tid];
    kind[tid] = kk;
}
