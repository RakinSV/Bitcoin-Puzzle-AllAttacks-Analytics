"""
GPU тесты — проверка OpenCL ядра на малых пазлах.
  python tests/test_gpu.py

Тест 1: Верификация точек после инициализации (k*G правильно вычислен)
Тест 2: Поиск k=1 в диапазоне [1,100] (пазл #1)
Тест 3: Поиск произвольного ключа в малом диапазоне
"""

import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pyopencl as cl

from ecc.curve        import scalar_mul, G, N
from utils.address    import (point_to_address, get_target_for_kernel,
                               verify_key_address, point_to_hash160_compressed)
from kangaroo.gpu_search import GPUSearchEngine, _int_to_u256, _u256_to_int, _scalar_mul


# ==============================================================
# Тест 1: OpenCL устройства
# ==============================================================

def test_opencl_available():
    platforms = cl.get_platforms()
    devices   = [d for p in platforms for d in p.get_devices(cl.device_type.GPU)]
    assert len(devices) > 0, "No OpenCL GPU devices found!"
    for d in devices:
        print(f"  Device: {d.name}  CUs={d.max_compute_units}  "
              f"VRAM={d.global_mem_size//1024//1024}MB")
    print(f"[OK] {len(devices)} OpenCL GPU device(s) found")


# ==============================================================
# Тест 2: Корректность инициализации точек
# ==============================================================

def test_init_points():
    """После multiplyStepKernel GPU должен содержать верные k*G точки."""
    from kangaroo.gpu_search import _INF_U256

    # Маленький движок: 32 threads × 1 block × 1 point/thread = 32 total
    engine = GPUSearchEngine(threads=32, blocks=1, points_per_thread=1)
    engine.set_target(get_target_for_kernel('1BgGZ9tcN4rm9KBzDn7KprQz87SZ26SAMH'))

    k_start = 1
    engine.initialize(k_start)

    # Читаем x, y буферы обратно
    N_pts = engine.total_points   # = 32
    x_host = np.zeros(N_pts * 8, dtype=np.uint32)
    y_host = np.zeros(N_pts * 8, dtype=np.uint32)
    cl.enqueue_copy(engine.queue, x_host, engine.x_buf)
    cl.enqueue_copy(engine.queue, y_host, engine.y_buf)
    engine.queue.finish()

    errors = 0
    for i in range(min(N_pts, 10)):    # проверяем первые 10 точек
        x_gpu = _u256_to_int(x_host[i*8:(i+1)*8])
        y_gpu = _u256_to_int(y_host[i*8:(i+1)*8])
        pt_gpu = (x_gpu, y_gpu)

        pt_cpu = _scalar_mul(k_start + i, (_GX, _GY))

        if pt_gpu != pt_cpu:
            print(f"  [FAIL] Point {i}: GPU={hex(x_gpu)[:16]}... CPU={hex(pt_cpu[0])[:16]}...")
            errors += 1
        else:
            print(f"  [OK] Point {i}: k={k_start+i}  x={hex(x_gpu)[:20]}...")

    assert errors == 0, f"{errors} point(s) incorrectly initialized!"
    print(f"[OK] Initialization correct (checked {min(N_pts,10)} points)")


# ==============================================================
# Тест 3: Найти k=1 в диапазоне [1,1000]
# ==============================================================

def test_find_puzzle1():
    """GPU должен найти k=1 для адреса puzzle #1."""
    from utils.address import decode_address_hash160

    TARGET_ADDR = '1BgGZ9tcN4rm9KBzDn7KprQz87SZ26SAMH'
    K_START     = 1
    K_END       = 1000

    engine = GPUSearchEngine(threads=32, blocks=4, points_per_thread=8)
    # total = 32*4*8 = 1024 → покрывает [1, 1025)

    engine.set_target(get_target_for_kernel(TARGET_ADDR))
    engine.initialize(K_START)

    print(f"  Searching k in [{K_START}, {K_END}]  total_pts={engine.total_points}")

    found = None
    for step_i in range(5):   # макс 5 шагов
        results = engine.step()
        if results:
            found = results[0]
            break

    assert found is not None, "GPU did not find k=1!"
    assert found['k'] == 1, f"Wrong key: expected 1, got {found['k']}"

    # Верифицируем через CPU
    assert verify_key_address(found['k'], TARGET_ADDR), "Key doesn't match address!"

    print(f"[OK] Found k={found['k']} = {hex(found['k'])}  compressed={found['compressed']}")


# ==============================================================
# Тест 4: Найти произвольный ключ
# ==============================================================

def test_find_random_key():
    """GPU находит заданный ключ в маленьком диапазоне."""
    # Создаём тестовый пазл: берём k=777, вычисляем адрес
    K_KNOWN   = 777
    K_START   = 512
    K_END     = 1023

    pt_known  = scalar_mul(K_KNOWN, G)
    addr_test = point_to_address(pt_known[0], pt_known[1])
    print(f"  Test key: k={K_KNOWN}  addr={addr_test}")

    # Нам нужны threads*blocks*points >= (K_END - K_START + 1) = 512
    # 32*2*8 = 512 → ровно покрывает за 1 шаг
    engine = GPUSearchEngine(threads=32, blocks=2, points_per_thread=8)
    assert engine.total_points >= K_END - K_START + 1, "total_points too small"

    engine.set_target(get_target_for_kernel(addr_test))
    engine.initialize(K_START)

    found = None
    for _ in range(3):
        results = engine.step()
        if results:
            found = results[0]
            break

    assert found is not None, f"GPU did not find k={K_KNOWN}!"
    assert found['k'] == K_KNOWN, f"Wrong key: expected {K_KNOWN}, got {found['k']}"
    assert verify_key_address(found['k'], addr_test), "Verification failed!"
    print(f"[OK] Found k={found['k']} for addr {addr_test}")


# ==============================================================
# Запуск
# ==============================================================

from ecc.curve import GX as _GX, GY as _GY

ALL_TESTS = [
    ('OpenCL devices',     test_opencl_available),
    ('Init points',        test_init_points),
    ('Find puzzle #1',     test_find_puzzle1),
    ('Find random key',    test_find_random_key),
]

if __name__ == '__main__':
    print("=" * 55)
    print("GPU OpenCL Tests")
    print("=" * 55)

    failed = []
    for name, fn in ALL_TESTS:
        print(f"\n--- {name} ---")
        try:
            fn()
        except Exception as e:
            import traceback
            print(f"[FAIL] FAILED: {e}")
            traceback.print_exc()
            failed.append(name)

    print("\n" + "=" * 55)
    if not failed:
        print(f"ALL {len(ALL_TESTS)} GPU TESTS PASSED [OK]")
    else:
        print(f"FAILED ({len(failed)}): {failed}")
    sys.exit(len(failed))
