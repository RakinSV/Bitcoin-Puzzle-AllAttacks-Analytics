#!/usr/bin/env python3
"""
Bitcoin Puzzle — All Attacks & Analytics : full desktop application (PySide6).

A complete GUI front-end over the whole toolkit — solver, every offline attack,
every on-chain analysis, live mempool watchers, and GPU tooling. Each action is
run as a child worker (the same binary re-invoked with `--module ...`), so the
UI never freezes, output streams live AND is saved to logs/, and everything
works identically in dev and in the packaged executable.

On first launch, if no analysis data exists yet, it offers to research
everything (full sweep over all 150 puzzles + live puzzle status).
"""

import os
import re
import sys
import time
from datetime import datetime

from PySide6.QtCore import Qt, QProcess, QProcessEnvironment, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QSpinBox, QLineEdit, QPlainTextEdit,
    QGroupBox, QCheckBox, QListWidget, QListWidgetItem, QStackedWidget,
    QScrollArea, QMessageBox, QFrame,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(ROOT, "logs")
REPORTS = os.path.join(ROOT, "reports")

# ── live-output parsers ──────────────────────────────────────────────────────
RE_SPEED  = re.compile(r"speed=\s*([\d.]+)\s*M/?s", re.I)
RE_BENCH  = re.compile(r"Speed:\s*([\d.]+)\s*Mkeys", re.I)
RE_HOPS   = re.compile(r"hops=\s*([\d,]+)")
RE_DP     = re.compile(r"\bdp=\s*(\d+)")
RE_FOUND  = re.compile(r"(?:FOUND\s+k\s*=\s*|Key\s*=\s*|Private key \(hex\):\s*)(0x[0-9a-fA-F]+)")
RE_SOLVED = re.compile(r"SOLVED|FOUND k =", re.I)

QSS = """
QMainWindow, QWidget { background:#0d1117; color:#e6edf3;
    font-family:'Segoe UI',Arial,sans-serif; font-size:13px; }
QListWidget#nav { background:#010409; border:none; border-right:1px solid #21262d;
    font-size:14px; outline:0; }
QListWidget#nav::item { padding:12px 18px; color:#8b949e; }
QListWidget#nav::item:selected { background:#161b22; color:#58a6ff;
    border-left:3px solid #1f6feb; }
QListWidget#nav::item:hover { background:#0d1117; color:#e6edf3; }
QGroupBox { border:1px solid #30363d; border-radius:8px; margin-top:14px;
    padding:12px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 5px; color:#8b949e; }
QPushButton { background:#21262d; border:1px solid #30363d; border-radius:6px;
    padding:7px 14px; font-weight:600; }
QPushButton:hover { background:#30363d; border-color:#8b949e; }
QPushButton#run { background:#238636; border-color:#2ea043; color:white; }
QPushButton#run:hover { background:#2ea043; }
QPushButton#stop { background:#b62324; border-color:#da3633; color:white; }
QPushButton#stop:hover { background:#da3633; }
QPushButton#primary { background:#1f6feb; border-color:#388bfd; color:white; padding:10px 18px; }
QPushButton:disabled { background:#161b22; color:#484f58; border-color:#21262d; }
QComboBox, QSpinBox, QLineEdit { background:#0d1117; border:1px solid #30363d;
    border-radius:6px; padding:5px 8px; selection-background-color:#1f6feb; }
QComboBox QAbstractItemView { background:#161b22; border:1px solid #30363d;
    selection-background-color:#1f6feb; }
QPlainTextEdit { background:#010409; border:1px solid #30363d; border-radius:8px;
    font-family:'Cascadia Mono','Consolas',monospace; font-size:12px; color:#c9d1d9; }
QLabel#h1 { font-size:20px; font-weight:800; }
QLabel#sub { color:#8b949e; font-size:12px; }
QLabel#desc { color:#8b949e; font-size:12px; }
QLabel#stat { font-family:'Cascadia Mono',monospace; font-size:15px; font-weight:700; color:#58a6ff; }
QLabel#statlabel { color:#8b949e; font-size:11px; }
QLabel#found { background:#1a7f37; color:white; border-radius:8px; padding:10px;
    font-size:14px; font-weight:700; }
"""


