@echo off
chcp 65001 > nul
title Bitcoin Puzzle Status Checker

echo ============================================================
echo  BITCOIN PUZZLE STATUS CHECKER
echo ============================================================
echo.
echo  Checks the REAL blockchain state (blockstream.info) for all
echo  known puzzles #1-150 - NOT just what btcpuzzle.info claims.
echo  (We caught puzzle #75 mislabeled as "solved" this way - its
echo   7.6 BTC is still sitting there unspent!)
echo.
echo  First run checks ~150 addresses (~40-60 sec). After that,
echo  results are cached for 6 hours.
echo ============================================================
echo.

cd /d "%~dp0"

set /p REFRESH="Force refresh from blockchain now? (y/n, default n): "
if /i "%REFRESH%"=="y" (
    python analysis/puzzle_status.py --refresh
) else (
    python analysis/puzzle_status.py
)

echo.
echo ============================================================
echo  To attack one of the unsolved puzzles above, run:
echo    CHOOSE_PUZZLE.bat
echo ============================================================
echo.
pause
