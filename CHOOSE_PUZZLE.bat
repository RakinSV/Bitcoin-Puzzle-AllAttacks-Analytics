@echo off
chcp 65001 > nul
title Bitcoin Puzzle - Choose Target

cd /d "%~dp0"

echo ============================================================
echo  BITCOIN PUZZLE - CHOOSE YOUR TARGET
echo ============================================================
echo.
echo  Showing unsolved puzzles (checked against live blockchain,
echo  cached up to 6h - run CHECK_PUZZLE_STATUS.bat to force refresh).
echo ============================================================
echo.

python analysis/puzzle_status.py --unsolved --max 100

echo.
echo ============================================================
echo  NOTE: only #71-90 or so are realistically attackable with a
echo  consumer GPU. Above that, the keyspace doubles every step and
echo  the lottery odds become astronomically small - but it's your
echo  call.
echo.
echo  !!! DO NOT run START_MONITOR / another lottery instance at
echo  !!! the same time - two OpenCL contexts share the GPU and can
echo  !!! cause overheating/TDR crashes.
echo ============================================================
echo.

set /p PUZZLE_NUM="Enter puzzle number to attack (or Q to quit): "
if /i "%PUZZLE_NUM%"=="Q" goto END
if "%PUZZLE_NUM%"=="" goto END

set /p JUMP_EVERY="Steps between random jumps (default 1000, press Enter to keep): "
if "%JUMP_EVERY%"=="" set JUMP_EVERY=1000

echo.
echo ============================================================
echo  Launching lottery on puzzle #%PUZZLE_NUM%
echo  jump-every=%JUMP_EVERY%  pool-avoid=on
echo  Key (if found) saved to FOUND_KEY.txt + Desktop immediately.
echo ============================================================
echo.

python main.py --puzzle %PUZZLE_NUM% --mode gpu --pure-random --jump-every %JUMP_EVERY% --pool-avoid

:END
pause
