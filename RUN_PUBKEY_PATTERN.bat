@echo off
chcp 65001 > nul
title Bitcoin Puzzle #71 - PUBKEY PATTERN (EC Point Analysis)

echo ============================================================
echo  HACKER ATTACK #3: EC Public Key Pattern Analysis
echo ============================================================
echo.
echo  IDEA: For solved puzzles 1-66, the public keys are VISIBLE
echo  on the blockchain (in spending transactions).
echo  If there is a mathematical pattern in the EC points:
echo.
echo    LINEAR:         K_n = K_{n-1} + c*G  (constant shift)
echo    MULTIPLICATIVE: K_n = r * K_{n-1}     (geometric)
echo    POWER-OF-2:     K_n = 2 * K_{n-1}     (doubling)
echo.
echo  Any of these -> predict K_71 -> run Kangaroo in minutes!
echo.
echo  This DOES NOT require knowing private keys!
echo  We only need the PUBLIC keys (visible on blockchain).
echo ============================================================
echo.
echo  Checking pip dependencies...
python -c "import requests" 2>nul
if errorlevel 1 (
    echo  Installing requests...
    pip install requests -q
)
echo.
echo  [1/2] Collecting pubkeys from blockchain...
echo        (fetching ~66 spending transactions, ~2-5 min)
echo        Results cached to: puzzle_pubkeys.json
echo.
python analysis/pubkey_pattern.py --collect --max-puzzles 66
echo.
echo  ============================================================
echo  [2/2] Pattern analysis complete - see output above
echo  ============================================================
echo.
if exist puzzle_pubkeys.json (
    echo  Pubkey cache: puzzle_pubkeys.json
    python -c "import json; d=json.load(open('puzzle_pubkeys.json')); print(f'  Collected: {len(d)} pubkeys')"
)
echo.
echo  If constant delta found above -> run Kangaroo on K_71:
echo    python main.py --kangaroo --pubkey X_COORD:Y_COORD
echo.
pause
