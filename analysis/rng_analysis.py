#!/usr/bin/env python3
"""
Bitcoin Puzzle RNG Pattern Analysis
====================================
Анализирует известные ключи пазлов #1-#65 и пытается найти паттерн ГПСЧ.

Если создатель использовал предсказуемый генератор случайных чисел,
мы можем вычислить ключ #71 напрямую — без перебора!

Источник ключей: https://privatekeys.pw/puzzles/bitcoin-puzzle-tx

Стратегии:
  1. Python random.Random(seed) — проверяет 0..MAX_SEED
  2. SHA256-based — hash("puzzle71"), hash(seed_str), etc.
  3. Биты паттерн — анализ позиции ключа внутри диапазона
  4. Линейная регрессия — предсказание позиции по предыдущим

Usage:
  python analysis/rng_analysis.py           # full analysis
  python analysis/rng_analysis.py --quick   # только быстрые тесты
  python analysis/rng_analysis.py --predict # предсказать ключ #71
"""

import sys
import os
import random
import hashlib
import struct
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ===========================================================================
# Известные ключи пазлов Bitcoin (публично раскрытые)
# Источник: https://privatekeys.pw/puzzles/bitcoin-puzzle-tx
# ===========================================================================

# Формат: {puzzle_num: private_key_int}
# Ключ #N находится в диапазоне [2^(N-1), 2^N - 1]
KNOWN_KEYS = {
     1: 0x1,  # 1
     2: 0x3,  # 3
     3: 0x7,  # 7
     4: 0x8,  # 8
     5: 0x15,  # 21
     6: 0x31,  # 49
     7: 0x4c,  # 76
     8: 0xe0,  # 224
     9: 0x1d3,  # 467
    10: 0x202,  # 514
    11: 0x483,  # 1155
    12: 0xa7b,  # 2683
    13: 0x1460,  # 5216
    14: 0x2930,  # 10544
    15: 0x68f3,  # 26867
    16: 0xc936,  # 51510
    17: 0x1764f,  # 95823
    18: 0x3080d,  # 198669
    19: 0x5749f,  # 357535
    20: 0xd2c55,  # 863317
    21: 0x1ba534,  # 1811764
    22: 0x2de40f,  # 3007503
    23: 0x556e52,  # 5598802
    24: 0xdc2a04,  # 14428676
    25: 0x1fa5ee5,  # 33185509
    26: 0x340326e,  # 54538862
    27: 0x6ac3875,  # 111949941
    28: 0xd916ce8,  # 227634408
    29: 0x17e2551e,  # 400708894
    30: 0x3d94cd64,  # 1033162084
    31: 0x7d4fe747,  # 2102388551
    32: 0xb862a62e,  # 3093472814
    33: 0x1a96ca8d8,  # 7137437912
    34: 0x34a65911d,  # 14133072157
    35: 0x4aed21170,  # 20112871792
    36: 0x9de820a7c,  # 42387769980
    37: 0x1757756a93,  # 100251560595
    38: 0x22382facd0,  # 146971536592
    39: 0x4b5f8303e9,  # 323724968937
    40: 0xe9ae4933d6,  # 1003651412950
    41: 0x153869acc5b,  # 1458252205147
    42: 0x2a221c58d8f,  # 2895374552463
    43: 0x6bd3b27c591,  # 7409811047825
    44: 0xe02b35a358f,  # 15404761757071
    45: 0x122fca143c05,  # 19996463086597
    46: 0x2ec18388d544,  # 51408670348612
    47: 0x6cd610b53cba,  # 119666659114170
    48: 0xade6d7ce3b9b,  # 191206974700443
    49: 0x174176b015f4d,  # 409118905032525
    50: 0x22bd43c2e9354,  # 611140496167764
    # Puzzles 51-70 (source: btcpuzzle.info, verified 2026-06)
    51: 0x75070a1a009d4,
    52: 0xefae164cb9e3c,
    53: 0x180788e47e326c,
    54: 0x236fb6d5ad1f43,
    55: 0x6abe1f9b67e114,
    56: 0x9d18b63ac4ffdf,
    57: 0x1eb25c90795d61c,
    58: 0x2c675b852189a21,
    59: 0x7496cbb87cab44f,
    60: 0xfc07a1825367bbe,
    61: 0x13c96a3742f64906,
    62: 0x363d541eb611abee,
    63: 0x7cce5efdaccf6808,
    64: 0xf7051f27b09112d4,
    65: 0x1a838b13505b26867,
    66: 0x2832ed74f2b5e35ee,
    67: 0x730fc235c1942c1ae,
    68: 0xbebb3940cd0fc1491,
    69: 0x101d83275fb2bc7e0c,
    70: 0x349b84b6431a6c4ef1,
}

