#!/usr/bin/env python3
"""
Bitcoin Puzzle Solver - RX 6600 Edition
Works with ANY known puzzle #1-150 (see utils/puzzle_registry.py).
Default target: Bitcoin Puzzle #71.

Usage:
  python main.py                          # run with default params (puzzle #71)
  python main.py --puzzle 71 --mode gpu --pure-random --pool-avoid  # lottery mode
  python main.py --puzzle 73 --mode gpu --pure-random               # any other puzzle
  python main.py --puzzle 20 --mode cpu   # test on puzzle #20 CPU mode
  python main.py --test                   # built-in self-test
  python main.py --devices                # list GPU devices
  python main.py --status                 # checkpoint status

To see which puzzles are currently unsolved:
  python analysis/puzzle_status.py --unsolved
  or run CHOOSE_PUZZLE.bat for an interactive menu.
"""

import sys
import os
import time
import argparse
import hashlib
import random

# Добавляем корень проекта в путь
sys.path.insert(0, os.path.dirname(__file__))

from ecc.curve   import scalar_mul, G, N
from utils.address   import (decode_address_hash160, point_to_address,
                               get_target_for_kernel, verify_key_address)
from utils.checkpoint import Checkpoint
from utils.coverage   import CoverageMap
from utils.puzzle_registry import get_puzzle, all_puzzle_numbers
from kangaroo.gpu_search import (GPUSearchEngine, DEFAULT_THREADS,
                                  DEFAULT_BLOCKS, DEFAULT_POINTS_PER_THREAD)


# ===========================================================================
# Таблица пазлов Bitcoin — любой известный пазл #1-150 (utils/puzzle_registry.py)
# ===========================================================================

PUZZLES = {n: get_puzzle(n) for n in all_puzzle_numbers()}

# ===========================================================================
# Pool avoidance — btcpuzzle.info scans some puzzles sequentially from the
# start of their range. Manually-updated snapshot (ranges_done, range_size_bits)
# per puzzle; check https://btcpuzzle.info/puzzle/<n> for current values.
# Puzzles not listed here -> no avoidance (pool_end stays at range start).
# ===========================================================================

POOL_PROGRESS = {
    # puzzle_num: (ranges_done, range_size_bits, total_ranges)
    71: (287_884, 45, 33_554_432),   # snapshot 2026-06: 0.858% scanned
}


def _get_pool_end(puzzle_num: int, pz: dict) -> int:
    """Absolute key offset up to which the btcpuzzle.info pool has scanned.

    Returns 0 when no pool data is known for this puzzle — callers treat that
    as "no avoidance" via the `pool_end > k_start` guard.
    """
    info = POOL_PROGRESS.get(puzzle_num)
    if not info:
        return 0
    ranges_done, range_size_bits, _total = info
    pool_end = pz['start'] + ranges_done * (1 << range_size_bits)
    return min(pool_end, pz['end'])


# ===========================================================================
# CPU-режим (для тестирования, отладки малых пазлов)
# ===========================================================================

def cpu_search(address: str, k_start: int, k_end: int,
               checkpoint_file: str = 'checkpoint.json'):
    """Простой CPU перебор. Используется для --mode cpu и малых пазлов."""
    from utils.address import point_to_hash160_compressed, decode_address_hash160

    chk        = Checkpoint(checkpoint_file)
    k_current  = chk.get_resume_key(k_start)
    target_h160 = decode_address_hash160(address)

    print(f"[CPU] Searching {address}")
    print(f"[CPU] Range: [{hex(k_start)}, {hex(k_end)}]")
    print(f"[CPU] Start: {hex(k_current)}")

    t0   = time.time()
    keys = 0

    pt = scalar_mul(k_current, G)   # начальная точка

    try:
        for k in range(k_current, k_end + 1):
            if pt == (0, 0):
                pt = scalar_mul(k, G)
            h = point_to_hash160_compressed(pt[0], pt[1])
            if h == target_h160:
                print(f"\n!!! KEY FOUND: k = {k} = {hex(k)} !!!")
                _save_found_key(k, address)
                return k
            # Инкремент: следующая точка = текущая + G
            from ecc.curve import point_add
            pt = point_add(pt, G)
            keys += 1
            if keys % 10000 == 0:
                elapsed = time.time() - t0
                spd     = keys / elapsed / 1000 if elapsed > 0 else 0
                print(f"\r{spd:.1f} Kkeys/sec | k={hex(k)}", end='', flush=True)
                chk.save(k, k_start, k_end, address, keys, spd / 1000)

    except KeyboardInterrupt:
        k_now = k_current + keys
        chk.save(k_now, k_start, k_end, address, keys)
        print(f"\n[CPU] Interrupted at {hex(k_now)}")

    return None


# ===========================================================================
# GPU-режим (основной)
# ===========================================================================

