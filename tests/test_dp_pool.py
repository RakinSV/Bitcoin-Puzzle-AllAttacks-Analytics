#!/usr/bin/env python3
"""
Distributed Kangaroo DP-pool tests.

1. Synthetic: a tame DP and a wild DP from *different* workers, sharing an x,
   reconstruct to the real key in the pool (proves cross-worker reconstruction).
2. End-to-end: a live server + one real GPU worker solves a small puzzle.
3. Concurrency: two GPU workers stream into one pool and it solves (proves the
   effective herd is the union of all workers).
"""
import os, sys, time, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ecc.curve import scalar_mul, G
from analysis.rng_analysis import KNOWN_KEYS
from kangaroo.dp_server import DPPool, serve
from kangaroo.dp_client import run_worker


def test_synthetic_cross_worker():
    bits = 38
    k = KNOWN_KEYS[bits]; pub = scalar_mul(k, G)
    ks, ke = 2 ** (bits - 1), 2 ** bits - 1
    pool = DPPool(ks, ke, pub, dp_bits=4)
    # tame log = ks + dist_t ; wild log = k + dist_w. Same x (=same/negated log)
    # when ks + dist_t == k + dist_w. Pick dist_t=k, dist_w=ks  -> both >= 0.
    # x itself is arbitrary (reconstruction uses only dist+kind); use 0xABC.
    solved, key = pool.add_batch('A', [(0xABC, k, 0)])      # tame from worker A
    assert not solved, "one DP alone must not solve"
    solved, key = pool.add_batch('B', [(0xABC, ks, 1)])     # wild from worker B
    assert solved and key == k, f"cross-worker reconstruct failed: {key} vs {k}"
    assert len(pool.workers) == 2
    print("  [OK] synthetic cross-worker reconstruction")


def _serve_bg(pool):
    httpd = serve(pool, 0)                      # port 0 -> auto-assign
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    return httpd, f"http://127.0.0.1:{port}"


def test_e2e_single_worker():
    bits = 38
    k = KNOWN_KEYS[bits]; pub = scalar_mul(k, G)
    ks, ke = 2 ** (bits - 1), 2 ** bits - 1
    pool = DPPool(ks, ke, pub, dp_bits=6)
    httpd, url = _serve_bg(pool)
    try:
        key = run_worker(url, 'gpu-1', status_every=20, max_calls=8000,
                         verbose=False)
    finally:
        httpd.shutdown()
    assert key is not None and int(key, 16) == k, f"e2e single worker: {key}"
    print(f"  [OK] e2e single worker solved #{bits} ({pool.status()['elapsed']}s, "
          f"{pool.status()['dps']:,} pool DPs)")


def test_e2e_two_workers():
    bits = 40
    k = KNOWN_KEYS[bits]; pub = scalar_mul(k, G)
    ks, ke = 2 ** (bits - 1), 2 ** bits - 1
    pool = DPPool(ks, ke, pub, dp_bits=7)
    httpd, url = _serve_bg(pool)
    results = {}
    solved_evt = threading.Event()

    def work(name):
        results[name] = run_worker(url, name, status_every=10, max_calls=12000,
                                   verbose=False,
                                   stop_flag=solved_evt.is_set)
        solved_evt.set()

    threads = [threading.Thread(target=work, args=(f'gpu-{i}',)) for i in range(2)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=180)
    finally:
        time.sleep(0.2)
        httpd.shutdown()
    st = pool.status()
    assert st['solved'] and int(st['key'], 16) == k, f"two-worker pool: {st}"
    assert st['workers'] == 2, f"expected 2 workers, got {st['workers']}"
    print(f"  [OK] two workers solved #{bits} via shared pool "
          f"({st['elapsed']}s, {st['dps']:,} DPs, {st['submissions']:,} submits)")


if __name__ == '__main__':
    print("=" * 62)
    print("  DISTRIBUTED KANGAROO DP-POOL TESTS")
    print("=" * 62, flush=True)
    test_synthetic_cross_worker()
    test_e2e_single_worker()
    test_e2e_two_workers()
    print("=" * 62)
    print("  ALL DP-POOL TESTS PASSED [OK]")
    print("=" * 62)
