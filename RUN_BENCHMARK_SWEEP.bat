@echo off
chcp 65001 > nul
title GPU Parameter Sweep - Find Fastest Config

echo ============================================================
echo  GPU PARAMETER SWEEP
echo  Tests threads x blocks x points_per_thread combinations
echo  to find the fastest config for YOUR specific GPU.
echo.
echo  ~27 configs x ~3-5 sec each = 2-4 minutes total.
echo  Methodology: baseline -> grid -> statistical confidence (std%%, p95)
echo  -> pick winner backed by data, not guesses.
echo ============================================================
echo.
echo  !!! Close other GPU-using windows first (lottery/monitor) !!!
echo.
pause

cd /d "%~dp0"
python main.py --bench-sweep

echo.
echo  Copy the "To use:" command above into START_LOTTERY.bat
echo  if it beats your current speed.
echo.
pause