def _pure_random_search(address: str, k_start: int, k_end: int,
                        device_idx: int = 0,
                        threads: int = 64, blocks: int = 1024,
                        points_per_thread: int = 8,
                        jump_every: int = 200,
                        pool_end: int = 0,
                        checkpoint_file: str = 'checkpoint.json') -> int | None:
    """
    TRUE random lottery mode.

    Each jump_every GPU steps → reinitialize to a completely random key.
    The 2^i*G table and increment are cached after first build — only
    the multiplyStepKernel×n_bits GPU pass repeats (n_bits = key bit-length
    of this puzzle, auto-detected in GPUSearchEngine.initialize; ~1.8s/jump
    for puzzle #71's 71 bits).

    pool_end: if >0, skip [k_start, pool_end) already covered by btcpuzzle.info pool.
    """
    engine = GPUSearchEngine(device_idx=device_idx, threads=threads,
                             blocks=blocks, points_per_thread=points_per_thread)
    target_words = get_target_for_kernel(address)
    engine.set_target(target_words)

    # Cumulative lottery stats survive restarts: a random search has no resume
    # point, but the work done is still worth recording.
    chk = Checkpoint(checkpoint_file)
    prior_keys, prior_windows, prior_elapsed = chk.load_lottery_totals()

    total_keys = 0
    t_global   = time.time()
    t_step     = time.time()
    t_save     = time.time()
    jump_num   = 0

    # Pool avoidance: skip region already scanned by btcpuzzle.info pool
    # Pool scans sequentially from k_start; we cover everything else randomly.
    rand_lo = max(k_start, pool_end) if pool_end > k_start else k_start
    rand_hi = k_end - engine.total_points

    pool_pct = (pool_end - k_start) / (k_end - k_start) * 100 if pool_end > k_start else 0

    def _save_stats(spd: float = 0.0):
        """Persist cumulative work (adds this session onto any prior totals)."""
        try:
            chk.save_lottery_stats(
                address, k_start, k_end,
                prior_keys + total_keys,
                prior_windows + jump_num,
                prior_elapsed + (time.time() - t_global),
                spd)
        except Exception:
            pass        # a stats write must never kill the search

    print(f"\n{'='*60}")
    print(f"Bitcoin Puzzle Solver — PURE RANDOM MODE")
    print(f"Address:    {address}")
    print(f"Range:      [{hex(k_start)}, {hex(k_end)}]")
    print(f"Jump every: {jump_every} steps  (~{jump_every * engine.total_points / 1e9:.1f}B keys/window)")
    if pool_end > k_start:
        print(f"Pool avoid: [{hex(k_start)}, {hex(pool_end)}) = {pool_pct:.2f}% skipped")
        print(f"Our zone:   [{hex(rand_lo)}, {hex(rand_hi)}] ({100-pool_pct:.2f}% of range)")
    print(f"{'='*60}\n")

    try:
        while True:
            # Pick a completely random starting position (outside pool zone)
            k_rand  = random.randint(rand_lo, rand_hi)
            jump_num += 1
            engine.initialize(k_rand)

            for s in range(jump_every):
                if engine.current_key > k_end:
                    break  # ran past end — jump again

                found = engine.step()
                total_keys += engine.total_points

                if found:
                    for r in found:
                        k = r['k']
                        # ── СОХРАНЕНИЕ ПЕРВЫМ — до любых print/GPU операций ──
                        # Если комп зависнет сразу после — файл уже на диске.
                        _save_found_key(k, address)
                        # ─────────────────────────────────────────────────────
                        _save_stats()
                        print(f"\n{'!'*60}")
                        print(f"  KEY FOUND: {hex(k)}")
                        print(f"  Decimal:   {k}")
                        print(f"  WIF:       {_key_to_wif(k)}")
                        print(f"{'!'*60}")
                        if verify_key_address(k, address):
                            print("  [[OK]] Address verified!")
                        return k

                elapsed = time.time() - t_step
                if elapsed >= 1.0:
                    total_elapsed = time.time() - t_global
                    speed = total_keys / total_elapsed / 1e6 if total_elapsed > 0 else 0
                    print(f"\r[{time.strftime('%H:%M:%S')}] "
                          f"{speed:7.2f} Mkeys/s | "
                          f"Jumps: {jump_num:,} | "
                          f"Pos: {hex(engine.current_key)} | "
                          f"Total: {total_keys/1e12:.4f}T",
                          end='', flush=True)
                    t_step = time.time()

                    if time.time() - t_save >= 10.0:   # record work every ~10s
                        _save_stats(speed)
                        t_save = time.time()

    except KeyboardInterrupt:
        total_elapsed = time.time() - t_global
        speed = total_keys / total_elapsed / 1e6 if total_elapsed > 0 else 0
        _save_stats(speed)
        print(f"\n[PureRandom] Stopped. Keys checked: {total_keys:,}  "
              f"Speed: {speed:.1f} Mkeys/s  Jumps: {jump_num:,}")
        print(f"[PureRandom] Cumulative across runs: "
              f"{(prior_keys + total_keys)/1e12:.4f}T keys, "
              f"{prior_windows + jump_num:,} windows  -> {checkpoint_file}")
        return None


