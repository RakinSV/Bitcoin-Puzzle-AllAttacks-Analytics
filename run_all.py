#!/usr/bin/env python3
"""
run_all.py — Максимальная стратегия Bitcoin Puzzle

Запускает три параллельных стратегии одновременно:

  [1] GPU БРУТФОРС (фоновый процесс)
      Перебирает диапазон [2^70, 2^71-1] случайными сегментами 24/7.
      Шанс мал, но ненулевой. Покрытие сохраняется в coverage.json.

  [2] PRE-WARM KANGAROO GPU (в памяти, ждёт)
      Компилирует OpenCL ядро, строит jump table, выделяет VRAM.
      Когда pubkey найден — запускается МГНОВЕННО (0 секунд инициализации).

  [3] БЫСТРЫЙ МОНИТОРИНГ (главный поток)
      По умолчанию: HTTP polling каждые 30s (lightweight).
      С --websocket: WebSocket mempool.space — обнаружение < 1 секунды!

Когда pubkey раскрывается в мемпуле:
  → Pre-warmed Kangaroo стартует немедленно
  → Ожидаемое время до ключа: ~3 минуты (RX 6600, n=16384)
  → Ключ сохраняется в FOUND_KEY.txt с WIF
  → Инструкция для broadcast через MARA Slipstream

Использование:
  python run_all.py                   # стандарт: брутфорс + монитор
  python run_all.py --no-brute        # только монитор + pre-warm
  python run_all.py --websocket       # WebSocket вместо polling
  python run_all.py --puzzle 71 -n 16384  # кастомные параметры
"""

import sys
import os
import time
import threading
import subprocess
import argparse
import hashlib

sys.path.insert(0, os.path.dirname(__file__))

from main    import PUZZLES, _save_found_key, _key_to_wif
from monitor import (check_puzzle, on_pubkey_found,
                     monitor, monitor_websocket,
                     get_spent_txo_count)


# ---------------------------------------------------------------------------
# Баннер
# ---------------------------------------------------------------------------

BANNER = r"""
+----------------------------------------------------------+
|       BITCOIN PUZZLE SOLVER - MAKSIMALNAYA STRATEGIYA   |
|       GLV + Negation + Pre-warm + WebSocket             |
+----------------------------------------------------------+
"""


# ---------------------------------------------------------------------------
# Pre-warm engine loader
# ---------------------------------------------------------------------------

def precompute_tame_async(engine, puzzle_num: int,
                          n_iters: int = 4000) -> threading.Thread:
    """
    Запускает предвычисление tame DP в фоновом потоке.
    Tame-кенгуру не зависят от pubkey → можно считать ЗАРАНЕЕ.
    Файл tame_dps_puzzle{N}.pkl будет готов когда придёт pubkey.
    """
    save_path = f'tame_dps_puzzle{puzzle_num}.pkl'
    import os
    if os.path.exists(save_path):
        print(f"[TameCache] {save_path} уже существует — пропускаем пересчёт")
        return None

    def _worker():
        print(f"\n[TameCache] Старт фонового предвычисления ({n_iters} итераций)...")
        try:
            n = engine.precompute_tame(save_path=save_path, n_iters=n_iters)
            print(f"\n[TameCache] Готово: {n:,} tame DPs -> {save_path}")
            print(f"[TameCache] Следующий solve() будет в ~2x быстрее!")
        except Exception as e:
            print(f"\n[TameCache] Ошибка: {e}")

    t = threading.Thread(target=_worker, daemon=True, name='TamePrecompute')
    t.start()
    print(f"[TameCache] Фоновое предвычисление запущено (PID-поток: TamePrecompute)")
    return t


def prewarm_engine(puzzle_num: int, n_tame: int, n_wild: int,
                   device_idx: int = 0) -> object:
    """
    Создаёт KangarooEngine без pubkey:
    - Компилирует OpenCL ядро
    - Строит jump table (GLV ускорение)
    - Выделяет VRAM

    Возвращает готовый engine, который запустится немедленно при
    вызове engine.solve(pubkey=...).
    """
    from kangaroo.kangaroo_engine import KangarooEngine

    pz = PUZZLES[puzzle_num]
    print(f"\n[PreWarm] Warming up Kangaroo engine for puzzle #{puzzle_num}...")
    print(f"[PreWarm] n_tame={n_tame}  n_wild={n_wild}  "
          f"(birthday speedup: {n_tame}x)")

    t0 = time.time()
    engine = KangarooEngine(
        pubkey     = None,
        k_start    = pz['start'],
        k_end      = pz['end'],
        device_idx = device_idx,
        n_tame     = n_tame,
        n_wild     = n_wild,
    )
    elapsed = time.time() - t0
    print(f"[PreWarm] Engine ready in {elapsed:.1f}s — will fire instantly on pubkey!\n")
    return engine


