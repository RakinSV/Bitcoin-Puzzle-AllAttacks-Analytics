@echo off
chcp 65001 > nul
title Bitcoin Puzzle - Ghost-Solved Check

echo ============================================================
echo  GHOST-SOLVED PUZZLE CHECK
echo ============================================================
echo.
echo  Puzzles #75,80,85,90,95,100,105,110,125,130 are commonly
echo  listed as "solved". This re-verifies each one DIRECTLY on the
echo  blockchain. Blockchain truth beats any website:
echo.
echo    balance == 0  -> genuinely solved (spent)
echo    balance  > 0  -> STILL CLAIMABLE (the prize was never taken)
echo    spend-from exists -> PUBKEY exposed -> Kangaroo-able
echo.
echo  Best case: a puzzle everyone thinks is done that still holds
echo  BTC and already has a public pubkey.
echo ============================================================
echo.

cd /d "%~dp0"
python analysis/ghost_solved_check.py

echo.
echo  Any pubkey_puzzleNN.txt files written above are ready to feed
echo  into: python main.py --puzzle NN --mode kangaroo --pubkey ...
echo.
pause
