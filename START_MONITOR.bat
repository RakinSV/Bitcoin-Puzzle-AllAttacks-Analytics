@echo off
chcp 65001 > nul

set PUZZLE_NUM=%1
if "%PUZZLE_NUM%"=="" set PUZZLE_NUM=71

title Bitcoin Puzzle #%PUZZLE_NUM% - Monitor + Kangaroo Prewarm

echo ============================================================
echo  Bitcoin Puzzle #%PUZZLE_NUM% - MONITOR + PREWARM
echo  - Kangaroo engine: prewarm (ready to fire instantly)
echo  - Tame DPs:        tame_dps_puzzle%PUZZLE_NUM%.pkl (loaded if exists)
echo  - Blockchain:      polling every 30s
echo  - Brute force:     OFF
echo.
echo  Usage: START_MONITOR.bat [puzzle_number]   (default 71)
echo ============================================================
echo.

cd /d "%~dp0"
python run_all.py --puzzle %PUZZLE_NUM% --no-brute --interval 30

pause
