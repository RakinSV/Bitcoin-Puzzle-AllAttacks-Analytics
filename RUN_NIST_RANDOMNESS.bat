@echo off
chcp 65001 > nul
title Bitcoin Puzzle - NIST Randomness Tests

echo ============================================================
echo  NIST-STYLE RANDOMNESS BATTERY
echo ============================================================
echo.
echo  rng_analysis.py gives descriptive stats. This runs the formal
echo  NIST SP 800-22 hypothesis tests on the 70 known keys and emits
echo  real p-values:
echo.
echo    Monobit, Runs, Poker/block-frequency, Autocorrelation
echo    + position uniformity (chi-square) and runs-about-median
echo.
echo    p >= 0.01 -> random (no RNG shortcut, brute force is correct)
echo    p <  0.01 -> statistically significant bias worth exploiting
echo.
echo  Offline, no internet, ~1 second.
echo ============================================================
echo.

cd /d "%~dp0"
python analysis/nist_randomness.py

echo.
pause