def gpu_search(address: str, k_start: int, k_end: int,
               device_idx:        int = 0,
               threads:           int = 64,
               blocks:            int = 1024,
               points_per_thread: int = 8,
               checkpoint_file:   str = 'checkpoint.json',
               random_mode:       bool = False,
               coverage_file:     str  = 'coverage.json',
               pure_random:       bool = False,
               jump_every:        int  = 200,
               pool_end:          int  = 0):
    """
    GPU search via PyOpenCL + BitCrack kernel.
    Optimized for AMD RX 6600 (gfx1032).

    random_mode=True : pick random uncovered segments instead of linear scan.
    pure_random=True  : TRUE random — reinitialize to random position every
                        jump_every steps. No coverage tracking. Best lottery mode.
    pool_end         : skip [k_start, pool_end) already covered by btcpuzzle.info pool.
    """
    # ── Pure random mode — TRUE random jumps ──────────────────────────────────
    if pure_random:
        return _pure_random_search(
            address, k_start, k_end, device_idx,
            threads, blocks, points_per_thread, jump_every, pool_end,
            checkpoint_file)

    cov = CoverageMap(coverage_file, k_start, k_end)
    chk = Checkpoint(checkpoint_file)

    # One-time engine init (reused across segments in random mode)
    engine = GPUSearchEngine(
        device_idx=device_idx,
        threads=threads,
        blocks=blocks,
        points_per_thread=points_per_thread,
    )
    target_words = get_target_for_kernel(address)
    engine.set_target(target_words)

    while True:
        # ----- Choose segment -----
        if random_mode:
            seg = cov.pick_random()
            if seg is None:
                print("\n[GPU] All segments covered! Full range searched.")
                return None
            seg_start, seg_end, seg_idx = seg
            print(f"\n[GPU] Random segment #{seg_idx}: "
                  f"[{hex(seg_start)}, {hex(seg_end)}]")
        else:
            # Linear: resume from checkpoint or k_start
            k_resume = chk.get_resume_key(k_start)
            seg_start = k_resume
            seg_end   = k_end
            seg_idx   = cov.seg_index(seg_start)
            if k_resume > k_start:
                print(f"[GPU] Resuming from checkpoint: {hex(k_resume)}")

        # ----- Init GPU for this segment -----
        engine.initialize(seg_start)

        seg_total  = seg_end - seg_start + 1
        keys_done  = 0
        t_global   = time.time()
        t_step     = time.time()
        step_count = 0

        print(f"\n{'='*60}")
        print(f"Bitcoin Puzzle Solver - GPU Mode")
        print(f"Address:   {address}")
        print(f"Segment:   [{hex(seg_start)}, {hex(seg_end)}]")
        print(f"Full range:[{hex(k_start)}, {hex(k_end)}]")
        print(f"Keys:      {seg_total:,}")
        print(f"KPS:       {engine.keys_per_step:,} keys/step")
        cov.print_status()
        print(f"{'='*60}")

        try:
            while engine.current_key <= seg_end:
                found = engine.step()

                if found:
                    for r in found:
                        k = r['k']
                        print(f"\n{'!'*60}")
                        print(f"  KEY FOUND: {hex(k)}")
                        print(f"  Decimal:   {k}")
                        print(f"  Address:   {address}")
                        print(f"{'!'*60}")
                        _save_found_key(k, address)
                        if verify_key_address(k, address):
                            print("[[OK]] Verified: key matches address")
                        else:
                            print("[!] WARNING: Verification failed!")
                        return k

                keys_done  += engine.keys_per_step
                step_count += 1
                elapsed     = time.time() - t_step

                if elapsed >= 1.0:
                    total_elapsed = time.time() - t_global
                    speed     = keys_done / total_elapsed / 1e6
                    progress  = 100.0 * (engine.current_key - seg_start) / max(seg_total, 1)
                    eta_s     = ((seg_total - keys_done) / (keys_done / total_elapsed)
                                 if keys_done > 0 else 0)
                    eta_str   = _fmt_eta(eta_s)
                    print(f"\r[{time.strftime('%H:%M:%S')}] "
                          f"{speed:7.2f} Mkeys/s | "
                          f"Seg: {progress:6.2f}% | "
                          f"Key: {hex(engine.current_key)} | "
                          f"ETA: {eta_str}  ",
                          end='', flush=True)
                    t_step = time.time()

                # Checkpoint every 10 steps (~3s)
                if step_count % 10 == 0:
                    total_elapsed = time.time() - t_global
                    speed = keys_done / total_elapsed / 1e6 if total_elapsed > 0 else 0
                    chk.save(engine.current_key, k_start, k_end,
                             address, keys_done, speed)

        except KeyboardInterrupt:
            total_elapsed = time.time() - t_global
            speed = keys_done / total_elapsed / 1e6 if total_elapsed > 0 else 0
            chk.save(engine.current_key, k_start, k_end, address, keys_done, speed)
            print(f"\n[GPU] Interrupted at {hex(engine.current_key)}")
            return None

        # Segment complete
        print(f"\n[GPU] Segment done: [{hex(seg_start)}, {hex(seg_end)}]")
        cov.mark_done(seg_idx)

        if not random_mode:
            # Linear mode: we scanned to the end
            return None


# ===========================================================================
# Встроенный тест
# ===========================================================================

