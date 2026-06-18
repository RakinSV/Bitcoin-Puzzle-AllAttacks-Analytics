@echo off
chcp 65001 > nul
title Bitcoin Puzzle - Multi-Puzzle Mempool Sniper

echo ============================================================
echo  MULTI-PUZZLE MEMPOOL SNIPER
echo ============================================================
echo.
echo  monitor.py watches ONE address. This watches ALL unsolved
echo  puzzles at once. The moment a competitor broadcasts a spend,
echo  their PUBLIC KEY appears in the mempool - this grabs it and
echo  (with autosolve) fires a Kangaroo GPU solver instantly on any
echo  puzzle small enough to crack before the next block.
echo.
echo  First valid confirmed tx wins. This is the race-to-claim edge.
echo ============================================================
echo.

cd /d "%~dp0"

set /p AUTO="Auto-launch Kangaroo on an in-range hit? (y/N): "
set /p MAXBITS="Auto-solve gate - max puzzle bits (default 75): "
if "%MAXBITS%"=="" set MAXBITS=75

echo.
echo  Starting sniper (Ctrl+C to stop)...
echo.
if /i "%AUTO%"=="y" (
    python multi_sniper.py --autosolve --max-bits %MAXBITS% --refresh-status
) else (
    python multi_sniper.py --max-bits %MAXBITS% --refresh-status
)

echo.
pause
