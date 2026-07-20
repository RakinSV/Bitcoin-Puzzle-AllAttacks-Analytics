"""
Distributed Kangaroo — Distinguished-Point POOL SERVER.

Many workers run their own GPU Kangaroo herds on the SAME interval, jump table
and DP filter, and stream their distinguished points here. The server keeps ONE
global DP table across all workers and reconstructs the key on the first
cross-worker collision (see kangaroo/reconstruct.py). Because every worker shares
tame_base (= k_start) and Q (= pubkey), a tame DP from worker A and a wild DP
from worker B reconstruct exactly as if a single engine had produced both — so N
workers give ~N x the effective herd and an ~N x wall-clock speed-up. This is the
only route that scales past what one GPU can do (a 71-bit key needs far more hops
than any single machine can walk).

Protocol (JSON over HTTP, no external deps):
    GET  /config  -> {k_start, k_end, pubkey:[x,y], dp_bits}   (workers self-configure)
    POST /submit  <- {worker, dps:[[x,dist,kind],...]}  -> {solved, key}
    GET  /status  -> {solved, key, dps, submissions, workers, elapsed}

Run:  python -m kangaroo.dp_server --puzzle 71 --pubkey 02... --dp-bits 20 --port 8899
"""
import sys, os, json, time, threading, argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from kangaroo.reconstruct import recover


class DPPool:
    """Thread-safe global distinguished-point table + reconstruction."""

    def __init__(self, k_start, k_end, pubkey, dp_bits):
        self.k_start = k_start
        self.k_end   = k_end
        self.pubkey  = (int(pubkey[0]), int(pubkey[1]))
        self.dp_bits = dp_bits
        self._table  = {}                     # x -> (dist, kind)
        self._lock   = threading.Lock()
        self.solved  = False
        self.key     = None
        self.submissions = 0
        self.workers = set()
        self.t0      = time.time()

    def add_batch(self, worker, dps):
        """dps: iterable of (x, dist, kind). Returns (solved, key)."""
        with self._lock:
            self.workers.add(worker)
            self.submissions += len(dps)
            if self.solved:
                return True, self.key
            for x, dist, kind in dps:
                prev = self._table.get(x)
                if prev is None:
                    self._table[x] = (dist, kind)
                    continue
                pd, pk = prev
                k = recover(dist, kind, pd, pk,
                            self.k_start, self.k_end, self.pubkey)
                if k is not None:
                    self.solved = True
                    self.key = k
                    return True, k
            return False, None

    def config(self):
        return {'k_start': str(self.k_start), 'k_end': str(self.k_end),
                'pubkey': [str(self.pubkey[0]), str(self.pubkey[1])],
                'dp_bits': self.dp_bits}

    def status(self):
        with self._lock:
            return {'solved': self.solved,
                    'key': hex(self.key) if self.key is not None else None,
                    'dps': len(self._table), 'submissions': self.submissions,
                    'workers': len(self.workers),
                    'elapsed': round(time.time() - self.t0, 1)}


def make_handler(pool: DPPool):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):            # silence per-request logging
            pass

        def _send(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/config':
                self._send(pool.config())
            elif self.path == '/status':
                self._send(pool.status())
            else:
                self._send({'error': 'not found'}, 404)

        def do_POST(self):
            if self.path != '/submit':
                self._send({'error': 'not found'}, 404)
                return
            n = int(self.headers.get('Content-Length', 0))
            try:
                req = json.loads(self.rfile.read(n) or b'{}')
            except json.JSONDecodeError:
                self._send({'error': 'bad json'}, 400)
                return
            worker = req.get('worker', 'anon')
            # dps arrive as [x_hex_or_int, dist, kind]; x may be huge -> string.
            dps = [(int(x), int(d), int(k)) for x, d, k in req.get('dps', [])]
            solved, key = pool.add_batch(worker, dps)
            self._send({'solved': solved,
                        'key': hex(key) if key is not None else None})
    return Handler


def serve(pool: DPPool, port: int, host: str = ''):
    httpd = ThreadingHTTPServer((host, port), make_handler(pool))
    return httpd


def _main():
    ap = argparse.ArgumentParser(description="Kangaroo DP-pool server")
    ap.add_argument('--puzzle', type=int, required=True,
                    help="puzzle number (sets the interval [2^(n-1), 2^n-1])")
    ap.add_argument('--pubkey', required=True,
                    help="target pubkey: compressed hex (02/03..) or 'x,y'")
    ap.add_argument('--dp-bits', type=int, required=True,
                    help="MUST match the workers' dp_bits")
    ap.add_argument('--port', type=int, default=8899)
    args = ap.parse_args()

    from kangaroo.reconstruct import decompress_pubkey
    if ',' in args.pubkey:
        px, py = (int(v, 0) for v in args.pubkey.split(','))
    else:
        px, py = decompress_pubkey(args.pubkey)

    k_start, k_end = 2 ** (args.puzzle - 1), 2 ** args.puzzle - 1
    pool = DPPool(k_start, k_end, (px, py), args.dp_bits)
    httpd = serve(pool, args.port)
    print(f"[DP-pool] puzzle #{args.puzzle}  dp_bits={args.dp_bits}  "
          f"port={args.port}  interval=[2^{args.puzzle-1}, 2^{args.puzzle}-1]")
    print(f"[DP-pool] workers point --server http://<host>:{args.port}")
    try:
        while not pool.solved:
            httpd.handle_request()
    finally:
        st = pool.status()
        print(f"[DP-pool] {'SOLVED key=' + st['key'] if st['solved'] else 'stopped'} "
              f"({st['dps']:,} DPs, {st['workers']} workers, {st['elapsed']}s)")


if __name__ == '__main__':
    _main()
