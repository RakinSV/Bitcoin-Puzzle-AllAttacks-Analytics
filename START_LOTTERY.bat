@echo off
chcp 65001 > nul
title Bitcoin Puzzle - GPU Lottery (OPTIMIZED)

cd /d "%~dp0"

echo ============================================================
echo  BITCOIN PUZZLE - GPU LOTTERY  [OPTIMIZED for AMD RX 6600]
echo ============================================================
echo.
echo  Optimizations active:
echo    - GPU params 64/4096/112 = ~399 Mkeys/s (re-benched, off VRAM cliff)
echo    - multiplyStep: N iterations (was 256) = 3.6x faster init
echo    - jump-every: 1000 steps = ~1%% reinit overhead (was 30%%)
echo    - Crash-safe: key saved to disk IMMEDIATELY when found
echo    - Pool-avoid: skips the prefix btcpuzzle.info pool already swept
echo.
echo  !!! DO NOT run START_MONITOR alongside this (two OpenCL contexts =
echo  !!! GPU sharing / overheating / TDR crash).
echo ============================================================
echo.
echo  Which puzzle do you want to attack?
echo    - #71-80 are realistically reachable on a consumer GPU.
echo    - Above that the keyspace doubles every step (lottery odds).
echo    - Run CHECK_PUZZLE_STATUS.bat to see what is still unsolved.
echo.

set /p PUZZLE_NUM="Enter puzzle number [default 71, Enter to keep]: "
if "%PUZZLE_NUM%"=="" set PUZZLE_NUM=71
if /i "%PUZZLE_NUM%"=="Q" goto END

set /p JUMP_EVERY="Steps between random jumps [default 1000, Enter to keep]: "
if "%JUMP_EVERY%"=="" set JUMP_EVERY=1000

echo.
echo ============================================================
echo  Launching GPU lottery on puzzle #%PUZZLE_NUM%
echo  jump-every=%JUMP_EVERY%  pool-avoid=on
echo  Key (if found) is saved to FOUND_KEY.txt + Desktop immediately.
echo ============================================================
echo.

python main.py --puzzle %PUZZLE_NUM% --mode gpu --pure-random --jump-every %JUMP_EVERY% --pool-avoid

:END
echo.
pause
