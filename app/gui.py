#!/usr/bin/env python3
"""
Bitcoin Puzzle — All Attacks & Analytics : desktop GUI (PySide6).

A thin, robust front-end over the existing solver/analysis code. Work runs in a
QProcess (the same executable re-invoked with a worker marker), so the UI never
freezes, output streams live, and it behaves identically in dev and in the
packaged .exe.
"""

import os
import re
import sys
import time

from PySide6.QtCore import Qt, QProcess, QProcessEnvironment, QTimer
from PySide6.QtGui import QFont, QTextCursor, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QSpinBox, QLineEdit, QPlainTextEdit,
    QGroupBox, QCheckBox, QFrame, QFileDialog, QMessageBox,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── modes ──────────────────────────────────────────────────────────────────
MODE_LOTTERY  = "GPU Lottery  (brute force a chosen puzzle)"
MODE_KANGAROO = "Pollard's Kangaroo  (known public key)"
MODE_ANALYSES = "Run ALL analyses  (every attack, all 150 puzzles)"

# ── live-output parsers ──────────────────────────────────────────────────────
RE_SPEED = re.compile(r"speed=\s*([\d.]+)\s*M/?s", re.I)
RE_BENCH = re.compile(r"Speed:\s*([\d.]+)\s*Mkeys", re.I)
RE_HOPS  = re.compile(r"hops=\s*([\d,]+)")
RE_DP    = re.compile(r"\bdp=\s*(\d+)")
RE_FOUND = re.compile(r"(?:FOUND\s+k\s*=\s*|Key\s*=\s*|Private key \(hex\):\s*)(0x[0-9a-fA-F]+)")
RE_SOLVED = re.compile(r"SOLVED|FOUND k =", re.I)


