#!/usr/bin/env python3
"""
A found key must not end up in a log file.

The key is printed to stdout so it is visible the instant it appears, and the GUI
mirrors worker stdout into logs/. Left alone, that puts a live private key in the
one file people cheerfully attach to a bug report, drop in a cloud-synced folder,
or reach for via the app's own "Open logs" button. It is not an external leak --
logs/ is gitignored and never transmitted -- but it is a copy of the key
somewhere nobody thinks of as sensitive.

So the log mirror is redacted. The screen still shows everything, and
FOUND_KEY.txt remains the authoritative copy.

The redaction has to stay SURGICAL, which is the other half of what these tests
protect: a blanket hex rule also eats the search position and the pool bounds,
and a log where every number reads <REDACTED> cannot diagnose anything.

Run:  python tests/test_log_redaction.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.gui as gui                                    # noqa: E402

FAILS = []

KEY_HEX = "122fca143c05"
KEY_DEC = "19996463086597"
KEY_WIF = "KwDiBf89QgGbjEhKnhXJuH7LrciVrZi3qYjgdDrgx63tbte4scLA"
SECRETS = (KEY_HEX, KEY_DEC, KEY_WIF)


def check(name, cond, detail=""):
    print("  [%s] %s%s" % ("OK" if cond else "FAIL", name,
                           ("  -- " + detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def test_every_announcement_form_is_redacted():
    """Each way the code can print a key must be caught.

    There are several: the GPU path prints a labelled block, the CPU path prints
    "k = <dec> = <hex>" on one line, and the saved file echoes HEX/WIF plus an
    importprivkey command. A rule that catches only the first form leaks the rest.
    """
    forms = [
        "  KEY FOUND: 0x%s" % KEY_HEX,
        "  Decimal:   %s" % KEY_DEC,
        "  WIF:       %s" % KEY_WIF,
        "!!! KEY FOUND: k = %s = 0x%s !!!" % (KEY_DEC, KEY_HEX),
        "HEX: 0x%s" % KEY_HEX,
        "Private key (dec):  %s" % KEY_DEC,
        "  importprivkey %s" % KEY_WIF,
    ]
    for form in forms:
        out = gui._redact_secrets(form)
        leaked = [s for s in SECRETS if s in out]
        check("redacted: %s" % form.strip()[:44], not leaked,
              "leaked %s" % leaked if leaked else "")


def test_a_bare_wif_is_caught_without_any_label():
    """A WIF is unmistakable, so context must not be required to strip it."""
    out = gui._redact_secrets("something unexpected: %s" % KEY_WIF)
    check("bare WIF stripped with no key label", KEY_WIF not in out)


def test_ordinary_telemetry_survives():
    """The log must remain usable, or redaction has traded one problem for another."""
    line = ("[GPU] 405.69 Mkeys/s | Jumps: 12 | Pos: 0x72c8804ecdd91b5a9e | "
            "Total: 0.0212T")
    pool = ("Pool avoid: [0x400000000000000000, 0x409637a00000000000) = "
            "0.92% skipped")
    utxo = "[utxo] #71: 59 output(s), 7.10185241 BTC"
    out = gui._redact_secrets("\n".join([line, pool, utxo]))
    check("speed and position survive", "405.69 Mkeys/s" in out
          and "0x72c8804ecdd91b5a9e" in out)
    check("pool bounds survive", "0x409637a00000000000" in out)
    check("utxo summary survives", "59 output(s)" in out)
    check("nothing was redacted at all here", "REDACTED" not in out)


def test_the_mirror_actually_uses_it():
    """Wiring check: the log write must pass through the redactor."""
    import inspect
    src = inspect.getsource(gui.MainWindow)
    idx = src.find("self.logfile.write(")
    check("log writes go through _redact_secrets",
          idx != -1 and "_redact_secrets" in src[idx:idx + 80],
          src[idx:idx + 60].strip() if idx != -1 else "no logfile.write found")


if __name__ == "__main__":
    print("=" * 68)
    print("  LOG REDACTION -- keys stay out of shareable logs")
    print("=" * 68)
    print("\n--- every way a key can be announced ---")
    test_every_announcement_form_is_redacted()
    print("\n--- a WIF needs no label ---")
    test_a_bare_wif_is_caught_without_any_label()
    print("\n--- the log stays useful ---")
    test_ordinary_telemetry_survives()
    print("\n--- the mirror is actually wired to it ---")
    test_the_mirror_actually_uses_it()
    print("\n" + "=" * 68)
    if FAILS:
        print("  %d FAILED: %s" % (len(FAILS), FAILS))
        sys.exit(1)
    print("  NO KEY MATERIAL REACHES A LOG FILE [OK]")
    print("=" * 68)