# Диапазоны пазлов: ключ #N ∈ [2^(N-1), 2^N - 1]
def puzzle_range(n: int) -> tuple:
    return (1 << (n - 1), (1 << n) - 1)

def puzzle_position(n: int, key: int) -> float:
    """Нормализованная позиция ключа в диапазоне: 0.0 = начало, 1.0 = конец."""
    lo, hi = puzzle_range(n)
    return (key - lo) / (hi - lo)


# ===========================================================================
# Анализ 1: Паттерн позиций
# ===========================================================================

def analyze_positions(target: int = 71):
    """Смотрим где в своём диапазоне находится каждый ключ."""
    print("\n" + "="*60)
    print("АНАЛИЗ ПОЗИЦИЙ КЛЮЧЕЙ В ДИАПАЗОНЕ")
    print("="*60)
    print(f"{'#':>4}  {'Ключ (hex)':>20}  {'Позиция':>8}  {'Бит-паттерн'}")
    print("-"*60)

    positions = []
    for n, k in sorted(KNOWN_KEYS.items()):
        lo, hi = puzzle_range(n)
        if hi == lo:   # puzzle #1 range = [1,1], skip
            continue
        pos = (k - lo) / (hi - lo)
        positions.append(pos)
        # Pattern: first 4 bits after leading 1
        bits = bin(k)[3:7] if len(bin(k)) > 3 else '???'
        print(f"  {n:>2}  {hex(k):>20}  {pos:>7.4f}   {bits}")

    if positions:
        avg = sum(positions) / len(positions)
        print(f"\n  Среднее позиций: {avg:.4f}  (ожидается 0.5 для чистого рандома)")
        print(f"  Мин: {min(positions):.4f}  Макс: {max(positions):.4f}")

        # Предсказание для целевого пазла: берём среднюю позицию
        lo_t, hi_t = puzzle_range(target)
        predicted = int(lo_t + avg * (hi_t - lo_t))
        print(f"\n  Предсказание для #{target} (по средней позиции {avg:.4f}):")
        print(f"  k ~= {hex(predicted)}")
        print(f"  Это 'слабое' предсказание — годится для приоритетного поиска")

    return positions


# ===========================================================================
# Анализ 2: Python random.Random(seed)
# ===========================================================================