# ---------------------------------------------------------------------------
# Brute-force subprocess launcher
# ---------------------------------------------------------------------------

def start_brute_force(puzzle_num: int, device_idx: int = 0,
                      pure_random: bool = True,
                      jump_every:  int  = 200) -> subprocess.Popen:
    """
    Запускает брутфорс GPU как отдельный процесс.

    pure_random=True  (по умолчанию): TRUE random jumps — прыгает в случайные
                      позиции каждые jump_every шагов. Нет паттерна "нулей".
    pure_random=False: случайные СЕГМЕНТЫ (старый режим), coverage.json.
    """
    cmd = [
        sys.executable,
        os.path.join(os.path.dirname(__file__), 'main.py'),
        '--puzzle', str(puzzle_num),
        '--mode',   'gpu',
        '--device', str(device_idx),
    ]
    if pure_random:
        cmd += ['--pure-random', '--jump-every', str(jump_every)]
        mode_str = f'pure-random (jump every {jump_every} steps)'
    else:
        cmd += ['--random']
        mode_str = 'random segments (coverage.json)'

    print(f"[BruteForce] Starting GPU search: {mode_str}")
    print(f"[BruteForce] cmd: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd)
    print(f"[BruteForce] PID={proc.pid}\n")
    return proc


# ---------------------------------------------------------------------------
# Callback: когда pubkey найден — немедленно запускаем Kangaroo
# ---------------------------------------------------------------------------

def make_solve_callback(engine, puzzle_num: int):
    """Возвращает функцию, которая запускается когда pubkey найден."""
    pz = PUZZLES[puzzle_num]

    def on_pubkey(pk_bytes: bytes):
        t_detect = time.time()
        pk_hex   = pk_bytes.hex()

        print(f"\n{'!'*60}")
        print(f"  PUBKEY ОБНАРУЖЕН! ЗАПУСКАЕМ KANGAROO!")
        print(f"  Pubkey: {pk_hex}")
        print(f"{'!'*60}\n")

        # Декодируем pubkey → (x, y)
        from main import _parse_pubkey_hex
        try:
            pubkey = _parse_pubkey_hex(pk_hex)
        except Exception as e:
            print(f"[!] Ошибка декодирования pubkey: {e}")
            return

        # Kangaroo стартует НЕМЕДЛЕННО (engine уже прогрет)
        tame_file = f'tame_dps_puzzle{puzzle_num}.pkl'
        import os as _os
        if _os.path.exists(tame_file):
            print(f"[Kangaroo] Загружаем pre-computed tame DPs из {tame_file} -> 2x faster!")
        print(f"[Kangaroo] Старт! Время с обнаружения pubkey: 0s (engine pre-warmed)")
        k = engine.solve(pubkey=pubkey, tame_dp_file=tame_file, verbose=True)

        if k is not None:
            elapsed = time.time() - t_detect
            print(f"\n{'='*60}")
            print(f"  КЛЮЧ НАЙДЕН! Прошло {elapsed:.1f}s с момента обнаружения pubkey")
            print(f"  k = {hex(k)}")
            print(f"  WIF = {_key_to_wif(k)}")
            print(f"{'='*60}")
            _save_found_key(k, pz['addr'])
            sys.exit(0)
        else:
            print("[!] Kangaroo не нашёл ключ — повторяем...")

    return on_pubkey


# ---------------------------------------------------------------------------
# Главный runner
# ---------------------------------------------------------------------------

def run_all(puzzle_num:   int  = 71,
            n_tame:       int  = 16384,
            n_wild:       int  = 16384,
            device_idx:   int  = 0,
            use_brute:    bool = True,
            pure_random:  bool = True,
            jump_every:   int  = 200,
            use_ws:       bool = False,
            interval:     int  = 30,
            tame_iters:   int  = 4000):

    print(BANNER)
    pz = PUZZLES[puzzle_num]
    print(f"Цель:     Bitcoin Puzzle #{puzzle_num}")
    print(f"Адрес:    {pz['addr']}")
    print(f"Диапазон: [2^70, 2^71-1]  ({(pz['end'] - pz['start']).bit_length()-1} бит)")
    print(f"Приз:     ~7.1 BTC (проверяем при старте)\n")

    brute_proc = None

    try:
        # ── Шаг 1: Pre-warm Kangaroo ──────────────────────────────────────
        engine = prewarm_engine(puzzle_num, n_tame, n_wild, device_idx)

        # ── Шаг 1b: Tame DP предвычисление (фоновый поток) ───────────────
        tame_thread = precompute_tame_async(engine, puzzle_num, tame_iters)

        # ── Шаг 2: Брутфорс в фоне ───────────────────────────────────────
        if use_brute:
            brute_proc = start_brute_force(puzzle_num, device_idx, pure_random, jump_every)
            print(f"[Strategy] Брутфорс запущен (PID {brute_proc.pid})")
        else:
            print("[Strategy] Брутфорс: ВЫКЛ (--no-brute)")

        # ── Шаг 3: Callback для мгновенного Kangaroo ─────────────────────
        callback = make_solve_callback(engine, puzzle_num)

        # ── Шаг 4: Мониторинг ────────────────────────────────────────────
        print(f"[Strategy] Мониторинг: {'WebSocket (instant)' if use_ws else f'polling {interval}s'}")
        tame_file = f'tame_dps_puzzle{puzzle_num}.pkl'
        import os as _os2
        tame_status = ('готов ' + tame_file if _os2.path.exists(tame_file)
                       else 'вычисляется в фоне...')
        print(f"\nСтатистика:")
        print(f"  Engine:     ПРОГРЕТ (старт за 0s при обнаружении pubkey)")
        print(f"  Tame DPs:   {tame_status}")
        print(f"  Брутфорс:   {'pure-random' if (use_brute and pure_random) else 'фон' if use_brute else 'выкл'}")
        print(f"  Монитор:    {'WS' if use_ws else f'poll/{interval}s'}")
        print(f"  ETA Kang:   ~3 мин без tame cache / ~1.5 мин с tame cache\n")

        if use_ws:
            monitor_websocket(puzzle_num,
                              on_found_callback=callback,
                              fallback_interval=interval)
        else:
            monitor(puzzle_num,
                    interval=interval,
                    on_found_callback=callback)

    except KeyboardInterrupt:
        print("\n\n[!] Прерывание пользователем.")

    finally:
        if brute_proc and brute_proc.poll() is None:
            print(f"[BruteForce] Останавливаем PID {brute_proc.pid}...")
            brute_proc.terminate()
            try:
                brute_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                brute_proc.kill()
            print("[BruteForce] Остановлен.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Bitcoin Puzzle — максимальная стратегия',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--puzzle',    type=int,  default=71,
                        help='Номер пазла (default: 71)')
    parser.add_argument('-n', '--n-tame', type=int, default=16384,
                        help='Kangaroo: tame count (default: 16384)')
    parser.add_argument('--n-wild',    type=int,  default=16384,
                        help='Kangaroo: wild count (default: 16384)')
    parser.add_argument('--device',    type=int,  default=0,
                        help='OpenCL device index (default: 0)')
    parser.add_argument('--no-brute',    action='store_true',
                        help='Не запускать GPU брутфорс')
    parser.add_argument('--no-pure-random', action='store_true',
                        help='Использовать старый режим случайных сегментов вместо pure-random')
    parser.add_argument('--jump-every',  type=int,  default=200,
                        help='Шаги между прыжками в pure-random (default: 200)')
    parser.add_argument('--tame-iters', type=int,  default=4000,
                        help='Итераций для предвычисления tame DPs (default: 4000)')
    parser.add_argument('--websocket',   action='store_true',
                        help='WebSocket мониторинг (instant, '
                             'требует: pip install websockets)')
    parser.add_argument('--interval',    type=int,  default=30,
                        help='Polling interval в секундах (default: 30)')
    args = parser.parse_args()

    if args.puzzle not in PUZZLES:
        print(f"Неизвестный пазл #{args.puzzle}. Доступны: {sorted(PUZZLES.keys())}")
        sys.exit(1)

    run_all(
        puzzle_num  = args.puzzle,
        n_tame      = args.n_tame,
        n_wild      = args.n_wild,
        device_idx  = args.device,
        use_brute   = not args.no_brute,
        pure_random = not args.no_pure_random,
        jump_every  = args.jump_every,
        use_ws      = args.websocket,
        interval    = args.interval,
        tame_iters  = args.tame_iters,
    )


if __name__ == '__main__':
    main()