def run_test():
    """
    Встроенный тест: верифицируем ECC и пробуем решить маленький пазл.
    Пазл #1 (k=1), пазл #5 (диапазон 16-31).
    """
    print("=" * 60)
    print("SELF-TEST")
    print("=" * 60)

    # --- ECC test ---
    print("\n[1] ECC arithmetic tests...")
    from ecc.curve import G, N, INF, point_add, scalar_mul, point_neg
    from ecc.field import P, inv

    # G на кривой
    gx, gy = G
    assert (gy * gy) % P == (gx * gx * gx + 7) % P, "G not on curve!"
    print("  [OK] G lies on curve y^2=x^3+7")

    # N*G = INF
    assert scalar_mul(N, G) == INF, "N*G != INF!"
    print("  [OK] N*G = INF")

    # 2*G = G+G
    assert scalar_mul(2, G) == point_add(G, G), "2*G != G+G!"
    print("  [OK] 2*G = G+G")

    # P + (-P) = INF
    ng = point_neg(G)
    assert point_add(G, ng) == INF, "G + (-G) != INF!"
    print("  [OK] G + (-G) = INF")

    # --- GLV test ---
    from ecc.glv import glv_decompose, glv_endomorphism, scalar_mul_glv, LAMBDA
    phi_G  = glv_endomorphism(G)
    lam_G  = scalar_mul(LAMBDA, G)
    assert phi_G == lam_G, "GLV endomorphism mismatch!"
    print("  [OK] phi(G) = lambda*G")

    k_test = 2**70 + 12345
    k1, k2 = glv_decompose(k_test)
    assert (k1 + k2 * LAMBDA) % N == k_test % N, "GLV decompose error!"
    print(f"  [OK] GLV decompose: k1={k1.bit_length()}bit, k2={k2.bit_length()}bit")

    glv_pt = scalar_mul_glv(k_test, G)
    std_pt = scalar_mul(k_test, G)
    assert glv_pt == std_pt, "GLV mul != std mul!"
    print("  [OK] GLV scalar_mul matches standard")

    # --- Address test ---
    print("\n[2] Address encoding/decoding tests...")
    from utils.address import (point_to_address, decode_address_hash160,
                                point_to_hash160_compressed, verify_key_address)

    # Пазл #1: k=1 → известный адрес
    pt1    = scalar_mul(1, G)
    addr1  = point_to_address(pt1[0], pt1[1])
    KNOWN1 = PUZZLES[1]['addr']
    assert addr1 == KNOWN1, f"Puzzle #1 address mismatch!\n  got: {addr1}\n  exp: {KNOWN1}"
    print(f"  [OK] Puzzle #1: k=1 -> {addr1}")

    h160_1 = decode_address_hash160(KNOWN1)
    assert len(h160_1) == 20, "hash160 should be 20 bytes"
    print(f"  [OK] Decode address hash160: {h160_1.hex()}")

    h160_from_pt = point_to_hash160_compressed(pt1[0], pt1[1])
    assert h160_from_pt == h160_1, "hash160 mismatch from point vs address!"
    print("  [OK] hash160 from point matches address")

    # target_for_kernel должен вернуть 5 слов
    from utils.address import get_target_for_kernel
    tw = get_target_for_kernel(KNOWN1)
    assert len(tw) == 5, "target_for_kernel must return 5 words"
    print(f"  [OK] target_for_kernel: {[hex(w) for w in tw]}")

    # --- Speed test ---
    print("\n[3] Speed test (1000 point additions)...")
    from ecc.curve import point_add
    t0 = time.perf_counter()
    pt = G
    for _ in range(1000):
        pt = point_add(pt, G)
    dt = time.perf_counter() - t0
    print(f"  1000 point_add = {dt*1000:.1f}ms  -> {1000/dt/1000:.1f} Kops/sec")

    # --- CPU puzzle mini-test ---
    print("\n[4] CPU mini-puzzle test (puzzle #1, k_range=1)...")
    result = cpu_search(PUZZLES[1]['addr'], 1, 10, 'checkpoint_test.json')
    if result == 1:
        print("  [OK] Found k=1 for puzzle #1")
    else:
        print(f"  [FAIL] Expected k=1, got {result}")
        return False

    # Cleanup
    import os
    if os.path.exists('checkpoint_test.json'):
        os.remove('checkpoint_test.json')

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED [OK]")
    print("=" * 60)
    return True


# ===========================================================================
# Kangaroo-режим (ECDLP с известным публичным ключом)
# ===========================================================================