def test_python_random(max_seed: int = 1_000_000, verbose: bool = True,
                       target: int = 71):
    """
    Проверяем: если random.Random(seed).randint(2^(n-1), 2^n-1) для n=1,2,...
    совпадает с известными ключами, мы нашли сид и можем предсказать target.
    """
    print("\n" + "="*60)
    print(f"ТЕСТ: Python random.Random(seed)  [seed 0..{max_seed:,}]")
    print("="*60)

    # Используем первые N известных ключей как "фингерпринт"
    test_keys = {n: k for n, k in sorted(KNOWN_KEYS.items())[:8]}
    if len(test_keys) < 3:
        print("  Недостаточно известных ключей для теста")
        return None

    first_n = min(test_keys.keys())
    first_k = test_keys[first_n]
    lo_first, hi_first = puzzle_range(first_n)

    matches = []
    for seed in range(max_seed):
        rng = random.Random(seed)

        # Пропускаем пазлы до первого известного
        for skip_n in range(1, first_n):
            lo, hi = puzzle_range(skip_n)
            rng.randint(lo, hi)

        # Проверяем совпадение с первым ключом
        candidate = rng.randint(lo_first, hi_first)
        if candidate != first_k:
            continue

        # Совпало! Проверяем остальные
        match_count = 1
        for n in sorted(test_keys.keys()):
            if n == first_n:
                continue
            lo, hi = puzzle_range(n)
            # Нужно продолжить RNG state, но мы его сбросили...
            # Пересоздаём с правильной позицией
        # Полная проверка:
        rng2 = random.Random(seed)
        all_match = True
        for n in sorted(test_keys.keys()):
            lo, hi = puzzle_range(n)
            c = rng2.randint(lo, hi)
            if c != test_keys[n]:
                all_match = False
                break

        if all_match:
            print(f"\n  *** SEED FOUND: {seed} ***")
            # Предсказываем целевой пазл
            rng3 = random.Random(seed)
            for n in range(1, target + 1):
                lo, hi = puzzle_range(n)
                k = rng3.randint(lo, hi)
                if n == target:
                    print(f"  Предсказанный ключ #{target}: {hex(k)}")
                    return seed, k
            matches.append(seed)

        if verbose and seed % 100_000 == 0:
            print(f"\r  Проверено: {seed:,}/{max_seed:,} сидов...", end='', flush=True)

    print(f"\n  Совпадений не найдено в [0, {max_seed:,}]")
    return None


# ===========================================================================
# Анализ 3: Hash-based генераторы
# ===========================================================================

def test_hash_generators(target: int = 71):
    """Проверяем: ключи = hash(seed_string + puzzle_number) % range."""
    print("\n" + "="*60)
    print("ТЕСТ: Hash-based генераторы")
    print("="*60)

    test_keys = {n: k for n, k in sorted(KNOWN_KEYS.items()) if n <= 10}
    if len(test_keys) < 3:
        print("  Недостаточно известных ключей")
        return None

    # Различные схемы генерации
    schemes = [
        # (name, lambda n: bytes_to_hash)
        ("SHA256(n)",         lambda n: f"{n}".encode()),
        ("SHA256('puzzle'+n)",lambda n: f"puzzle{n}".encode()),
        ("SHA256('Bitcoin Puzzle #'+n)", lambda n: f"Bitcoin Puzzle #{n}".encode()),
        ("SHA256(sha256(n))", lambda n: hashlib.sha256(f"{n}".encode()).digest()),
        ("MD5(n)",            lambda n: f"{n}".encode()),
        ("SHA256('puzzle'+n+'secret')", lambda n: f"puzzle{n}secret".encode()),
    ]

    for name, seed_fn in schemes:
        print(f"\n  Схема: {name}")
        all_match = True
        for n, expected_k in list(test_keys.items())[:5]:
            lo, hi = puzzle_range(n)
            rng_range = hi - lo + 1

            seed_bytes = seed_fn(n)
            if 'MD5' in name:
                h = int(hashlib.md5(seed_bytes).hexdigest(), 16)
            else:
                h = int(hashlib.sha256(seed_bytes).hexdigest(), 16)

            k = lo + (h % rng_range)
            if k != expected_k:
                all_match = False
                break

        if all_match:
            print(f"  *** СХЕМА СОВПАЛА! ***")
            lo_t, hi_t = puzzle_range(target)
            seed_bytes = seed_fn(target)
            if 'MD5' in name:
                h = int(hashlib.md5(seed_bytes).hexdigest(), 16)
            else:
                h = int(hashlib.sha256(seed_bytes).hexdigest(), 16)
            k_t = lo_t + (h % (hi_t - lo_t + 1))
            print(f"  Ключ #{target} = {hex(k_t)}")
            return k_t
        else:
            print(f"    Нет совпадения")

    return None


# ===========================================================================
# Анализ 4: Статистика битов
# ===========================================================================

