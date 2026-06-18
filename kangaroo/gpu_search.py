"""
GPU-движок поиска Bitcoin Puzzle на AMD RX 6600 через OpenCL.

Использует BitCrack's bitcrack.cl ядро (secp256k1 + SHA256 + RIPEMD160).

Алгоритм:
1. Инициализация: multiplyStepKernel × 256 → вычисляет k*G для всех TOTAL_POINTS потоков
2. Основной цикл: keyFinderKernel → хеш, сравнение, инкремент точки
3. При нахождении: восстанавливает приватный ключ k = k_start + idx + iter * TOTAL_POINTS

Производительность на RX 6600: ~200-500 Mkeys/sec (зависит от TOTAL_POINTS).
"""

import os
import sys
import time
import struct
import hashlib
import numpy as np
import pyopencl as cl
from pathlib import Path
from typing import Optional

# ---- secp256k1 + SHA256 + RIPEMD160 OpenCL kernel ----
# Vendored from BitCrack (bitcrack.cl), (c) 2018 Ben Richard, MIT license.
# See THIRD_PARTY_NOTICES.md. Kept local so the repo / packaged build are
# self-contained; falls back to a BitCrack checkout if present.
_HERE    = Path(__file__).parent
_KERNEL  = _HERE / 'bitcrack.cl'
if not _KERNEL.exists():
    _KERNEL = _HERE.parent / 'BitCrack' / 'CLKeySearchDevice' / 'bitcrack.cl'

# ---- secp256k1 константы ----
_P  = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N  = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
_G  = (_GX, _GY)
_INF = (0, 0)

# ---- Параметры GPU (оптимизировано для AMD RX 6600) ----
# Re-benched RX 6600 (2026-06): peak 64x4096x120 = 31.5M pts -> 406 Mkeys/s.
# Curve: p112=399 p116=402 p120=406 p124=386 p128=354, then VRAM CLIFF
# (p160=110, blocks6144=85). Old default p128 sat past the peak on the
# downslope (354). p112 = ~399 Mkeys/s with the widest margin to the cliff.
DEFAULT_THREADS           = 64       # local_work_size (wavefront=32 on RDNA2)
DEFAULT_BLOCKS            = 4096     # global_work_size / threads
DEFAULT_POINTS_PER_THREAD = 112      # points/thread; just below the ~31M-pt peak,
                                     # safely clear of the ~33M+ VRAM cliff

# ---- CLDeviceResult: структура результата из ядра ----
# struct { int idx; bool compressed; uint x[8]; uint y[8]; uint digest[5]; }
# В OpenCL C: bool = int (4 байта). Итого: 4+4+32+32+20 = 92 байта
_RESULT_DTYPE = np.dtype([
    ('idx',        np.int32),
    ('compressed', np.int32),
    ('x',          np.uint32, (8,)),
    ('y',          np.uint32, (8,)),
    ('digest',     np.uint32, (5,)),
])
_MAX_RESULTS = 128


# ===========================================================================
# Вспомогательная арифметика CPU (для инициализации)
# ===========================================================================

def _fp_inv(a: int) -> int:
    return pow(a, _P - 2, _P)

def _pt_add(P1, P2):
    if P1 == _INF: return P2
    if P2 == _INF: return P1
    x1, y1 = P1; x2, y2 = P2
    if x1 == x2:
        if y1 != y2: return _INF
        lam = (3 * x1 * x1 * _fp_inv(2 * y1)) % _P
    else:
        lam = ((y2 - y1) * _fp_inv(x2 - x1)) % _P
    x3 = (lam * lam - x1 - x2) % _P
    y3 = (lam * (x1 - x3) - y1) % _P
    return (x3, y3)

def _pt_dbl(pt):
    if pt == _INF: return _INF
    x, y = pt
    if y == 0: return _INF
    lam = (3 * x * x * _fp_inv(2 * y)) % _P
    x3  = (lam * lam - 2 * x) % _P
    y3  = (lam * (x - x3) - y) % _P
    return (x3, y3)

def _scalar_mul(k: int, pt):
    if k == 0: return _INF
    if k < 0:
        x, y = _scalar_mul(-k, pt)
        return (x, (-y) % _P)
    r = _INF; add = pt
    while k:
        if k & 1: r = _pt_add(r, add)
        add = _pt_dbl(add)
        k >>= 1
    return r


