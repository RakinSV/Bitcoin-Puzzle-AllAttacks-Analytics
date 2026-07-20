"""
Distributed Kangaroo — WORKER CLIENT.

Pulls the interval/pubkey/dp_bits from a DP-pool server, runs a local GPU
Kangaroo herd with EXACTLY that dp_bits (so its distinguished points line up with
every other worker's), and streams its DPs to the pool. Stops as soon as any
worker's DPs collide into the key. All workers share tame_base (= k_start) and Q
(= pubkey), so the pool reconstructs across workers transparently.

Run:  python -m kangaroo.dp_client --server http://HOST:8899 --worker gpu-1
"""
import sys, os, time, argparse, urllib.request, json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def _get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def _post(url, obj):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def run_worker(server, worker='gpu', status_every=10, max_calls=0,
               verbose=True, stop_flag=None):
    """Run one worker against `server`. Returns the key hex if solved here or by
    a peer, else None. stop_flag: optional callable -> bool to abort early."""
    from kangaroo.kangaroo_engine import KangarooEngine

    cfg = _get(server.rstrip('/') + '/config')
    k_start, k_end = int(cfg['k_start']), int(cfg['k_end'])
    pubkey = (int(cfg['pubkey'][0]), int(cfg['pubkey'][1]))
    dp_bits = int(cfg['dp_bits'])

    eng = KangarooEngine(pubkey, k_start, k_end, use_mb=True)
    # Force the pool's dp_bits so every worker samples the SAME distinguished set.
    eng.dp_bits = dp_bits
    eng.dp_mask = (1 << dp_bits) - 1
    if eng._use_mb:
        eng._mb_steps = max(1, min(2048, int(eng._dp_capacity * (1 << dp_bits)
                                             / max(1, eng.n_total) / 4)))
    eng.initialize()

    if verbose:
        print(f"[worker {worker}] interval [2^{k_start.bit_length()-1}], "
              f"dp_bits={dp_bits}, herd={eng.n_total}", flush=True)

    submit_url = server.rstrip('/') + '/submit'
    status_url = server.rstrip('/') + '/status'
    calls = 0
    t0 = time.time()
    while True:
        if stop_flag is not None and stop_flag():
            return None
        dps = eng.step()
        calls += 1
        if dps:
            batch = [[str(d['x']), d['dist'], d['kind']] for d in dps]
            resp = _post(submit_url, {'worker': worker, 'dps': batch})
            if resp.get('solved'):
                if verbose:
                    print(f"[worker {worker}] SOLVED key={resp['key']} "
                          f"({time.time()-t0:.1f}s, {calls} calls)", flush=True)
                return resp['key']
        if calls % status_every == 0:
            st = _get(status_url)
            if st.get('solved'):
                if verbose:
                    print(f"[worker {worker}] peer solved key={st['key']}",
                          flush=True)
                return st['key']
            if verbose:
                print(f"\r[worker {worker}] calls={calls} pool_dps={st['dps']:,} "
                      f"workers={st['workers']} {time.time()-t0:.0f}s ",
                      end='', flush=True)
        if max_calls and calls >= max_calls:
            return None


def _main():
    ap = argparse.ArgumentParser(description="Kangaroo DP-pool worker")
    ap.add_argument('--server', required=True, help="http://HOST:PORT of the pool")
    ap.add_argument('--worker', default=f"gpu-{os.getpid()}")
    ap.add_argument('--max-calls', type=int, default=0)
    args = ap.parse_args()
    key = run_worker(args.server, args.worker, max_calls=args.max_calls)
    print(f"\n[worker] {'done key=' + key if key else 'stopped (not solved)'}")


if __name__ == '__main__':
    _main()
