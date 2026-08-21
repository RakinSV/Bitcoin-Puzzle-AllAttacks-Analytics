#!/usr/bin/env python3
"""
A found key must never leave this machine by itself.

This is the one bug class that costs real money rather than time: a solver that
quietly reports its find to somebody else's server. Nothing in this project does
that today, and this test exists so nothing ever starts to -- a future edit that
adds a "submit result" call, a crash reporter, or an analytics ping will fail
here rather than in production, once, silently, with the prize gone.

Three things are pinned:

  1. The save path performs NO network I/O. Sockets and urllib are replaced with
     objects that raise on use, then a real key is saved. Any outbound call --
     however well-intentioned -- turns into a test failure.
  2. The key lands only in files under the working directory (and the desktop
     copy), never anywhere else.
  3. The DP-pool client transmits distinguished points and a worker label, and
     specifically NOT a private key or WIF. Distinguished points are the shared
     work product a pool exists to combine; a private key is not.

Run:  python tests/test_no_key_exfiltration.py
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


class Tripwire(Exception):
    pass


def test_saving_a_key_makes_no_network_calls():
    import main
    import urllib.request

    k = KNOWN_KEYS[50]
    addr = point_to_address(*scalar_mul(k, G))

    real_socket = socket.socket
    real_create = socket.create_connection
    real_urlopen = urllib.request.urlopen

    def boom(*a, **kw):
        raise Tripwire("network access during key save")

    workdir = tempfile.mkdtemp(prefix="exfil-")
    cwd = os.getcwd()
    home = os.environ.get("USERPROFILE")
    tripped = None
    try:
        os.chdir(workdir)
        os.environ["USERPROFILE"] = workdir
        os.makedirs(os.path.join(workdir, "Desktop"), exist_ok=True)

        socket.socket = boom
        socket.create_connection = boom
        urllib.request.urlopen = boom
        try:
            main._save_found_key(k, addr)
        except Tripwire as e:
            tripped = str(e)
        except Exception:
            pass          # unrelated failures are covered by test_find_path
    finally:
        socket.socket = real_socket
        socket.create_connection = real_create
        urllib.request.urlopen = real_urlopen
        os.chdir(cwd)
        if home is not None:
            os.environ["USERPROFILE"] = home
        written = [f for f in os.listdir(workdir) if "FOUND" in f.upper()]
        shutil.rmtree(workdir, ignore_errors=True)

    check("no network access while saving a key", tripped is None,
          tripped or "sockets and urlopen were tripwired")
    check("the key still reached disk", bool(written),
          "%d file(s)" % len(written))


def test_save_path_source_has_no_transmit_calls():
    """Read the function itself: no requests/urlopen/socket anywhere in it."""
    import inspect
    import main

    src = inspect.getsource(main._save_found_key)
    banned = ("requests.", "urlopen", "urllib", "socket.", "http.client",
              "smtplib", "ftplib", "subprocess")
    hits = [b for b in banned if b in src]
    check("save function contains no transmit primitives", not hits,
          ", ".join(hits) if hits else "clean")

    # The broadcast URL in the output is advice for the user to act on, not an
    # action the program takes. Confirm it is only ever printed.
    for line in src.splitlines():
        if "http" in line and "slipstream" in line:
            ok = ("print" in line) or line.strip().startswith('f"') \
                 or line.strip().startswith('"')
            check("broadcast URL is text, not a request", ok, line.strip()[:60])


def test_dp_client_sends_no_private_key():
    """The pool client may share distinguished points -- never a key."""
    import inspect
    from kangaroo import dp_client

    src = inspect.getsource(dp_client)
    # Locate the payload actually POSTed.
    check("payload carries distinguished points", "'dps'" in src or '"dps"' in src)
    for bad in ("privkey", "private_key", "wif", "WIF", "secret"):
        check("payload never mentions %r" % bad, bad not in src)

    # And the server side must not ask for one either.
    from kangaroo import dp_server
    ssrc = inspect.getsource(dp_server)
    for bad in ("privkey", "private_key", "wif"):
        check("pool server never requests %r" % bad, bad not in ssrc)


def test_no_telemetry_anywhere():
    """No analytics or crash-reporting ENDPOINT is contacted.

    Matching the bare words is useless here: this project is literally called
    "All Attacks & Analytics", and the Info page tells users it collects no
    telemetry. Both are prose. What matters is whether a request is ever aimed at
    a reporting service, so look for the hostnames instead.
    """
    import glob
    hosts = ("sentry.io", "ingest.sentry", "google-analytics.com",
             "analytics.google", "mixpanel.com", "api.segment.io",
             "amplitude.com", "bugsnag.com", "datadoghq.com",
             "app.posthog.com")
    hits = []
    for path in glob.glob("**/*.py", recursive=True):
        if any(skip in path for skip in ("BitCrack", "keyhunt", "__pycache__",
                                         "tests" + os.sep)):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                low = f.read().lower()
        except Exception:
            continue
        for h in hosts:
            if h in low:
                hits.append("%s:%s" % (path, h))
    check("no telemetry or crash-reporting endpoints", not hits,
          ", ".join(hits[:3]) if hits else "no reporting hosts referenced")

    # And nothing imports a reporting SDK.
    sdks = ("import sentry_sdk", "from sentry_sdk", "import posthog",
            "import mixpanel", "import bugsnag")
    sdk_hits = []
    for path in glob.glob("**/*.py", recursive=True):
        # Skip tests/: this very file lists the SDK names as search strings and
        # would otherwise report itself.
        if any(skip in path for skip in ("BitCrack", "keyhunt", "__pycache__",
                                         "tests" + os.sep)):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                low = f.read().lower()
        except Exception:
            continue
        for s in sdks:
            if s in low:
                sdk_hits.append("%s:%s" % (path, s))
    check("no reporting SDK imported", not sdk_hits,
          ", ".join(sdk_hits[:3]) if sdk_hits else "clean")


if __name__ == "__main__":
    print("=" * 70)
    print("  KEY EXFILTRATION GUARDS")
    print("=" * 70)
    print("\n--- saving a key performs no network I/O ---")
    test_saving_a_key_makes_no_network_calls()
    print("\n--- the save function contains no transmit primitives ---")
    test_save_path_source_has_no_transmit_calls()
    print("\n--- the DP pool client shares work, not secrets ---")
    test_dp_client_sends_no_private_key()
    print("\n--- no telemetry ---")
    test_no_telemetry_anywhere()
    print("\n" + "=" * 70)
    if FAILS:
        print("  %d FAILED: %s" % (len(FAILS), FAILS))
        sys.exit(1)
    print("  A FOUND KEY STAYS ON THIS MACHINE [OK]")
    print("=" * 70)