# ── dark theme (GitHub-ish) ──────────────────────────────────────────────────
QSS = """
QMainWindow, QWidget { background: #0d1117; color: #e6edf3;
    font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; }
QGroupBox { border: 1px solid #30363d; border-radius: 8px; margin-top: 14px;
    padding: 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px;
    color: #8b949e; }
QPushButton { background: #21262d; border: 1px solid #30363d; border-radius: 6px;
    padding: 8px 16px; font-weight: 600; }
QPushButton:hover { background: #30363d; border-color: #8b949e; }
QPushButton#run { background: #238636; border-color: #2ea043; color: white; }
QPushButton#run:hover { background: #2ea043; }
QPushButton#stop { background: #b62324; border-color: #da3633; color: white; }
QPushButton#stop:hover { background: #da3633; }
QPushButton:disabled { background: #161b22; color: #484f58; border-color: #21262d; }
QComboBox, QSpinBox, QLineEdit { background: #0d1117; border: 1px solid #30363d;
    border-radius: 6px; padding: 6px 8px; selection-background-color: #1f6feb; }
QComboBox:hover, QSpinBox:hover, QLineEdit:hover { border-color: #8b949e; }
QComboBox QAbstractItemView { background: #161b22; border: 1px solid #30363d;
    selection-background-color: #1f6feb; }
QPlainTextEdit { background: #010409; border: 1px solid #30363d; border-radius: 8px;
    font-family: 'Cascadia Mono','Consolas',monospace; font-size: 12px; color: #c9d1d9; }
QLabel#stat { font-family: 'Cascadia Mono','Consolas',monospace; font-size: 16px;
    font-weight: 700; color: #58a6ff; }
QLabel#statlabel { color: #8b949e; font-size: 11px; }
QLabel#found { background: #1a7f37; color: white; border-radius: 8px; padding: 10px;
    font-size: 14px; font-weight: 700; }
QCheckBox::indicator { width: 16px; height: 16px; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bitcoin Puzzle — All Attacks & Analytics")
        self.resize(960, 720)

        self.proc = None
        self.t0 = None
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)

        self._build_ui()
        self._on_mode_changed()

    # ---- UI construction -------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # header
        title = QLabel("🔐  Bitcoin Puzzle — All Attacks & Analytics")
        title.setStyleSheet("font-size: 20px; font-weight: 800; color: #e6edf3;")
        subtitle = QLabel("Custom OpenCL secp256k1 engine · Pollard's Kangaroo · 9-attack cryptanalysis suite")
        subtitle.setStyleSheet("color: #8b949e; font-size: 12px;")
        root.addWidget(title)
        root.addWidget(subtitle)

        # ── controls ─────────────────────────────────────────────────────
        ctl = QGroupBox("Target & mode")
        g = QGridLayout(ctl)
        g.setVerticalSpacing(10)
        g.setHorizontalSpacing(12)

        g.addWidget(QLabel("Mode"), 0, 0)
        self.mode = QComboBox()
        self.mode.addItems([MODE_LOTTERY, MODE_KANGAROO, MODE_ANALYSES])
        self.mode.currentIndexChanged.connect(self._on_mode_changed)
        g.addWidget(self.mode, 0, 1, 1, 3)

        self.lbl_puzzle = QLabel("Puzzle #")
        g.addWidget(self.lbl_puzzle, 1, 0)
        self.puzzle = QSpinBox()
        self.puzzle.setRange(1, 150)
        self.puzzle.setValue(71)
        g.addWidget(self.puzzle, 1, 1)

        self.opt_pool = QCheckBox("Pool-avoid (skip the already-swept prefix)")
        self.opt_pool.setChecked(True)
        g.addWidget(self.opt_pool, 1, 2, 1, 2)

        self.lbl_pubkey = QLabel("Public key (hex)")
        g.addWidget(self.lbl_pubkey, 2, 0)
        self.pubkey = QLineEdit()
        self.pubkey.setPlaceholderText("02…/03… compressed, or 04… uncompressed")
        g.addWidget(self.pubkey, 2, 1, 1, 3)

        self.hint = QLabel("")
        self.hint.setStyleSheet("color: #8b949e; font-size: 11px;")
        self.hint.setWordWrap(True)
        g.addWidget(self.hint, 3, 0, 1, 4)

        root.addWidget(ctl)

        # ── run / stop ────────────────────────────────────────────────────
        bar = QHBoxLayout()
        self.btn_run = QPushButton("▶  Start")
        self.btn_run.setObjectName("run")
        self.btn_run.clicked.connect(self.start)
        self.btn_stop = QPushButton("■  Stop")
        self.btn_stop.setObjectName("stop")
        self.btn_stop.clicked.connect(self.stop)
        self.btn_stop.setEnabled(False)
        self.btn_reports = QPushButton("📂  Open reports")
        self.btn_reports.clicked.connect(self._open_reports)
        bar.addWidget(self.btn_run)
        bar.addWidget(self.btn_stop)
        bar.addStretch(1)
        bar.addWidget(self.btn_reports)
        root.addLayout(bar)

        # ── live stats ────────────────────────────────────────────────────
        stats = QGroupBox("Live status")
        sg = QGridLayout(stats)
        self.stat_status = self._stat(sg, 0, "Status", "idle")
        self.stat_speed  = self._stat(sg, 1, "Speed", "—")
        self.stat_hops   = self._stat(sg, 2, "Hops / keys", "—")
        self.stat_dp     = self._stat(sg, 3, "DPs", "—")
        self.stat_time   = self._stat(sg, 4, "Elapsed", "0s")
        root.addWidget(stats)

        # found banner
        self.found = QLabel("")
        self.found.setObjectName("found")
        self.found.setVisible(False)
        self.found.setWordWrap(True)
        self.found.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.found)

        # ── log ───────────────────────────────────────────────────────────
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        root.addWidget(self.log, 1)

        self.setStyleSheet(QSS)

    def _stat(self, grid, col, label, value):
        box = QVBoxLayout()
        lab = QLabel(label)
        lab.setObjectName("statlabel")
        val = QLabel(value)
        val.setObjectName("stat")
        box.addWidget(lab)
        box.addWidget(val)
        w = QWidget()
        w.setLayout(box)
        grid.addWidget(w, 0, col)
        return val

    # ---- mode switching --------------------------------------------------
    def _on_mode_changed(self):
        m = self.mode.currentText()
        is_kang = m == MODE_KANGAROO
        is_anal = m == MODE_ANALYSES
        per_puzzle = not is_anal
        for w in (self.lbl_puzzle, self.puzzle):
            w.setVisible(per_puzzle)
        for w in (self.lbl_pubkey, self.pubkey):
            w.setVisible(is_kang)
        self.opt_pool.setVisible(m == MODE_LOTTERY)
        self.btn_reports.setVisible(is_anal)
        if is_anal:
            self.hint.setText("Runs every offline & on-chain analysis across all 150 puzzles and "
                              "writes results to the reports/ folder. No key search — pure recon.")
        elif is_kang:
            self.hint.setText("Fastest path: with a known public key, the interval collapses to a "
                              "~minutes-long Kangaroo walk. Paste the exposed pubkey above.")
        else:
            self.hint.setText("Brute-force lottery on the chosen puzzle. Realistic only for #71–80 "
                              "on a consumer GPU; higher bits are astronomically unlikely.")

    # ---- worker command --------------------------------------------------
    def _worker_cmd(self):
        """Return (program, args) re-invoking THIS binary as a worker."""
        frozen = getattr(sys, "frozen", False)
        prog = sys.executable
        prefix = [] if frozen else [os.path.join(ROOT, "app_entry.py")]

        m = self.mode.currentText()
        if m == MODE_ANALYSES:
            return prog, prefix + ["--run-analyses"]

        args = ["--cli", "--puzzle", str(self.puzzle.value())]
        if m == MODE_KANGAROO:
            pk = self.pubkey.text().strip()
            args += ["--mode", "kangaroo", "--pubkey", pk]
        else:  # lottery
            args += ["--mode", "gpu", "--pure-random", "--jump-every", "1000"]
            if self.opt_pool.isChecked():
                args += ["--pool-avoid"]
        return prog, prefix + args

    # ---- run / stop ------------------------------------------------------
    def start(self):
        if self.proc is not None:
            return
        if self.mode.currentText() == MODE_KANGAROO and not self.pubkey.text().strip():
            QMessageBox.warning(self, "Public key required",
                                "Kangaroo mode needs the target's public key (hex).")
            return

        prog, args = self._worker_cmd()
        self.log.clear()
        self.found.setVisible(False)
        self._set_stat(self.stat_status, "running", "#3fb950")
        self.stat_speed.setText("—"); self.stat_hops.setText("—"); self.stat_dp.setText("—")
        self._append(f"$ {os.path.basename(prog)} {' '.join(args)}\n", "#6e7681")

        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUTF8", "1")
        self.proc.setProcessEnvironment(env)
        self.proc.setWorkingDirectory(ROOT)
        self.proc.readyReadStandardOutput.connect(self._on_output)
        self.proc.finished.connect(self._on_finished)
        self.proc.start(prog, args)

        self.t0 = time.time()
        self.timer.start()
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.mode.setEnabled(False)

    def stop(self):
        if self.proc is not None:
            self._append("\n[stopping…]\n", "#d29922")
            self.proc.kill()

    # ---- process events --------------------------------------------------
    def _on_output(self):
        if self.proc is None:
            return
        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        self._append(data, None)
        for line in data.splitlines():
            self._parse(line)

    def _parse(self, line):
        m = RE_SPEED.search(line) or RE_BENCH.search(line)
        if m:
            self.stat_speed.setText(f"{float(m.group(1)):.0f} M/s")
        m = RE_HOPS.search(line)
        if m:
            self.stat_hops.setText(m.group(1))
        m = RE_DP.search(line)
        if m:
            self.stat_dp.setText(m.group(1))
        m = RE_FOUND.search(line)
        if m or RE_SOLVED.search(line):
            key = m.group(1) if m else "(see log)"
            self._show_found(key)

    def _show_found(self, key):
        self.found.setText(f"🎉  KEY FOUND:  {key}\n"
                           f"Saved to FOUND_KEY.txt — verify before broadcasting.")
        self.found.setVisible(True)
        self._set_stat(self.stat_status, "SOLVED", "#3fb950")

    def _on_finished(self, code, _status):
        self.timer.stop()
        ok = code == 0
        self._set_stat(self.stat_status,
                       "done" if ok else f"exit {code}",
                       "#3fb950" if ok else "#f85149")
        self._append(f"\n[process finished, exit {code}]\n", "#6e7681")
        self.proc = None
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.mode.setEnabled(True)
        if self.mode.currentText() == MODE_ANALYSES and ok:
            self._append("Reports written to reports/. Click 'Open reports'.\n", "#58a6ff")

    def _tick(self):
        if self.t0:
            s = int(time.time() - self.t0)
            h, m, sec = s // 3600, (s % 3600) // 60, s % 60
            self.stat_time.setText(f"{h}h{m:02d}m{sec:02d}s" if h else
                                   f"{m}m{sec:02d}s" if m else f"{sec}s")

    # ---- helpers ---------------------------------------------------------
    def _append(self, text, color):
        self.log.moveCursor(QTextCursor.End)
        if color:
            self.log.appendHtml(f'<span style="color:{color}">{_html(text)}</span>')
        else:
            self.log.insertPlainText(text)
        self.log.moveCursor(QTextCursor.End)

    def _set_stat(self, widget, text, color):
        widget.setText(text)
        widget.setStyleSheet(f"font-family:'Cascadia Mono',monospace;font-size:16px;"
                             f"font-weight:700;color:{color};")

    def _open_reports(self):
        d = os.path.join(ROOT, "reports")
        if not os.path.isdir(d):
            QMessageBox.information(self, "No reports yet",
                                    "Run 'Run ALL analyses' first — reports/ will appear here.")
            return
        # newest subfolder
        subs = [os.path.join(d, x) for x in os.listdir(d)]
        subs = [x for x in subs if os.path.isdir(x)]
        target = max(subs, key=os.path.getmtime) if subs else d
        _open_in_file_manager(target)

    def closeEvent(self, e):
        if self.proc is not None:
            self.proc.kill()
            self.proc.waitForFinished(1500)
        e.accept()


def _html(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace("\n", "<br>"))


def _open_in_file_manager(path):
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa
    elif sys.platform == "darwin":
        os.system(f'open "{path}"')
    else:
        os.system(f'xdg-open "{path}"')


def run_gui():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Bitcoin Puzzle — All Attacks & Analytics")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_gui()