def analyze_bit_patterns():
    """Анализ распределения битов после ведущей единицы."""
    print("\n" + "="*60)
    print("АНАЛИЗ БИТОВЫХ ПАТТЕРНОВ")
    print("="*60)

    bit_freq = {}   # позиция бита → частота 1
    n_keys = 0

    for n, k in sorted(KNOWN_KEYS.items()):
        if n < 5:
            continue  # слишком маленький диапазон, нет паттерна
        bits = bin(k)[2:]  # без '0b'
        # Нормализуем: берём биты после ведущей единицы
        payload = bits[1:]  # убираем ведущий 1
        for i, b in enumerate(payload):
            bit_freq[i] = bit_freq.get(i, 0) + int(b)
        n_keys += 1

    if n_keys == 0:
        print("  Недостаточно ключей")
        return

    print(f"  Анализ {n_keys} ключей")
    print(f"\n  Позиция бита  |  Частота '1'  |  Отклонение от 0.5")
    print(f"  " + "-"*50)

    biased_positions = []
    for pos in range(min(20, len(bit_freq))):
        freq = bit_freq.get(pos, 0)
        rate = freq / n_keys if n_keys > 0 else 0
        deviation = abs(rate - 0.5)
        bar = '#' * int(rate * 20)
        print(f"  Bit {pos:>2}:  {freq:>3}/{n_keys}  ({rate:.3f})  "
              f"{'BIASED!' if deviation > 0.3 else '       '} {bar}")
        if deviation > 0.3:
            biased_positions.append((pos, rate))

    if biased_positions:
        print(f"\n  *** НАЙДЕНЫ СМЕЩЁННЫЕ БИТЫ: {biased_positions}")
        print(f"  Это СИЛЬНО сужает пространство поиска!")
    else:
        print(f"\n  Биты выглядят случайными (нет явного смещения)")


# ===========================================================================
# Анализ 5: Предсказание через линейную позицию
# ===========================================================================