def _parse_pubkey_hex(pubkey_hex: str) -> tuple:
    """
    Декодирует публичный ключ Bitcoin из hex-строки в (x, y).
    Поддерживает сжатый (33 байт, 02/03) и несжатый (65 байт, 04) форматы.
    """
    data = bytes.fromhex(pubkey_hex.strip())
    if len(data) == 33:
        prefix = data[0]
        if prefix not in (0x02, 0x03):
            raise ValueError(f"Invalid compressed prefix: {prefix:#x}")
        x = int.from_bytes(data[1:], 'big')
        from ecc.field import P
        y_sq = (pow(x, 3, P) + 7) % P
        y    = pow(y_sq, (P + 1) // 4, P)
        if (y % 2) != (prefix - 2):
            y = P - y
        return (x, y)
    elif len(data) == 65:
        if data[0] != 0x04:
            raise ValueError(f"Invalid uncompressed prefix: {data[0]:#x}")
        x = int.from_bytes(data[1:33],  'big')
        y = int.from_bytes(data[33:65], 'big')
        return (x, y)
    else:
        raise ValueError(f"Invalid pubkey length: {len(data)} (expected 33 or 65)")


def kangaroo_search(pubkey_hex: str, k_start: int, k_end: int,
                    device_idx: int = 0,
                    n_tame: int = 8192, n_wild: int = 8192,
                    dp_bits: int = 14,
                    tame_dp_file: str = None) -> int | None:
    """
    Kangaroo ECDLP-решатель на GPU — использовать когда публичный ключ ИЗВЕСТЕН.
    Сложность O(sqrt(range)) против O(range) у brute-force.

    pubkey_hex : публичный ключ в hex (33 или 65 байт)
    k_start    : нижняя граница диапазона
    k_end      : верхняя граница диапазона
    """
    from kangaroo.kangaroo_engine import KangarooEngine

    pubkey = _parse_pubkey_hex(pubkey_hex)
    x, y   = pubkey

    rng_size = k_end - k_start + 1
    expected = int(2.5 * rng_size ** 0.5)
    print(f"\n[Kangaroo] Pubkey: x={hex(x)[:24]}...")
    print(f"[Kangaroo] Range:  [{hex(k_start)}, {hex(k_end)}]  "
          f"({rng_size.bit_length()-1} bits)")
    print(f"[Kangaroo] Expected steps: ~{expected:,}  "
          f"(vs {rng_size:,} for brute-force)")

    engine = KangarooEngine(
        pubkey    = pubkey,
        k_start   = k_start,
        k_end     = k_end,
        device_idx= device_idx,
        n_tame    = n_tame,
        n_wild    = n_wild,
        dp_bits   = dp_bits,
    )
    return engine.solve(tame_dp_file=tame_dp_file)


# ===========================================================================
# Утилиты
# ===========================================================================

def _key_to_wif(k: int) -> str:
    """
    Конвертирует приватный ключ в WIF (Wallet Import Format), сжатый вариант.

    Формат: Base58Check( 0x80 | k_bytes(32) | 0x01 | checksum(4) )
      0x80  = mainnet prefix
      0x01  = compressed pubkey flag
    Используется для импорта в любой Bitcoin-кошелёк (Electrum, Bitcoin Core, etc.)
    """
    raw      = b'\x80' + k.to_bytes(32, 'big') + b'\x01'
    checksum = hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
    payload  = raw + checksum
    # Base58 encode
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    n = int.from_bytes(payload, 'big')
    result = ''
    while n > 0:
        n, r = divmod(n, 58)
        result = alphabet[r] + result
    for byte in payload:
        if byte == 0:
            result = '1' + result
        else:
            break
    return result


def _save_found_key(k: int, address: str):
    """
    Crash-safe сохранение найденного ключа.

    Алгоритм:
      1. НЕМЕДЛЕННО пишем минимальный файл (hex + WIF) с os.fsync() —
         гарантированно попадает на диск до любых дальнейших операций.
      2. Пишем полный файл с деталями.
      3. Пишем timestamped backup (защита от перезаписи).
      4. Пишем на рабочий стол (если доступен).
      5. Звуковое оповещение.

    Порядок важен: даже если комп зависнет сразу после вызова —
    хотя бы минимальный файл уже на диске.
    """
    wif       = _key_to_wif(k)
    ts        = time.strftime('%Y-%m-%d %H:%M:%S')
    ts_fname  = time.strftime('%Y%m%d_%H%M%S')

    # ── ШАГ 1: Минимальный аварийный файл, fsync ───────────────────────────
    # Пишем ТОЛЬКО ключ и WIF — максимально быстро, гарантированно на диск.
    emergency_content = (
        f"FOUND {ts}\n"
        f"HEX: {hex(k)}\n"
        f"WIF: {wif}\n"
        f"ADDR: {address}\n"
    )
    for fname_em in ['FOUND_KEY_EMERGENCY.txt',
                     f'FOUND_KEY_{ts_fname}.txt']:
        try:
            with open(fname_em, 'w') as f:
                f.write(emergency_content)
                f.flush()
                os.fsync(f.fileno())   # ← гарантированная запись на диск
        except Exception:
            pass

    # ── ШАГ 2: Полный файл ─────────────────────────────────────────────────
    full_content = (
        f"BITCOIN PUZZLE SOLVED!\n"
        f"{'='*40}\n"
        f"Private key (hex):  {hex(k)}\n"
        f"Private key (dec):  {k}\n"
        f"Private key (WIF):  {wif}\n"
        f"Bitcoin address:    {address}\n"
        f"Found at:           {ts}\n"
        f"\n{'='*40}\n"
        f"BROADCAST VIA MARA SLIPSTREAM (MEV-protected):\n"
        f"  https://slipstream.mara.com\n"
        f"\nIMPORT INTO ELECTRUM / BITCOIN CORE:\n"
        f"  importprivkey {wif}\n"
    )
    for fname_full in ['FOUND_KEY.txt', f'FOUND_KEY_FULL_{ts_fname}.txt']:
        try:
            with open(fname_full, 'w') as f:
                f.write(full_content)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            pass

    # ── ШАГ 3: Рабочий стол (если доступен) ───────────────────────────────
    try:
        desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
        if os.path.isdir(desktop):
            desk_file = os.path.join(desktop, 'BITCOIN_FOUND.txt')
            with open(desk_file, 'w') as f:
                f.write(full_content)
                f.flush()
                os.fsync(f.fileno())
    except Exception:
        pass

    # ── ШАГ 4: Звуковое оповещение (Windows) ──────────────────────────────
    try:
        import winsound
        for _ in range(10):
            winsound.Beep(1000, 300)
            time.sleep(0.1)
    except Exception:
        # Fallback: ASCII bell
        for _ in range(5):
            print('\a', end='', flush=True)
            time.sleep(0.2)

    print(f"\nKey saved to FOUND_KEY.txt  +  FOUND_KEY_{ts_fname}.txt")
    print(f"  WIF: {wif}")
    print(f"  Broadcast: https://slipstream.mara.com")


def _fmt_eta(seconds: float) -> str:
    if seconds <= 0 or seconds > 365 * 24 * 3600:
        return "inf"
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    m = int((seconds % 3600) // 60)
    if d > 0:
        return f"{d}d {h}h"
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m {int(seconds%60)}s"


def _benchmark_gpu(device_idx: int = 0, threads: int = DEFAULT_THREADS,
                   blocks: int = DEFAULT_BLOCKS, points: int = DEFAULT_POINTS_PER_THREAD):
    """Замеряет скорость GPU на одном шаге."""
    engine = GPUSearchEngine(device_idx=device_idx, threads=threads,
                             blocks=blocks, points_per_thread=points)
    engine.set_target(get_target_for_kernel(PUZZLES[71]['addr']))
    engine.initialize(PUZZLES[71]['start'])

    print("[BENCH] Warming up (3 steps)...")
    for _ in range(3):
        engine.step()

    print("[BENCH] Measuring (10 steps)...")
    t0 = time.perf_counter()
    for _ in range(10):
        engine.step()
    dt  = time.perf_counter() - t0
    kps = engine.keys_per_step * 10 / dt / 1e6
    print(f"[BENCH] Speed: {kps:.2f} Mkeys/sec")
    print(f"[BENCH] {engine.keys_per_step:,} keys/step x10 steps = "
          f"{engine.keys_per_step*10:,} keys in {dt:.3f}s")


def _benchmark_sweep(device_idx: int = 0,
                     threads_grid: list = None,
                     blocks_grid:  list = None,
                     points_grid:  list = None,
                     n_warmup: int = 3, n_measure: int = 15):
    """
    Systematic GPU parameter sweep (baseline -> grid -> statistical
    confidence -> winner), in the spirit of disciplined performance
    benchmarking: never tune on a single sample, always measure
    per-step latency distribution (mean/std/p95), not just a lump sum.

    Reports Mkeys/s for every (threads, blocks, points_per_thread)
    combination so you can pick a config backed by data instead of guesses.
    """
    threads_grid = threads_grid or [64, 128, 256]
    blocks_grid  = blocks_grid  or [1024, 2048, 4096]
    # NOTE: the old grid capped points at 32 and badly under-reported the
    # optimum. On RX 6600 throughput keeps climbing to ~120 pts/thread
    # (peak ~406 Mkeys/s) then falls off a VRAM cliff above ~33M work-items.
    points_grid  = points_grid  or [32, 64, 96, 112, 120]

    # 8GB RDNA2 collapses hard once the point working-set passes ~33-34M
    # work-items (measured: 33.5M=ok, 42M=110 Mkeys/s, 50M=85). Skip those
    # combos so the sweep doesn't waste minutes benching guaranteed losers.
    VRAM_CLIFF_N = 34_000_000

    combos = [(t, b, p) for t in threads_grid for b in blocks_grid for p in points_grid
              if t * b * p <= VRAM_CLIFF_N]
    print(f"\n{'='*70}")
    print(f"  GPU PARAMETER SWEEP — {len(combos)} configurations")
    print(f"  (warmup={n_warmup} steps, measure={n_measure} steps per config)")
    print(f"{'='*70}\n")

    results = []
    for i, (t, b, p) in enumerate(combos, 1):
        n_total = t * b * p
        try:
            engine = GPUSearchEngine(device_idx=device_idx, threads=t,
                                     blocks=b, points_per_thread=p)
            engine.set_target(get_target_for_kernel(PUZZLES[71]['addr']))
            engine.initialize(PUZZLES[71]['start'])

            for _ in range(n_warmup):
                engine.step()

            step_times = []
            for _ in range(n_measure):
                t0 = time.perf_counter()
                engine.step()
                step_times.append(time.perf_counter() - t0)

            mean_t  = sum(step_times) / len(step_times)
            std_t   = (sum((x - mean_t) ** 2 for x in step_times) / len(step_times)) ** 0.5
            sorted_t = sorted(step_times)
            p95_t    = sorted_t[int(0.95 * (len(sorted_t) - 1))]

            mkeys_mean = engine.keys_per_step / mean_t / 1e6
            mkeys_p95  = engine.keys_per_step / p95_t / 1e6  # worst-case-ish throughput

            results.append({
                'threads': t, 'blocks': b, 'points': p, 'n_total': n_total,
                'mkeys_mean': mkeys_mean, 'mkeys_p95': mkeys_p95,
                'std_pct': std_t / mean_t * 100,
            })
            print(f"  [{i:>2}/{len(combos)}] t={t:>3} b={b:>5} pts={p:>3}  "
                  f"N={n_total:>10,}  {mkeys_mean:>7.1f} Mkeys/s  "
                  f"(p95={mkeys_p95:>7.1f}  std={std_t/mean_t*100:>4.1f}%)")
        except Exception as e:
            print(f"  [{i:>2}/{len(combos)}] t={t:>3} b={b:>5} pts={p:>3}  FAILED: {e}")

    if not results:
        print("\n[!] All configurations failed.")
        return

    results.sort(key=lambda r: r['mkeys_mean'], reverse=True)
    best = results[0]
    baseline = next((r for r in results if r['threads'] == DEFAULT_THREADS
                     and r['blocks'] == DEFAULT_BLOCKS
                     and r['points'] == DEFAULT_POINTS_PER_THREAD), None)

    print(f"\n{'='*70}")
    print(f"  RESULTS — top 5 by mean throughput")
    print(f"{'='*70}")
    for r in results[:5]:
        print(f"  t={r['threads']:>3} b={r['blocks']:>5} pts={r['points']:>3}  "
              f"{r['mkeys_mean']:>7.1f} Mkeys/s  (std={r['std_pct']:.1f}%)")

    print(f"\n  WINNER: threads={best['threads']} blocks={best['blocks']} "
          f"points_per_thread={best['points']}  ->  {best['mkeys_mean']:.1f} Mkeys/s")
    if baseline and baseline is not best:
        speedup = best['mkeys_mean'] / baseline['mkeys_mean']
        print(f"  vs current default ({DEFAULT_THREADS}/{DEFAULT_BLOCKS}/"
              f"{DEFAULT_POINTS_PER_THREAD} = {baseline['mkeys_mean']:.1f} Mkeys/s): "
              f"{speedup:.2f}x")
    print(f"\n  To use: python main.py --puzzle 71 --mode gpu --pure-random "
          f"--threads {best['threads']} --blocks {best['blocks']} "
          f"--points {best['points']} --pool-avoid")
    print(f"  Note: this measures raw step throughput only. Larger N also makes "
          f"initialize() slower — re-check --jump-every overhead with the chosen config.")


# ===========================================================================
# CLI
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Bitcoin Puzzle Solver - AMD RX 6600 Edition',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--puzzle',   type=int, default=71,
                        help='Puzzle number (default: 71)')
    parser.add_argument('--mode',     choices=['gpu', 'cpu', 'kangaroo'], default='gpu',
                        help='Search mode: gpu (brute-force), cpu (brute-force), '
                             'kangaroo (ECDLP with known pubkey, requires --pubkey)')
    parser.add_argument('--device',   type=int, default=0,
                        help='OpenCL device index (default: 0)')
    parser.add_argument('--threads',  type=int, default=DEFAULT_THREADS,
                        help=f'Threads per block (default: {DEFAULT_THREADS})')
    parser.add_argument('--blocks',   type=int, default=DEFAULT_BLOCKS,
                        help=f'Number of blocks (default: {DEFAULT_BLOCKS})')
    parser.add_argument('--points',   type=int, default=DEFAULT_POINTS_PER_THREAD,
                        help=f'Points per thread (default: {DEFAULT_POINTS_PER_THREAD})')
    parser.add_argument('--checkpoint', default='checkpoint.json',
                        help='Checkpoint file (default: checkpoint.json)')
    parser.add_argument('--random',      action='store_true',
                        help='Random segment mode: pick uncovered segments randomly')
    parser.add_argument('--pure-random', action='store_true',
                        help='TRUE random: jump to random positions every --jump-every steps. '
                             'Best lottery mode — no sequential pattern, no coverage tracking.')
    parser.add_argument('--jump-every',  type=int, default=200,
                        help='Steps between random jumps in --pure-random mode (default: 200 '
                             '≈ 6.7B keys/window at 33.5M pts/step, ~5%% reinit overhead)')
    parser.add_argument('--pool-avoid', action='store_true',
                        help='Skip region already covered by btcpuzzle.info pool (~0.86%% of range). '
                             'Pool scans sequentially from start; we cover rest randomly.')
    parser.add_argument('--coverage',    default='coverage.json',
                        help='Coverage map file (default: coverage.json)')
    parser.add_argument('--test',     action='store_true',
                        help='Run built-in self-test')
    parser.add_argument('--bench',    action='store_true',
                        help='GPU benchmark (single config)')
    parser.add_argument('--bench-sweep', action='store_true',
                        help='Systematic GPU parameter sweep (threads x blocks x '
                             'points_per_thread grid) to find the fastest config '
                             'for your specific GPU')
    parser.add_argument('--devices',  action='store_true',
                        help='List OpenCL devices')
    parser.add_argument('--status',   action='store_true',
                        help='Show checkpoint + coverage status')
    parser.add_argument('--reset',    action='store_true',
                        help='Delete checkpoint and start fresh')
    parser.add_argument('--pubkey',   type=str, default='',
                        help='Target public key hex (33 or 65 bytes) for --mode kangaroo')
    parser.add_argument('--n-tame',   type=int, default=8192,
                        help='Tame kangaroos count (default: 8192; offsets are '
                             'computed GPU-side so init stays ~0.1s)')
    parser.add_argument('--n-wild',   type=int, default=8192,
                        help='Wild kangaroos count (default: 8192)')
    parser.add_argument('--dp-bits',         type=int, default=0,
                        help='Distinguished point filter bits. Default 0 = pick '
                             'automatically from the range so DP detection does '
                             'not dominate the solve. Override only if you know why.')
    parser.add_argument('--precompute-tame', action='store_true',
                        help='Pre-compute tame kangaroo DPs and save to tame_dps_<puzzle>.pkl '
                             '(no pubkey needed). Load later with --tame-dps for 2x faster solve.')
    parser.add_argument('--tame-dps',        type=str, default='',
                        help='Path to pre-computed tame DPs file (from --precompute-tame). '
                             'If set, solve() pre-seeds table and only wild kangaroos need to collide.')

    args = parser.parse_args()

    if args.devices:
        from kangaroo.gpu_search import list_devices
        list_devices()
        return

    if args.test:
        ok = run_test()
        sys.exit(0 if ok else 1)

    if args.status:
        Checkpoint(args.checkpoint).print_status()
        pz = PUZZLES[args.puzzle if hasattr(args, 'puzzle') else 71]
        CoverageMap(args.coverage, pz['start'], pz['end']).print_status()
        return

    if args.reset:
        if os.path.exists(args.checkpoint):
            os.remove(args.checkpoint)
            print(f"Checkpoint deleted: {args.checkpoint}")
        else:
            print("No checkpoint to delete.")
        return

    if args.bench:
        _benchmark_gpu(args.device, args.threads, args.blocks, args.points)
        return

    if args.bench_sweep:
        _benchmark_sweep(args.device)
        return

    if args.puzzle not in PUZZLES:
        known = sorted(PUZZLES.keys())
        print(f"Unknown puzzle #{args.puzzle}. Known range: #{known[0]}-#{known[-1]}")
        print(f"Run 'python analysis/puzzle_status.py --unsolved' to see which "
              f"puzzles are currently unsolved, or CHOOSE_PUZZLE.bat for a menu.")
        sys.exit(1)

    pz = PUZZLES[args.puzzle]
    print(f"\nTarget: Bitcoin Puzzle #{args.puzzle}")
    print(f"Address: {pz['addr']}")
    print(f"Range:   [{hex(pz['start'])}, {hex(pz['end'])}]")
    print(f"Size:    {pz['end'] - pz['start'] + 1:,} keys\n")

    # ── Precompute tame DPs (no pubkey needed) ────────────────────────────────
    if args.precompute_tame:
        from kangaroo.kangaroo_engine import KangarooEngine
        save_path = f'tame_dps_puzzle{args.puzzle}.pkl'
        engine = KangarooEngine(
            pubkey     = None,
            k_start    = pz['start'],
            k_end      = pz['end'],
            device_idx = args.device,
            n_tame     = args.n_tame,
            n_wild     = args.n_wild,
            dp_bits    = args.dp_bits,
        )
        n = engine.precompute_tame(save_path=save_path)
        print(f"\n[PrecomputeTame] Done: {n:,} tame DPs saved to {save_path}")
        print(f"[PrecomputeTame] Run with: --tame-dps {save_path} to use pre-computed table")
        return

    if args.mode == 'kangaroo':
        if not args.pubkey:
            print("[!] --mode kangaroo requires --pubkey PUBKEY_HEX\n"
                  "    Use monitor.py to watch for the pubkey to appear on-chain.")
            sys.exit(1)
        result = kangaroo_search(
            pubkey_hex  = args.pubkey,
            k_start     = pz['start'],
            k_end       = pz['end'],
            device_idx  = args.device,
            n_tame      = args.n_tame,
            n_wild      = args.n_wild,
            dp_bits     = args.dp_bits,
            tame_dp_file= args.tame_dps if args.tame_dps else None,
        )
    elif args.mode == 'cpu':
        result = cpu_search(
            address        = pz['addr'],
            k_start        = pz['start'],
            k_end          = pz['end'],
            checkpoint_file = args.checkpoint,
        )
    else:
        pool_end = 0
        if getattr(args, 'pool_avoid', False):
            pool_end = _get_pool_end(args.puzzle, pz)

        result = gpu_search(
            address            = pz['addr'],
            k_start            = pz['start'],
            k_end              = pz['end'],
            device_idx         = args.device,
            threads            = args.threads,
            blocks             = args.blocks,
            points_per_thread  = args.points,
            checkpoint_file    = args.checkpoint,
            random_mode        = args.random,
            coverage_file      = args.coverage,
            pure_random        = args.pure_random,
            jump_every         = args.jump_every,
            pool_end           = pool_end,
        )

    if result:
        print(f"\n[!] Puzzle #{args.puzzle} SOLVED! Key = {hex(result)}")
    else:
        print(f"\nPuzzle #{args.puzzle}: Key not found in searched range.")


if __name__ == '__main__':
    main()
