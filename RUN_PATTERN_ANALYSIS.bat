@echo off
chcp 65001 > nul
title Bitcoin Puzzle #71 - PATTERN ANALYSIS (Math Attack)

echo ============================================================
echo  HACKER ATTACK #2: Key Generation Pattern Analysis
echo ============================================================
echo.
echo  IDEA: The 256 puzzle keys were NOT generated randomly.
echo  If the creator used a predictable algorithm:
echo    -> Python random.Random(seed) -> seed in [0..1M] = found instantly
echo    -> SHA256("puzzle71") or similar -> found in milliseconds
echo    -> BIP32 derivation m/0/70 -> recoverable from pubkeys
echo    -> Linear/geometric sequence k_n = a*k_(n-1)+b -> math solve
echo.
echo  50 known keys (#1-#50) give us enough to VERIFY any pattern.
echo ============================================================
echo.

echo  [1/4] RNG ANALYSIS - checking 50 known keys for patterns...
echo        Tests: Python random, SHA256, MD5, HMAC schemes
echo.
python analysis/rng_analysis.py --quick
echo.
echo  ============================================================
echo  [2/4] POSITION STATISTICS - where in range are known keys?
echo        If mean position != 0.5 -> biased search zone
echo  ============================================================
echo.
python analysis/rng_analysis.py --predict
echo.
echo  ============================================================
echo  [3/4] BIP32 DERIVATION PATTERN
echo        Tests linear, geometric, hash-based key sequences
echo  ============================================================
echo.
python analysis/bip32_analysis.py --test-all
echo.
echo  ============================================================
echo  [4/4] PRIORITY SEGMENTS for GPU brute force
echo        Best starting points based on position statistics
echo  ============================================================
echo.
python analysis/rng_analysis.py --segments
echo.
echo ============================================================
echo  RESULT SUMMARY
echo ============================================================
echo.
if exist PREDICTED_KEY_71.txt (
    echo  *** PREDICTED_KEY_71.txt FOUND! ***
    type PREDICTED_KEY_71.txt
) else (
    echo  No exact key predicted (creator used real randomness).
    echo  But priority zones identified above!
    echo.
    echo  NEXT STEPS:
    echo  1. Run pubkey pattern analysis (needs internet):
    echo     python analysis/pubkey_pattern.py --collect
    echo  2. Run nonce attack:
    echo     RUN_NONCE_ATTACK.bat
    echo  3. Or just keep the GPU lottery running:
    echo     START_LOTTERY.bat
)
echo.
pause