def _int_to_u256(k: int) -> np.ndarray:
    """Integer → 8×uint32 big-endian (MSW first, как в BitCrack uint256_t)."""
    arr = np.zeros(8, dtype=np.uint32)
    for i in range(7, -1, -1):
        arr[7 - i] = (k >> (i * 32)) & 0xFFFFFFFF
    return arr

def _u256_to_int(arr: np.ndarray) -> int:
    result = 0
    for w in arr:
        result = (result << 32) | int(w)
    return result

_INF_U256 = np.full(8, 0xFFFFFFFF, dtype=np.uint32)


def _batch_keys_to_u256(k_start: int, count: int) -> np.ndarray:
    """
    Быстрое (numpy) создание массива count×8 uint32 для ключей
    k_start, k_start+1, ..., k_start+count-1.
    Обрабатывает перенос через 32-битные границы.
    """
    result = np.zeros((count, 8), dtype=np.uint32)

    # Заполняем константные старшие слова из k_start
    kb = k_start.to_bytes(32, 'big')
    for j in range(8):
        w = int.from_bytes(kb[j*4:(j+1)*4], 'big')
        if w:
            result[:, j] = w

    # Добавляем смещение 0..count-1 с переносом через слова 7→6→5→4
    offsets = np.arange(count, dtype=np.uint64)

    # слова 7,6,5,4 = младшие 128 бит — с запасом для любого батча (count << 2^128);
    # старшие слова 0..3 (любой бит-лен ключа puzzle, до 256 бит) копируются как есть выше
    for col in range(7, 3, -1):
        base = np.uint64(int.from_bytes(kb[col*4:(col+1)*4], 'big'))
        s    = base + offsets
        result[:, col] = (s & np.uint64(0xFFFFFFFF)).astype(np.uint32)
        carry = (s >> np.uint64(32)).astype(np.uint64)
        if not np.any(carry):
            break
        offsets = carry   # передаём перенос в следующий столбец

    return result.reshape(-1)


# ===========================================================================
# Класс GPUSearchEngine
# ===========================================================================

