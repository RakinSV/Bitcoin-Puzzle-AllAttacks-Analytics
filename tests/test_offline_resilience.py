#!/usr/bin/env python3
"""
The lottery must survive losing the network -- and still capture a find.

A search that runs for weeks WILL see the connection drop. The failure that
matters is not "it stops": it is a search that keeps burning electricity while
silently unable to record the one result it exists to produce, or one that dies
at 3am because a status fetch raised.

Three properties are pinned here:

  1. Losing the network never kills the search. Only ONE network call exists in
     the whole lottery -- the pool frontier at startup -- and it must degrade to
     the offline snapshot rather than raise.
  2. The offline fallback is CONSERVATIVE. A stale snapshot must claim LESS
     coverage than reality, never more: over-claiming would skip keys nobody has
     checked, which is the one way to miss the answer entirely.
  3. A key found while offline still reaches the disk. (The save path is proven
     network-free in test_no_key_exfiltration; this checks it under an actual
     simulated outage.)

Run:  python tests/test_offline_resilience.py
"""
import os
import shutil
import socket
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.rng_analysis import KNOWN_KEYS
from ecc.curve import scalar_mul, G
from utils.address import point_to_address

FAILS = []


def check(name, cond, detail=""):
    print("  [%s] %s%s" % ("OK" if cond else "FAIL", name,
                           ("  -- " + detail) if detail else ""))
    if not cond:
        FAILS.append(name)


class Offline:
    """Context manager that makes every outbound connection fail, as a dead
    link does -- not by raising something exotic, but with the same OSError a
    real outage produces."""

    def __enter__(self):
        import urllib.request
        self._sock = socket.socket
        self._create = socket.create_connection
        self._getaddr = socket.getaddrinfo
        self._urlopen = urllib.request.urlopen

        def dead(*a, **kw):
            raise OSError("network is unreachable")

        socket.socket = dead
        socket.create_connection = dead
        socket.getaddrinfo = dead
        urllib.request.urlopen = dead
        return self

    def __exit__(self, *exc):
        import urllib.request
        socket.socket = self._sock
        socket.create_connection = self._create
        socket.getaddrinfo = self._getaddr
        urllib.request.urlopen = self._urlopen
        return False


def test_pool_lookup_degrades_instead_of_raising():
    """With the link down, the startup frontier lookup must return a usable
    value from the snapshot rather than taking the process down with it."""
    from main import PUZZLES, _get_pool_end
    pz = PUZZLES[71]

    online = _get_pool_end(71, pz)
    with Offline():
        try:
            offline = _get_pool_end(71, pz)
            raised = None
        except Exception as e:
            offline, raised = None, "%s: %s" % (type(e).__name__, e)

    check("frontier lookup does not raise while offline", raised is None,
          raised or "returned normally")
    check("offline lookup still yields a usable frontier",
          bool(offline) and pz['start'] <= offline <= pz['end'],
          hex(offline) if offline else "none")
    check("offline value never claims MORE than the live one",
          offline is not None and offline <= online,
          "offline %s vs live %s" % (hex(offline) if offline else '-', hex(online)))
    if offline is not None and offline < online:
        gap = online - offline
        print("            (snapshot is %s keys behind live -- costs redundant"
              % f"{gap:,}")
        print("             work, never skips unsearched keys)")


def test_a_find_is_saved_while_offline():
    """The whole point: an outage must not cost us the prize."""
    import main

    k = KNOWN_KEYS[45]
    addr = point_to_address(*scalar_mul(k, G))

    workdir = tempfile.mkdtemp(prefix="offline-")
    cwd, home = os.getcwd(), os.environ.get("USERPROFILE")
    err = None
    try:
        os.chdir(workdir)
        os.environ["USERPROFILE"] = workdir
        os.makedirs(os.path.join(workdir, "Desktop"), exist_ok=True)
        with Offline():
            try:
                main._save_found_key(k, addr)
            except Exception as e:
                err = "%s: %s" % (type(e).__name__, e)
        files = [f for f in os.listdir(workdir) if "FOUND" in f.upper()]
        blob = ""
        for f in files:
            p = os.path.join(workdir, f)
            if os.path.isfile(p):
                with open(p, encoding="utf-8", errors="replace") as fh:
                    blob += fh.read()
    finally:
        os.chdir(cwd)
        if home is not None:
            os.environ["USERPROFILE"] = home
        shutil.rmtree(workdir, ignore_errors=True)

    check("saving a key while offline does not raise", err is None, err or "clean")
    check("the key still reached disk during the outage", bool(files),
          "%d file(s)" % len(files))
    check("the saved text contains the key", hex(k) in blob)
    check("the saved text contains the WIF", main._key_to_wif(k) in blob)


def test_search_loop_holds_no_network_calls():
    """The loop that runs for weeks must not touch the network at all."""
    import inspect
    import main

    src = inspect.getsource(main._pure_random_search)
    banned = ("urlopen", "requests.", "socket.", "http.client")
    hits = [b for b in banned if b in src]
    check("search loop contains no network primitives", not hits,
          ", ".join(hits) if hits else "the only lookup is at startup, outside "
                                       "the loop")


if __name__ == "__main__":
    print("=" * 70)
    print("  OFFLINE RESILIENCE")
    print("=" * 70)
    print("\n--- the startup frontier lookup degrades gracefully ---")
    test_pool_lookup_degrades_instead_of_raising()
    print("\n--- a find during an outage still reaches disk ---")
    test_a_find_is_saved_while_offline()
    print("\n--- the long-running loop is network-free ---")
    test_search_loop_holds_no_network_calls()
    print("\n" + "=" * 70)
    if FAILS:
        print("  %d FAILED: %s" % (len(FAILS), FAILS))
        sys.exit(1)
    print("  THE SEARCH SURVIVES AN OUTAGE AND KEEPS ITS FIND [OK]")
    print("=" * 70)