def predict_key(target: int = 71):
    """
    Предсказываем ключ целевого пазла методом регрессии позиций.
    Если позиции имеют тренд, extrapolation даёт приоритетную зону поиска.
    """
    print("\n" + "="*60)
    print(f"ПРЕДСКАЗАНИЕ КЛЮЧА #{target} (статистический метод)")
    print("="*60)

    positions = [(n, puzzle_position(n, k))
                 for n, k in sorted(KNOWN_KEYS.items()) if n >= 5]

    if len(positions) < 3:
        print("  Недостаточно ключей")
        return

    ns   = [p[0] for p in positions]
    vals = [p[1] for p in positions]

    mean_pos = sum(vals) / len(vals)
    std_pos  = (sum((v - mean_pos)**2 for v in vals) / len(vals)) ** 0.5

    print(f"  Среднее:  {mean_pos:.4f}")
    print(f"  СКО:      {std_pos:.4f}")
    print(f"  Мин:      {min(vals):.4f}")
    print(f"  Макс:     {max(vals):.4f}")

    lo_t, hi_t = puzzle_range(target)
    range_size = hi_t - lo_t

    # Центральная зона (± 1 std от среднего)
    center_lo = lo_t + max(0, mean_pos - std_pos) * range_size
    center_hi = lo_t + min(1, mean_pos + std_pos) * range_size

    print(f"\n  Приоритетная зона поиска (±1std от среднего {mean_pos:.3f}):")
    print(f"  [{hex(int(center_lo))}, {hex(int(center_hi))}]")
    print(f"  Размер зоны: 2^{(int(center_hi)-int(center_lo)).bit_length()-1} ключей")
    print(f"  Вероятность попасть в эту зону: ~68% (если позиция нормально распределена)")

    # Дополнительно: квартили
    vals_sorted = sorted(vals)
    q1 = vals_sorted[len(vals_sorted)//4]
    q3 = vals_sorted[3*len(vals_sorted)//4]
    lo_q = lo_t + q1 * range_size
    hi_q = lo_t + q3 * range_size
    print(f"\n  Межквартильный диапазон (Q1-Q3, вероятность 50%):")
    print(f"  [{hex(int(lo_q))}, {hex(int(hi_q))}]")

    return int(center_lo), int(center_hi)


# ===========================================================================
# Анализ 6: Генерация приоритетных сегментов для GPU
# ===========================================================================

def generate_priority_segments(n_segments: int = 20, target: int = 71) -> list:
    """
    Генерирует список приоритетных стартовых точек для GPU brute force.
    Основан на статистике позиций известных ключей.

    Возвращает список k_start значений, отсортированных по приоритету.
    """
    positions = [(n, puzzle_position(n, k))
                 for n, k in sorted(KNOWN_KEYS.items()) if n >= 5]

    if len(positions) < 3:
        # Если не знаем паттерна — равномерное покрытие
        lo, hi = puzzle_range(target)
        step = (hi - lo) // n_segments
        return [lo + i * step for i in range(n_segments)]

    vals = [p[1] for p in positions]
    mean_pos = sum(vals) / len(vals)
    std_pos  = (sum((v - mean_pos)**2 for v in vals) / len(vals)) ** 0.5

    lo_t, hi_t = puzzle_range(target)
    range_size = hi_t - lo_t

    # Генерируем позиции вокруг среднего, по возрастанию расстояния
    priorities = []
    for i in range(n_segments):
        # Спираль вокруг среднего
        offset = (i // 2 + 1) * std_pos / (n_segments // 4)
        sign   = 1 if i % 2 == 0 else -1
        pos    = mean_pos + sign * offset
        pos    = max(0.001, min(0.999, pos))
        k      = int(lo_t + pos * range_size)
        priorities.append(k)

    return sorted(set(priorities))


# ===========================================================================
# CLI
# ===========================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='Bitcoin Puzzle RNG Pattern Analysis')
    parser.add_argument('--quick',   action='store_true',
                        help='Только быстрые тесты (без перебора сидов)')
    parser.add_argument('--predict', action='store_true',
                        help='Только предсказание ключа целевого пазла')
    parser.add_argument('--seeds',   type=int, default=200_000,
                        help='Количество сидов для проверки random.Random (default: 200000)')
    parser.add_argument('--segments', action='store_true',
                        help='Вывести приоритетные сегменты для GPU')
    parser.add_argument('--target',  type=int, default=71,
                        help='Какой пазл предсказывать/анализировать (default: 71). '
                             'Run analysis/puzzle_status.py --unsolved для списка кандидатов.')
    args = parser.parse_args()
    target = args.target

    print("\n" + "="*60)
    print("  BITCOIN PUZZLE RNG ANALYSIS")
    print(f"  Известных ключей: {len(KNOWN_KEYS)}  |  Цель: #{target}")
    print("="*60)

    # Обновляем таблицу из онлайн-источника (если доступен)
    _try_fetch_keys()

    if args.predict:
        predict_key(target)
        return

    if args.segments:
        segs = generate_priority_segments(20, target=target)
        print("\nПриоритетные старты для GPU brute force:")
        for i, k in enumerate(segs, 1):
            print(f"  {i:>2}. {hex(k)}")
        return

    # Полный анализ
    analyze_positions(target)
    analyze_bit_patterns()

    if not args.quick:
        result = test_python_random(max_seed=args.seeds, target=target)
        if result:
            seed, k_t = result
            print(f"\n{'!'*60}")
            print(f"  НАЙДЕН СИД: {seed}")
            print(f"  Ключ #{target}:   {hex(k_t)}")
            print(f"{'!'*60}")
            return

    test_hash_generators(target)
    predict_key(target)


def _try_fetch_keys():
    """Попытка обновить известные ключи из онлайн-источника."""
    try:
        import urllib.request, json
        # privatekeys.pw/puzzles/bitcoin-puzzle-tx — не имеет публичного API,
        # но можно добавить свой источник данных
        pass
    except Exception:
        pass


if __name__ == '__main__':
    main()