def worker_argv(module, args=None):
    """Build argv that re-invokes THIS binary as a `--module` worker."""
    args = args or []
    if getattr(sys, "frozen", False):
        return sys.executable, ["--module", module] + args
    return sys.executable, [os.path.join(ROOT, "app_entry.py"), "--module", module] + args


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bitcoin Puzzle — All Attacks & Analytics")
        self.resize(1100, 780)
        self.proc = None
        self.t0 = None
        self.logfile = None
        self.run_buttons = []
        self.timer = QTimer(self); self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self._build()
        QTimer.singleShot(400, self._first_run_check)

    # ====================================================================
    #  layout
    # ====================================================================
    def _build(self):
        central = QWidget(); self.setCentralWidget(central)
        outer = QHBoxLayout(central); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        # sidebar
        self.nav = QListWidget(); self.nav.setObjectName("nav")
        self.nav.setFixedWidth(210)
        for name in ["  Dashboard", "  Solve", "  Offline analyses",
                     "  On-chain recon", "  Live watch", "  GPU tools", "  Reports & logs"]:
            QListWidgetItem(name, self.nav)
        self.nav.currentRowChanged.connect(lambda i: self.stack.setCurrentIndex(i))
        outer.addWidget(self.nav)

        # right side
        right = QWidget(); rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 16, 16, 12); rl.setSpacing(10)
        outer.addWidget(right, 1)

        rl.addWidget(self._header())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_dashboard())
        self.stack.addWidget(self._page_solve())
        self.stack.addWidget(self._page_offline())
        self.stack.addWidget(self._page_onchain())
        self.stack.addWidget(self._page_watch())
        self.stack.addWidget(self._page_gpu())
        self.stack.addWidget(self._page_reports())
        rl.addWidget(self.stack)

        rl.addWidget(self._stats_bar())

        self.found = QLabel(""); self.found.setObjectName("found")
        self.found.setVisible(False); self.found.setWordWrap(True)
        self.found.setTextInteractionFlags(Qt.TextSelectableByMouse)
        rl.addWidget(self.found)

        self.log = QPlainTextEdit(); self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(8000)
        rl.addWidget(self.log, 1)

        rl.addLayout(self._bottom_bar())

        self.nav.setCurrentRow(0)
        self.setStyleSheet(QSS)

    def _header(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(2)
        t = QLabel("🔐  Bitcoin Puzzle — All Attacks & Analytics"); t.setObjectName("h1")
        s = QLabel("Custom OpenCL secp256k1 engine · Pollard's Kangaroo · 9-attack cryptanalysis suite")
        s.setObjectName("sub")
        v.addWidget(t); v.addWidget(s)
        return w

    def _stats_bar(self):
        box = QGroupBox("Live status"); g = QGridLayout(box)
        self.stat_status = self._stat(g, 0, "Status", "idle")
        self.stat_speed  = self._stat(g, 1, "Speed", "—")
        self.stat_hops   = self._stat(g, 2, "Hops / keys", "—")
        self.stat_dp     = self._stat(g, 3, "DPs", "—")
        self.stat_time   = self._stat(g, 4, "Elapsed", "0s")
        self.stat_task   = self._stat(g, 5, "Task", "—")
        return box

    def _stat(self, grid, col, label, value):
        v = QVBoxLayout()
        lab = QLabel(label); lab.setObjectName("statlabel")
        val = QLabel(value); val.setObjectName("stat")
        v.addWidget(lab); v.addWidget(val)
        wrap = QWidget(); wrap.setLayout(v); grid.addWidget(wrap, 0, col)
        return val

    def _bottom_bar(self):
        bar = QHBoxLayout()
        self.btn_stop = QPushButton("■  Stop"); self.btn_stop.setObjectName("stop")
        self.btn_stop.clicked.connect(self.stop); self.btn_stop.setEnabled(False)
        b_logs = QPushButton("📂 Open logs"); b_logs.clicked.connect(lambda: _open(LOGS))
        b_rep = QPushButton("📂 Open reports"); b_rep.clicked.connect(self._open_reports)
        b_clear = QPushButton("Clear log"); b_clear.clicked.connect(lambda: self.log.clear())
        bar.addWidget(self.btn_stop); bar.addStretch(1)
        bar.addWidget(b_clear); bar.addWidget(b_logs); bar.addWidget(b_rep)
        return bar

    # ====================================================================
    #  reusable card
    # ====================================================================
    def _scroll(self, inner):
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame)
        sc.setWidget(inner)
        return sc

    def _card(self, layout, title, desc, builder, inputs=None, primary=False):
        box = QGroupBox(title); v = QVBoxLayout(box)
        d = QLabel(desc); d.setObjectName("desc"); d.setWordWrap(True); v.addWidget(d)
        if inputs:
            v.addLayout(inputs)
        btn = QPushButton("▶  Run"); btn.setObjectName("primary" if primary else "run")
        btn.clicked.connect(lambda: self._start_builder(builder, title))
        row = QHBoxLayout(); row.addStretch(1); row.addWidget(btn)
        v.addLayout(row)
        self.run_buttons.append(btn)
        layout.addWidget(box)
        return box

    # ====================================================================
    #  pages
    # ====================================================================
    def _page_dashboard(self):
        inner = QWidget(); v = QVBoxLayout(inner)
        self.data_status = QLabel(""); self.data_status.setObjectName("desc")
        self.data_status.setWordWrap(True)
        box = QGroupBox("Data status"); bl = QVBoxLayout(box); bl.addWidget(self.data_status)
        v.addWidget(box)
        self._refresh_data_status()

        self._card(v, "First-time full research",
                   "Run every offline + on-chain analysis across all 150 puzzles and write "
                   "the results to reports/. Do this once to populate your data.",
                   lambda: worker_argv("run_all_analyses"), primary=True)
        self._card(v, "Refresh live puzzle status",
                   "Re-query the blockchain for which puzzles are still unsolved (cached up to 6h).",
                   lambda: worker_argv("analysis.puzzle_status", ["--unsolved", "--max", "150", "--refresh"]))
        v.addStretch(1)
        return self._scroll(inner)

    def _page_solve(self):
        inner = QWidget(); v = QVBoxLayout(inner)
        box = QGroupBox("Target"); g = QGridLayout(box)
        g.addWidget(QLabel("Mode"), 0, 0)
        self.s_mode = QComboBox()
        self.s_mode.addItems(["GPU lottery (brute force)", "Pollard's Kangaroo (known pubkey)", "CPU (reference)"])
        self.s_mode.currentIndexChanged.connect(self._solve_mode_changed)
        g.addWidget(self.s_mode, 0, 1, 1, 3)
        g.addWidget(QLabel("Puzzle #"), 1, 0)
        self.s_puzzle = QSpinBox(); self.s_puzzle.setRange(1, 150); self.s_puzzle.setValue(71)
        g.addWidget(self.s_puzzle, 1, 1)
        self.s_pool = QCheckBox("Pool-avoid"); self.s_pool.setChecked(True)
        g.addWidget(self.s_pool, 1, 2)
        g.addWidget(QLabel("jump-every"), 1, 3)
        self.s_jump = QSpinBox(); self.s_jump.setRange(1, 100000); self.s_jump.setValue(1000)
        g.addWidget(self.s_jump, 1, 4)
        self.s_pk_label = QLabel("Public key (hex)")
        g.addWidget(self.s_pk_label, 2, 0)
        self.s_pubkey = QLineEdit(); self.s_pubkey.setPlaceholderText("02…/03… or 04…")
        g.addWidget(self.s_pubkey, 2, 1, 1, 4)
        v.addWidget(box)

        runbox = QGroupBox("Run solver"); rb = QVBoxLayout(runbox)
        desc = QLabel("Lottery brute-forces the chosen puzzle (realistic only for #71–80). "
                      "Kangaroo needs the target's public key but solves a 71-bit range in minutes.")
        desc.setObjectName("desc"); desc.setWordWrap(True); rb.addWidget(desc)
        btn = QPushButton("▶  Start solving"); btn.setObjectName("primary")
        btn.clicked.connect(lambda: self._start_builder(self._build_solve, "Solve"))
        rr = QHBoxLayout(); rr.addStretch(1); rr.addWidget(btn); rb.addLayout(rr)
        self.run_buttons.append(btn)
        v.addWidget(runbox)
        v.addStretch(1)
        self._solve_mode_changed()
        return self._scroll(inner)

    def _build_solve(self):
        n = str(self.s_puzzle.value())
        idx = self.s_mode.currentIndex()
        if idx == 1:  # kangaroo
            pk = self.s_pubkey.text().strip()
            if not pk:
                raise ValueError("Kangaroo mode needs the target's public key.")
            return worker_argv("main", ["--puzzle", n, "--mode", "kangaroo", "--pubkey", pk])
        if idx == 2:  # cpu
            return worker_argv("main", ["--puzzle", n, "--mode", "cpu", "--pure-random"])
        args = ["--puzzle", n, "--mode", "gpu", "--pure-random", "--jump-every", str(self.s_jump.value())]
        if self.s_pool.isChecked():
            args.append("--pool-avoid")
        return worker_argv("main", args)

    def _solve_mode_changed(self):
        kang = self.s_mode.currentIndex() == 1
        lot = self.s_mode.currentIndex() == 0
        self.s_pk_label.setVisible(kang); self.s_pubkey.setVisible(kang)
        self.s_pool.setVisible(lot); self.s_jump.setVisible(lot)

    def _page_offline(self):
        inner = QWidget(); v = QVBoxLayout(inner)
        tgt = QGroupBox("Per-puzzle target (for RNG-predict / BIP32 / brainwallet)")
        tl = QHBoxLayout(tgt); tl.addWidget(QLabel("Puzzle #"))
        self.o_target = QSpinBox(); self.o_target.setRange(1, 150); self.o_target.setValue(71)
        tl.addWidget(self.o_target); tl.addStretch(1)
        v.addWidget(tgt)

        self._card(v, "Run ALL analyses (all 150 puzzles)",
                   "Every offline + on-chain attack across all puzzles, written to reports/.",
                   lambda: worker_argv("run_all_analyses"), primary=True)
        self._card(v, "RNG distribution (quick)", "Statistical look at the known keys for PRNG bias.",
                   lambda: worker_argv("analysis.rng_analysis", ["--quick"]))
        self._card(v, "RNG key prediction", "Try to predict the target key from seeded-RNG / LCG hypotheses.",
                   lambda: worker_argv("analysis.rng_analysis", ["--predict", "--target", str(self.o_target.value())]))
        self._card(v, "RNG priority segments", "Where in each interval keys cluster (search-zone hints).",
                   lambda: worker_argv("analysis.rng_analysis", ["--segments"]))
        self._card(v, "BIP32 / HD-wallet pattern", "Test whether keys are children of one master seed.",
                   lambda: worker_argv("analysis.bip32_analysis", ["--test-all"]))
        self._card(v, "Brainwallet dictionary", "privkey = SHA256(passphrase) — validated wordlist attack.",
                   lambda: worker_argv("analysis.brainwallet_attack", ["--target", str(self.o_target.value())]))
        self._card(v, "NIST SP 800-22 randomness battery", "Formal p-value tests on the known key bits.",
                   lambda: worker_argv("analysis.nist_randomness"))
        v.addStretch(1)
        return self._scroll(inner)

    def _page_onchain(self):
        inner = QWidget(); v = QVBoxLayout(inner)
        note = QLabel("These query the blockchain — internet required.")
        note.setObjectName("desc"); v.addWidget(note)
        self._card(v, "Live puzzle status", "Which puzzles are still unsolved + attack priority.",
                   lambda: worker_argv("analysis.puzzle_status", ["--unsolved", "--max", "150"]))
        self._card(v, "Ghost-solved re-verification", "Re-check #75…130 on-chain for funds / exposed pubkeys.",
                   lambda: worker_argv("analysis.ghost_solved_check"))
        self._card(v, "Creator fingerprint (deep)", "Common-input-ownership clustering + fee/timing fingerprints.",
                   lambda: worker_argv("analysis.creator_fingerprint", ["--deep"]))
        self._card(v, "ECDSA nonce-reuse attack", "Scan creator/solver signatures for reused or biased nonces.",
                   lambda: worker_argv("analysis.nonce_attack", ["--quick"]))
        self._card(v, "Pubkey EC-point patterns", "Harvest exposed pubkeys and test for structural relations.",
                   lambda: worker_argv("analysis.pubkey_pattern", ["--collect"]))
        v.addStretch(1)
        return self._scroll(inner)

    def _page_watch(self):
        inner = QWidget(); v = QVBoxLayout(inner)
        # multi-sniper
        box = QGroupBox("Multi-puzzle mempool sniper"); g = QGridLayout(box)
        d = QLabel("Watch ALL unsolved puzzles; the instant a rival spends and exposes a pubkey, "
                   "fire Kangaroo to win the block race.")
        d.setObjectName("desc"); d.setWordWrap(True); g.addWidget(d, 0, 0, 1, 4)
        g.addWidget(QLabel("Poll interval (s)"), 1, 0)
        self.ms_interval = QSpinBox(); self.ms_interval.setRange(5, 600); self.ms_interval.setValue(20)
        g.addWidget(self.ms_interval, 1, 1)
        g.addWidget(QLabel("Max bits to auto-solve"), 1, 2)
        self.ms_maxbits = QSpinBox(); self.ms_maxbits.setRange(40, 130); self.ms_maxbits.setValue(80)
        g.addWidget(self.ms_maxbits, 1, 3)
        self.ms_auto = QCheckBox("Auto-fire Kangaroo on hit"); self.ms_auto.setChecked(True)
        g.addWidget(self.ms_auto, 2, 0, 1, 2)
        b = QPushButton("▶  Start sniper"); b.setObjectName("run")
        b.clicked.connect(lambda: self._start_builder(self._build_sniper, "Multi-sniper"))
        self.run_buttons.append(b)
        rr = QHBoxLayout(); rr.addStretch(1); rr.addWidget(b); g.addLayout(rr, 3, 0, 1, 4)
        v.addWidget(box)

        # monitor
        mbox = QGroupBox("Single-puzzle mempool monitor"); mg = QGridLayout(mbox)
        md = QLabel("Watch one puzzle address; detect a pubkey exposure (HTTP or WebSocket).")
        md.setObjectName("desc"); md.setWordWrap(True); mg.addWidget(md, 0, 0, 1, 4)
        mg.addWidget(QLabel("Puzzle #"), 1, 0)
        self.mon_puzzle = QSpinBox(); self.mon_puzzle.setRange(1, 150); self.mon_puzzle.setValue(71)
        mg.addWidget(self.mon_puzzle, 1, 1)
        self.mon_ws = QCheckBox("WebSocket (sub-second)"); self.mon_ws.setChecked(True)
        mg.addWidget(self.mon_ws, 1, 2)
        mb = QPushButton("▶  Start monitor"); mb.setObjectName("run")
        mb.clicked.connect(lambda: self._start_builder(self._build_monitor, "Monitor"))
        self.run_buttons.append(mb)
        mr = QHBoxLayout(); mr.addStretch(1); mr.addWidget(mb); mg.addLayout(mr, 2, 0, 1, 4)
        v.addWidget(mbox)
        v.addStretch(1)
        return self._scroll(inner)

    def _build_sniper(self):
        args = ["--interval", str(self.ms_interval.value()), "--max-bits", str(self.ms_maxbits.value())]
        if self.ms_auto.isChecked():
            args.append("--autosolve")
        return worker_argv("multi_sniper", args)

    def _build_monitor(self):
        args = ["--puzzle", str(self.mon_puzzle.value())]
        if self.mon_ws.isChecked():
            args.append("--websocket")
        return worker_argv("monitor", args)

    def _page_gpu(self):
        inner = QWidget(); v = QVBoxLayout(inner)
        self._card(v, "List OpenCL devices", "Show the GPUs the engine can see.",
                   lambda: worker_argv("main", ["--devices"]))
        self._card(v, "Quick benchmark", "Single-config GPU throughput (Mkeys/s).",
                   lambda: worker_argv("main", ["--bench"]))
        self._card(v, "Benchmark sweep", "Map throughput vs. parallel-walker count and find the VRAM cliff.",
                   lambda: worker_argv("main", ["--bench-sweep"]))
        v.addStretch(1)
        return self._scroll(inner)

    def _page_reports(self):
        inner = QWidget(); v = QVBoxLayout(inner)
        b1 = QPushButton("📂  Open reports folder"); b1.clicked.connect(self._open_reports)
        b2 = QPushButton("📂  Open logs folder"); b2.clicked.connect(lambda: _open(LOGS))
        v.addWidget(b1); v.addWidget(b2)
        self.reports_list = QPlainTextEdit(); self.reports_list.setReadOnly(True)
        v.addWidget(QLabel("Recent report runs:"))
        v.addWidget(self.reports_list, 1)
        self._refresh_reports_list()
        return inner

    # ====================================================================
    #  run engine
    # ====================================================================
    def _start_builder(self, builder, label):
        try:
            prog, args = builder()
        except ValueError as e:
            QMessageBox.warning(self, "Cannot start", str(e)); return
        self.start(prog, args, label)

    def start(self, prog, args, label):
        if self.proc is not None:
            QMessageBox.information(self, "Busy", "A task is already running. Stop it first."); return
        self.found.setVisible(False)
        self.stat_speed.setText("—"); self.stat_hops.setText("—"); self.stat_dp.setText("—")
        self._set(self.stat_status, "running", "#3fb950"); self.stat_task.setText(label)
        self._open_logfile(label)
        self._append(f"$ {os.path.basename(prog)} {' '.join(args)}\n", "#6e7681")

        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8"); env.insert("PYTHONUTF8", "1")
        self.proc.setProcessEnvironment(env)
        self.proc.setWorkingDirectory(ROOT)
        self.proc.readyReadStandardOutput.connect(self._on_output)
        self.proc.finished.connect(self._on_finished)
        self.proc.start(prog, args)
        self.t0 = time.time(); self.timer.start()
        self.btn_stop.setEnabled(True)
        for b in self.run_buttons:
            b.setEnabled(False)

    def stop(self):
        if self.proc is not None:
            self._append("\n[stopping…]\n", "#d29922"); self.proc.kill()

    def _on_output(self):
        if self.proc is None:
            return
        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        self._append(data, None)
        if self.logfile:
            self.logfile.write(data); self.logfile.flush()
        for line in data.splitlines():
            self._parse(line)

    def _parse(self, line):
        m = RE_SPEED.search(line) or RE_BENCH.search(line)
        if m: self.stat_speed.setText(f"{float(m.group(1)):.0f} M/s")
        m = RE_HOPS.search(line)
        if m: self.stat_hops.setText(m.group(1))
        m = RE_DP.search(line)
        if m: self.stat_dp.setText(m.group(1))
        m = RE_FOUND.search(line)
        if m or RE_SOLVED.search(line):
            self._found(m.group(1) if m else "(see log)")

    def _found(self, key):
        self.found.setText(f"🎉  KEY FOUND:  {key}\nSaved to FOUND_KEY.txt — verify before broadcasting.")
        self.found.setVisible(True)
        self._set(self.stat_status, "SOLVED", "#3fb950")

    def _on_finished(self, code, _s):
        self.timer.stop()
        ok = code == 0
        self._set(self.stat_status, "done" if ok else f"exit {code}", "#3fb950" if ok else "#f85149")
        self._append(f"\n[finished, exit {code}]\n", "#6e7681")
        if self.logfile:
            self.logfile.close(); self.logfile = None
        self.proc = None
        self.btn_stop.setEnabled(False)
        for b in self.run_buttons:
            b.setEnabled(True)
        self._refresh_data_status(); self._refresh_reports_list()

    def _tick(self):
        if self.t0:
            s = int(time.time() - self.t0); h, m, x = s // 3600, (s % 3600) // 60, s % 60
            self.stat_time.setText(f"{h}h{m:02d}m{x:02d}s" if h else f"{m}m{x:02d}s" if m else f"{x}s")

    # ====================================================================
    #  logging / data status / first run
    # ====================================================================
    def _open_logfile(self, label):
        try:
            os.makedirs(LOGS, exist_ok=True)
            safe = re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_").lower()
            path = os.path.join(LOGS, f"{datetime.now():%Y%m%d_%H%M%S}_{safe}.log")
            self.logfile = open(path, "w", encoding="utf-8")
            self.logfile.write(f"# {label} — {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        except Exception:
            self.logfile = None

    def _refresh_data_status(self):
        def mark(ok): return "✅" if ok else "❌"
        known = os.path.exists(os.path.join(ROOT, "known_keys.json"))
        status = os.path.exists(os.path.join(ROOT, "puzzle_status_cache.json"))
        nrep = len([d for d in os.listdir(REPORTS)]) if os.path.isdir(REPORTS) else 0
        self.data_status.setText(
            f"{mark(known)}  Puzzle reference data (known_keys.json)\n"
            f"{mark(status)}  Live puzzle-status cache\n"
            f"{mark(nrep > 0)}  Analysis reports on disk: {nrep} run(s)\n\n"
            + ("Looks like a fresh setup — run 'First-time full research' below to populate everything."
               if nrep == 0 else "Data present. Re-run any analysis to refresh.")
        )

    def _refresh_reports_list(self):
        if not hasattr(self, "reports_list"):
            return
        if not os.path.isdir(REPORTS):
            self.reports_list.setPlainText("(no reports yet — run a full analysis)"); return
        runs = sorted(os.listdir(REPORTS), reverse=True)[:25]
        self.reports_list.setPlainText("\n".join(runs) or "(empty)")

    def _first_run_check(self):
        has_reports = os.path.isdir(REPORTS) and len(os.listdir(REPORTS)) > 0
        has_status = os.path.exists(os.path.join(ROOT, "puzzle_status_cache.json"))
        if has_reports or has_status:
            return
        r = QMessageBox.question(
            self, "First launch — research everything?",
            "No analysis data found yet.\n\nRun the full first-time research now? "
            "It runs every offline & on-chain analysis across all 150 puzzles and "
            "writes the results to reports/ (offline parts are quick; on-chain needs internet).",
            QMessageBox.Yes | QMessageBox.No)
        if r == QMessageBox.Yes:
            self.nav.setCurrentRow(0)
            prog, args = worker_argv("run_all_analyses")
            self.start(prog, args, "First-time full research")

    # ====================================================================
    #  helpers
    # ====================================================================
    def _append(self, text, color):
        self.log.moveCursor(QTextCursor.End)
        if color:
            self.log.appendHtml(f'<span style="color:{color}">{_html(text)}</span>')
        else:
            self.log.insertPlainText(text)
        self.log.moveCursor(QTextCursor.End)

    def _set(self, w, text, color):
        w.setText(text)
        w.setStyleSheet(f"font-family:'Cascadia Mono',monospace;font-size:15px;font-weight:700;color:{color};")

    def _open_reports(self):
        if not os.path.isdir(REPORTS):
            QMessageBox.information(self, "No reports yet", "Run a full analysis first."); return
        subs = [os.path.join(REPORTS, x) for x in os.listdir(REPORTS)]
        subs = [x for x in subs if os.path.isdir(x)]
        _open(max(subs, key=os.path.getmtime) if subs else REPORTS)

    def closeEvent(self, e):
        if self.proc is not None:
            self.proc.kill(); self.proc.waitForFinished(1500)
        if self.logfile:
            self.logfile.close()
        e.accept()


def _html(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>"))


def _open(path):
    os.makedirs(path, exist_ok=True) if not os.path.exists(path) else None
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa
    elif sys.platform == "darwin":
        os.system(f'open "{path}"')
    else:
        os.system(f'xdg-open "{path}"')


def run_gui():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Bitcoin Puzzle — All Attacks & Analytics")
    win = MainWindow(); win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_gui()