class GPUSearchEngine:
    """
    Движок поиска Bitcoin Puzzle на GPU через OpenCL (BitCrack ядро).

    Параметры производительности на AMD RX 6600 (gfx1032, 14 CU):
      threads=64, blocks=1024, points_per_thread=8 → TOTAL=524288 ключей/шаг
      Ожидаемая скорость: 100-400 Mkeys/sec
    """

    def __init__(
        self,
        device_idx:         int = 0,
        threads:            int = DEFAULT_THREADS,
        blocks:             int = DEFAULT_BLOCKS,
        points_per_thread:  int = DEFAULT_POINTS_PER_THREAD,
    ):
        self.threads           = threads
        self.blocks            = blocks
        self.points_per_thread = points_per_thread
        self.total_points      = threads * blocks * points_per_thread  # TOTAL_POINTS
        self.global_size       = threads * blocks                       # = dim в ядре
        self.local_size        = threads

        if self.threads % 32 != 0:
            raise ValueError("threads must be multiple of 32")
        if self.points_per_thread < 1:
            raise ValueError("points_per_thread must be >= 1")

        # ---- OpenCL setup ----
        platforms = cl.get_platforms()
        devices   = [d for p in platforms for d in p.get_devices(cl.device_type.GPU)]
        if not devices:
            raise RuntimeError("No OpenCL GPU devices found!")

        self.device = devices[device_idx]
        self.ctx    = cl.Context([self.device])
        self.queue  = cl.CommandQueue(self.ctx)

        print(f"[GPU] {self.device.name}")
        print(f"      CUs={self.device.max_compute_units}  "
              f"VRAM={self.device.global_mem_size//1024//1024}MB  "
              f"LocalMem={self.device.local_mem_size//1024}KB")
        print(f"      threads={threads}  blocks={blocks}  "
              f"points/thread={points_per_thread}  total={self.total_points:,}")

        # ---- Компиляция ядра ----
        if not _KERNEL.exists():
            raise FileNotFoundError(f"Kernel not found: {_KERNEL}")

        source = _KERNEL.read_text(encoding='utf-8', errors='replace')
        print(f"[GPU] Compiling kernel ({len(source)//1024}KB)...", flush=True)
        try:
            self.prog = cl.Program(self.ctx, source).build(
                options='-cl-mad-enable -cl-fast-relaxed-math'
            )
        except cl.RuntimeError as e:
            print(f"[GPU] Build failed!\n{e}")
            raise

        print("[GPU] Kernel compiled OK.")

        # Cache kernel objects to avoid RepeatedKernelRetrieval overhead
        self._kern_multiply = cl.Kernel(self.prog, 'multiplyStepKernel')
        self._kern_find     = cl.Kernel(self.prog, 'keyFinderKernel')
        self._kern_find_dbl = cl.Kernel(self.prog, 'keyFinderKernelWithDouble')

        # ---- Выделение буферов ----
        self._alloc_buffers()

        # Состояние
        self._initialized = False
        self._iteration   = 0
        self._k_start     = 0

    # -----------------------------------------------------------------------
    # Выделение GPU буферов
    # -----------------------------------------------------------------------

    def _alloc_buffers(self):
        mf = cl.mem_flags
        N  = self.total_points
        PT = self.total_points   # alias

        # x, y, chain: N × uint256_t = N × 8 × uint32 = N × 32 байт
        sz = PT * 8 * 4  # bytes

        self.x_buf      = cl.Buffer(self.ctx, mf.READ_WRITE, sz)
        self.y_buf      = cl.Buffer(self.ctx, mf.READ_WRITE, sz)
        self.chain_buf  = cl.Buffer(self.ctx, mf.READ_WRITE, sz)

        # Приватные ключи для инициализации (только запись от CPU)
        self.priv_buf   = cl.Buffer(self.ctx, mf.READ_ONLY, sz)

        # Таблица 2^i*G: 256 × uint256_t
        self.xtbl_buf   = cl.Buffer(self.ctx, mf.READ_ONLY, 256 * 8 * 4)
        self.ytbl_buf   = cl.Buffer(self.ctx, mf.READ_ONLY, 256 * 8 * 4)

        # Инкремент (одна точка)
        self.xinc_buf   = cl.Buffer(self.ctx, mf.READ_ONLY, 8 * 4)
        self.yinc_buf   = cl.Buffer(self.ctx, mf.READ_ONLY, 8 * 4)

        # Целевой список: placeholder, будет заменён в set_target
        self.target_buf  = cl.Buffer(self.ctx, mf.READ_ONLY, 5 * 4)

        # Результаты
        self.result_buf  = cl.Buffer(self.ctx, mf.WRITE_ONLY,
                                     _MAX_RESULTS * _RESULT_DTYPE.itemsize)
        self.nresult_buf = cl.Buffer(self.ctx, mf.READ_WRITE, 4)

        mem_mb = (sz * 3 + 256 * 8 * 4 * 2) / 1024 / 1024
        print(f"[GPU] Allocated {mem_mb:.1f}MB VRAM")

    # -----------------------------------------------------------------------
    # Установка цели
    # -----------------------------------------------------------------------

    def set_target(self, target_words: list):
        """
        Устанавливает цель поиска.
        target_words — список 5 uint32 в формате undoRMD160FinalRound (BitCrack).
        Используйте utils.address.get_target_for_kernel() для получения.
        """
        mf  = cl.mem_flags
        tgt = np.array(target_words, dtype=np.uint32)
        # Пересоздаём буфер с данными
        self.target_buf = cl.Buffer(self.ctx,
                                    mf.READ_ONLY | mf.COPY_HOST_PTR,
                                    hostbuf=tgt)
        self._target_words = target_words

    # -----------------------------------------------------------------------
    # Инициализация точек (multiplyStepKernel)
    # -----------------------------------------------------------------------

    def initialize(self, k_start: int):
        """
        Вычисляет k_start*G, (k_start+1)*G, ..., (k_start+TOTAL_POINTS-1)*G на GPU.
        Использует multiplyStepKernel из BitCrack.

        KEY OPTIMIZATION: запускаем только n_bits итераций вместо 256.
        Для puzzle #71 ключи имеют 71 бит → нужно лишь 71 итерация.
        Биты 71..255 всегда равны 0 → эти kernel-вызовы были бесполезны.
        Ускорение: 256/71 ≈ 3.6x на шаге initialize.
        """
        self._k_start   = k_start
        self._iteration = 0

        N = self.total_points
        G = self.global_size
        L = self.local_size

        # Определяем реальное кол-во бит в ключах этого батча.
        # Максимальный ключ в батче: k_start + N - 1.
        # bit_length() даёт позицию старшего бита + 1.
        # Пример: puzzle #71 → ключи в [2^70, 2^71-1] → bit_length = 71.
        n_bits = max((k_start + N - 1).bit_length(), 1)
        n_bits = min(n_bits, 256)   # secp256k1 ограничение

        # 1. Строим таблицу 2^i*G для i=0..n_bits-1 (ОДИН РАЗ — константа secp256k1)
        # Пересчитываем только если нужно больше бит чем было раньше.
        prev_n_bits = getattr(self, '_table_n_bits', 0)
        if n_bits > prev_n_bits:
            print(f"[GPU] Building 2^i*G table ({n_bits} bits, cached)...", flush=True)
            t0   = time.time()
            xtbl = np.zeros(256 * 8, dtype=np.uint32)
            ytbl = np.zeros(256 * 8, dtype=np.uint32)
            pt   = _G
            for i in range(n_bits):
                xtbl[i*8:(i+1)*8] = _int_to_u256(pt[0])
                ytbl[i*8:(i+1)*8] = _int_to_u256(pt[1])
                pt = _pt_dbl(pt)
            cl.enqueue_copy(self.queue, self.xtbl_buf, xtbl)
            cl.enqueue_copy(self.queue, self.ytbl_buf, ytbl)
            self._table_n_bits = n_bits
            print(f"[GPU]   G-table built in {time.time()-t0:.1f}s "
                  f"(reused on next jumps, {n_bits} entries)")

        # 2. Строим массив приватных ключей: k_start, k_start+1, ..., k_start+N-1
        print(f"[GPU] Building {N:,} private keys...", flush=True)
        t0       = time.time()
        priv_arr = _batch_keys_to_u256(k_start, N)
        cl.enqueue_copy(self.queue, self.priv_buf, priv_arr)
        del priv_arr
        print(f"[GPU]   private keys built in {time.time()-t0:.1f}s")

        # 3. Инициализируем x, y = INFINITY (все 0xFFFFFFFF)
        inf_data = np.full(N * 8, 0xFFFFFFFF, dtype=np.uint32)
        cl.enqueue_copy(self.queue, self.x_buf, inf_data)
        cl.enqueue_copy(self.queue, self.y_buf, inf_data)
        del inf_data

        # 4. Запускаем multiplyStepKernel только n_bits раз (не 256!).
        # Для бит i >= n_bits: они всегда 0 у всех ключей в батче → ядро
        # ничего не добавляло бы к аккумулятору. Пропускаем их.
        print(f"[GPU] Running multiplyStepKernel x{n_bits} "
              f"(was x256, speedup {256/n_bits:.1f}x)...", flush=True)
        t0     = time.time()
        kernel = self._kern_multiply

        for step in range(n_bits):
            kernel.set_args(
                np.int32(N),           # totalPoints
                np.int32(step),        # step (бит 0..n_bits-1)
                self.priv_buf,         # privateKeys
                self.chain_buf,        # chain (temp)
                self.xtbl_buf,         # gxPtr  [step] = x(2^step * G)
                self.ytbl_buf,         # gyPtr  [step] = y(2^step * G)
                self.x_buf,            # xPtr   (accumulator)
                self.y_buf,            # yPtr   (accumulator)
            )
            cl.enqueue_nd_range_kernel(
                self.queue, kernel,
                (G,), (L,)             # global=(BLOCKS*THREADS), local=(THREADS)
            )

        self.queue.finish()
        dt = time.time() - t0
        print(f"[GPU]   multiplyStep done in {dt:.2f}s "
              f"({dt*1000/n_bits:.1f}ms/step, {n_bits} steps)")

        # 5. Вычисляем инкремент = TOTAL_POINTS * G (ОДИН РАЗ — константа)
        if not getattr(self, '_inc_ready', False):
            print("[GPU] Computing increment point (once)...", flush=True)
            inc_pt = _scalar_mul(N, _G)
            cl.enqueue_copy(self.queue, self.xinc_buf, _int_to_u256(inc_pt[0]))
            cl.enqueue_copy(self.queue, self.yinc_buf, _int_to_u256(inc_pt[1]))
            self._inc_ready = True
        print(f"[GPU] Ready: {N:,} pts @ k={hex(k_start)}")

        self._initialized = True

    # -----------------------------------------------------------------------
    # Один шаг поиска
    # -----------------------------------------------------------------------

    def step(self) -> list:
        """
        Выполняет один шаг keyFinderKernel:
        - хеширует все TOTAL_POINTS текущих точек
        - сравнивает с целевым hash160
        - инкрементирует все точки на TOTAL_POINTS*G
        Возвращает список найденных ключей (обычно пустой).
        """
        if not self._initialized:
            raise RuntimeError("Call initialize() before step()")

        # Сброс счётчика результатов
        zero = np.zeros(1, dtype=np.uint32)
        cl.enqueue_copy(self.queue, self.nresult_buf, zero)

        # Выбор ядра: первые 2 итерации с WithDouble (на случай близких к G точек)
        if self._iteration < 2:
            kernel = self._kern_find_dbl
        else:
            kernel = self._kern_find

        kernel.set_args(
            np.uint32(self.total_points),   # totalPoints
            np.int32(0),                    # compression = COMPRESSED (0)
            self.chain_buf,                 # chain
            self.x_buf,                     # xPtr
            self.y_buf,                     # yPtr
            self.xinc_buf,                  # incXPtr
            self.yinc_buf,                  # incYPtr
            self.target_buf,                # targetList
            np.uint64(1),                   # numTargets
            np.uint64(0),                   # mask (direct compare, не bloom filter)
            self.result_buf,                # results
            self.nresult_buf,               # numResults
        )
        cl.enqueue_nd_range_kernel(
            self.queue, kernel,
            (self.global_size,), (self.local_size,)
        )
        self.queue.finish()

        # Читаем счётчик результатов
        nresults = np.zeros(1, dtype=np.uint32)
        cl.enqueue_copy(self.queue, nresults, self.nresult_buf)
        self.queue.finish()

        found = []
        if nresults[0] > 0:
            found = self._read_results(int(nresults[0]))

        self._iteration += 1
        return found

    # -----------------------------------------------------------------------
    # Чтение и декодирование результатов
    # -----------------------------------------------------------------------

    def _read_results(self, count: int) -> list:
        n = min(count, _MAX_RESULTS)
        buf = np.zeros(n, dtype=_RESULT_DTYPE)
        cl.enqueue_copy(self.queue, buf, self.result_buf)
        self.queue.finish()

        results = []
        for r in buf:
            # k = k_start + TOTAL_POINTS * iteration + idx
            # (итерация уже была при запуске step(), до increment _iteration)
            # Формула из CLKeySearchDevice.cpp:
            #   offset = _points * _iterations + result.idx * _stride
            #   privateKey = _start + offset
            idx     = int(r['idx'])
            k       = (self._k_start + self.total_points * self._iteration + idx) % _N
            x_int   = _u256_to_int(r['x'])
            y_int   = _u256_to_int(r['y'])

            # Верификация через hash160
            digest_be = bytes()
            for dw in r['digest']:
                digest_be += int(dw).to_bytes(4, 'big')

            results.append({
                'k':          k,
                'idx':        idx,
                'compressed': bool(r['compressed']),
                'x':          x_int,
                'y':          y_int,
                'hash160_be': digest_be.hex(),   # для проверки
            })

        return results

    # -----------------------------------------------------------------------
    # Вспомогательные свойства
    # -----------------------------------------------------------------------

    @property
    def keys_per_step(self) -> int:
        return self.total_points

    @property
    def current_key(self) -> int:
        return self._k_start + self._iteration * self.total_points

    def get_device_info(self) -> dict:
        return {
            'name':       self.device.name,
            'vendor':     self.device.vendor,
            'cus':        self.device.max_compute_units,
            'vram_mb':    self.device.global_mem_size // 1024 // 1024,
            'local_kb':   self.device.local_mem_size // 1024,
            'clock_mhz':  self.device.max_clock_frequency,
        }


# ===========================================================================
# Вспомогательная функция: список OpenCL устройств
# ===========================================================================

def list_devices():
    print("Available OpenCL devices:")
    idx = 0
    for p in cl.get_platforms():
        for d in p.get_devices():
            dtype = cl.device_type.to_string(d.type)
            print(f"  [{idx}] {d.name} ({dtype})")
            print(f"       CUs={d.max_compute_units}  "
                  f"VRAM={d.global_mem_size//1024//1024}MB  "
                  f"LocalMem={d.local_mem_size//1024}KB  "
                  f"MaxWG={d.max_work_group_size}")
            idx += 1
