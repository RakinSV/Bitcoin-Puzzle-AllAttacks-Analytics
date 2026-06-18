#!/usr/bin/env python3
"""
Generate the "VRAM performance cliff" benchmark chart from the real RX 6600
measurements (GPU brute mode, threads=64, blocks=4096, points/thread swept).
Throughput is plotted against the number of parallel walkers (work-items).

    python docs/make_benchmark_chart.py
-> docs/vram_cliff_rx6600.png
"""

import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

# ── measured data: (work-items in millions, Mkeys/s) ─────────────────────
# threads=64, blocks=4096, points/thread = 80..160  ->  N = 64*4096*pts
N = [20.97, 23.07, 25.17, 27.26, 29.36, 30.41, 31.46, 32.51, 33.55, 41.94, 50.33]
MK = [359.3, 370.1, 382.6, 390.1, 399.3, 402.6, 406.4, 385.9, 353.9, 109.7, 85.0]

PEAK_I    = 6     # 31.46M -> 406.4  (peak)
DEFAULT_I = 4     # 29.36M -> 399.3  (shipped default, safe side of the cliff)

# ── style ────────────────────────────────────────────────────────────────
BG, FG, GRID = "#0d1117", "#e6edf3", "#30363d"
LINE, PEAK, CLIFF, SAFE = "#2f81f7", "#3fb950", "#f85149", "#d29922"

fig, ax = plt.subplots(figsize=(11, 6.2), dpi=200)
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)

# cliff danger zone
ax.axvspan(34, 52, color=CLIFF, alpha=0.10, zorder=0)
ax.text(43, 150, "VRAM CLIFF\nworking set blows the\ncache budget  ->  ~4x collapse",
        color=CLIFF, fontsize=11, ha="center", va="center", fontweight="bold")

# main curve
ax.plot(N, MK, "-o", color=LINE, lw=2.6, markersize=7,
        markerfacecolor=BG, markeredgecolor=LINE, markeredgewidth=2, zorder=3)

# peak marker
ax.scatter([N[PEAK_I]], [MK[PEAK_I]], s=240, color=PEAK, zorder=5,
           edgecolor=BG, linewidth=2)
ax.annotate("PEAK  406 Mkeys/s\n@ 31.5M walkers",
            xy=(N[PEAK_I], MK[PEAK_I]), xytext=(N[PEAK_I] - 9, MK[PEAK_I] + 18),
            color=PEAK, fontsize=11.5, fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=PEAK, lw=1.8))

# shipped default marker
ax.scatter([N[DEFAULT_I]], [MK[DEFAULT_I]], s=170, color=SAFE, zorder=5,
           edgecolor=BG, linewidth=2)
ax.annotate("shipped default 399 Mkeys/s\n(safe side, +12% vs old default)",
            xy=(N[DEFAULT_I], MK[DEFAULT_I]), xytext=(N[DEFAULT_I] - 0.5, MK[DEFAULT_I] - 95),
            color=SAFE, fontsize=10.5, ha="center",
            arrowprops=dict(arrowstyle="->", color=SAFE, lw=1.6))

# old default (past the peak, on the downslope)
ax.annotate("old default (128 pts/thread):\n354 Mkeys/s on the downslope",
            xy=(N[8], MK[8]), xytext=(N[8] + 1.0, MK[8] - 120),
            color="#8b949e", fontsize=10, ha="center",
            arrowprops=dict(arrowstyle="->", color="#8b949e", lw=1.4))

# ── labels / cosmetics ────────────────────────────────────────────────────
ax.set_title("The VRAM performance cliff — AMD RX 6600",
             color=FG, fontsize=18, fontweight="bold", pad=16, loc="left")
ax.text(0.0, 1.018,
        "Custom OpenCL secp256k1 engine  •  GPU throughput vs. parallel walkers in flight",
        transform=ax.transAxes, color="#8b949e", fontsize=11.5)

ax.set_xlabel("Parallel walkers in flight  (millions of GPU work-items)",
              color=FG, fontsize=12.5, labelpad=10)
ax.set_ylabel("Throughput  (Mkeys / second)", color=FG, fontsize=12.5, labelpad=10)

ax.set_xlim(19, 52)
ax.set_ylim(60, 440)
ax.grid(True, color=GRID, lw=0.8, alpha=0.7)
for s in ax.spines.values():
    s.set_color(GRID)
ax.tick_params(colors="#8b949e", labelsize=10.5)
ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:.0f}M"))

fig.text(0.99, 0.015, "github.com/RakinSV/Bitcoin-Puzzle-AllAttacks-Analytics",
         color="#6e7681", fontsize=9.5, ha="right")

plt.tight_layout(rect=(0, 0.02, 1, 0.96))
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vram_cliff_rx6600.png")
fig.savefig(out, facecolor=BG, bbox_inches="tight")
print("saved:", out)
