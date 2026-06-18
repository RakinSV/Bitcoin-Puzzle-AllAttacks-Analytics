@echo off
chcp 65001 > nul
title Bitcoin Puzzle - Kangaroo Solver

echo ============================================================
echo  Bitcoin Puzzle - KANGAROO SOLVER (MANUAL)
echo  Use this when you have the pubkey (after puzzle is spent)
echo ============================================================
echo.

cd /d "%~dp0"

if "%1"=="" (
    echo Usage: RUN_KANGAROO_MANUAL.bat ^<pubkey_hex^> [puzzle_number]
    echo.
    echo Example:
    echo   RUN_KANGAROO_MANUAL.bat 02aabbcc... 71
    echo.

    set /p PUBKEY="Paste pubkey hex here: "
    set /p PUZZLE_NUM="Puzzle number (default 71): "
) else (
    set PUBKEY=%1
    set PUZZLE_NUM=%2
)

if "%PUZZLE_NUM%"=="" set PUZZLE_NUM=71

echo.
echo Running Kangaroo for puzzle #%PUZZLE_NUM%...
echo Pubkey: %PUBKEY%
echo.

python main.py --puzzle %PUZZLE_NUM% --mode kangaroo ^
               --pubkey %PUBKEY% ^
               --n-tame 16384 --n-wild 16384 --dp-bits 15

pause
