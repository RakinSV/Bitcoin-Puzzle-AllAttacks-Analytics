@echo off
chcp 65001 > nul
title Bitcoin Puzzle - RUN EVERYTHING (all analyses, all puzzles, to files)

cd /d "%~dp0"

echo ============================================================
echo  RUN EVERYTHING - every analysis and attack (except the GPU
echo  lottery), across ALL 150 puzzles, written straight to files.
echo.
echo  No parameters needed. Offline checks run first (instant),
echo  on-chain checks last (needs internet). A network hiccup on
echo  one check never aborts the batch.
echo.
echo  Results -> reports\<timestamp>\
echo     00_SUMMARY.txt        verdict + any hits, read this first
echo     global\*.txt          analyses spanning all keys/puzzles
echo     per_puzzle\*.txt       per-target analyses, all puzzles
echo ============================================================
echo.

python run_all_analyses.py

echo.
echo  Done. Open the newest folder under  reports\  and start with
echo  00_SUMMARY.txt.
echo.
pause
