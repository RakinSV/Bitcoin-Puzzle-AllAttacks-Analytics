#!/usr/bin/env python3
"""
Unified entry point for the desktop app AND the packaged executable.

One binary, two roles:
  * no args / launched normally  -> open the GUI
  * first arg is "--cli"          -> act as the CLI worker (runs main.py logic)

The GUI launches work by re-invoking this same executable with "--cli ...".
That makes the frozen PyInstaller .exe self-contained: the GUI and the solver
are the same binary, so there is no separate python needed at runtime.
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main():
    argv = sys.argv
    if len(argv) > 1 and argv[1] == "--cli":
        # Worker role: strip the marker and hand off to the existing solver CLI.
        sys.argv = [argv[0]] + argv[2:]
        import main as cli_main
        cli_main.main()
        return

    if len(argv) > 1 and argv[1] == "--run-analyses":
        # Worker role: run the full analysis sweep over all puzzles.
        sys.argv = [argv[0]] + argv[2:]
        import run_all_analyses
        run_all_analyses.main()
        return

    if len(argv) > 2 and argv[1] == "--module":
        # Worker role (frozen builds): run a bundled module as __main__.
        # Used by run_all_analyses to invoke analysis scripts inside the .exe,
        # where there is no python interpreter to run a .py file directly.
        import runpy
        modname = argv[2]
        sys.argv = [modname] + argv[3:]
        runpy.run_module(modname, run_name="__main__")
        return

    # GUI role.
    from app.gui import run_gui
    run_gui()


if __name__ == "__main__":
    main()
