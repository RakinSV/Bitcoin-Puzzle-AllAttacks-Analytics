@echo off
chcp 65001 > nul
title Bitcoin Puzzle #71 - ALL SMART ATTACKS

echo.
echo +============================================================+
echo   BITCOIN PUZZLE #71 - SMART ATTACK SUITE
echo   "Work smarter, not harder"
echo +============================================================+
echo.
echo  Three strategies to win WITHOUT brute force:
echo.
echo  [1] NONCE ATTACK      - recover creator's master key
echo      If creator reused ECDSA nonce -> key in milliseconds
echo      File: RUN_NONCE_ATTACK.bat
echo.
echo  [2] PATTERN ANALYSIS  - find mathematical key pattern
echo      Tests: Python random, SHA256, BIP32, linear/geometric
echo      File: RUN_PATTERN_ANALYSIS.bat
echo.
echo  [3] PUBKEY PATTERN    - analyze EC point structure
echo      Collects pubkeys of solved puzzles from blockchain
echo      Checks for linear/multiplicative/doubling patterns
echo      File: RUN_PUBKEY_PATTERN.bat
echo.
echo  [4] BRAINWALLET       - dictionary attack on weak passphrases
echo      privkey = SHA256("bitcoin71") style guesses, validated
echo      against all 70 solved keys first
echo      File: RUN_BRAINWALLET_ATTACK.bat
echo.
echo  [5] MULTI-SNIPER      - watch ALL unsolved puzzles in mempool;
echo      grab a competitor's pubkey the instant they spend, then
echo      auto-fire Kangaroo to win the block race
echo      File: RUN_MULTI_SNIPER.bat
echo.
echo  [6] GHOST CHECK       - re-verify "solved" #75..130 on-chain;
echo      flags any still holding BTC and/or with an exposed pubkey
echo      File: RUN_GHOST_CHECK.bat
echo.
echo  [7] DEEP FINGERPRINT  - common-input-ownership proof of which
echo      keys share one owner   File: RUN_DEEP_FINGERPRINT.bat
echo.
echo  [8] NIST RANDOMNESS   - formal p-value tests on known keys
echo      File: RUN_NIST_RANDOMNESS.bat
echo.
echo +============================================================+
echo.
echo  QUICK RESULTS (no internet needed, ~10 seconds):
echo.
echo  --- Pattern Analysis (offline, using 50 known keys) ---
python analysis/rng_analysis.py --quick 2>nul
echo.
python analysis/bip32_analysis.py 2>nul
echo.
echo  +----------------------------------------------------------+
echo  Press any key to launch INTERACTIVE MENU...
echo  +----------------------------------------------------------+
pause > nul

:MENU
cls
echo.
echo  SMART ATTACK MENU
echo  ==================
echo.
echo  [1]  Nonce Attack     (check creator's ECDSA signatures)
echo  [2]  Pattern Analysis (RNG / BIP32 / hash schemes)
echo  [3]  Pubkey Pattern   (EC point pattern, needs internet)
echo  [4]  Brainwallet      (dictionary attack, near-zero cost)
echo  [5]  Multi-Sniper     (watch ALL unsolved, snipe pubkeys in mempool)
echo  [6]  Ghost Check      (re-verify "solved" #75..130 on-chain)
echo  [7]  Deep Fingerprint (common-input-ownership proof of ownership)
echo  [8]  NIST Randomness  (formal p-value tests on known keys)
echo  [9]  Choose Puzzle    (pick any unsolved target + GPU lottery)
echo  [10] GPU Lottery #71  (classic brute force, default target)
echo  [11] Bench Sweep      (find fastest GPU params for your card)
echo  [A]  ALL QUICK        (run offline analyses automatically)
echo  [Q]  Quit
echo.
set /p CHOICE="Choose [1-11/A/Q]: "

if /i "%CHOICE%"=="1" call RUN_NONCE_ATTACK.bat & goto MENU
if /i "%CHOICE%"=="2" call RUN_PATTERN_ANALYSIS.bat & goto MENU
if /i "%CHOICE%"=="3" call RUN_PUBKEY_PATTERN.bat & goto MENU
if /i "%CHOICE%"=="4" call RUN_BRAINWALLET_ATTACK.bat & goto MENU
if /i "%CHOICE%"=="5" call RUN_MULTI_SNIPER.bat & goto MENU
if /i "%CHOICE%"=="6" call RUN_GHOST_CHECK.bat & goto MENU
if /i "%CHOICE%"=="7" call RUN_DEEP_FINGERPRINT.bat & goto MENU
if /i "%CHOICE%"=="8" call RUN_NIST_RANDOMNESS.bat & goto MENU
if /i "%CHOICE%"=="9" call CHOOSE_PUZZLE.bat & goto MENU
if /i "%CHOICE%"=="10" call START_LOTTERY.bat & goto MENU
if /i "%CHOICE%"=="11" call RUN_BENCHMARK_SWEEP.bat & goto MENU
if /i "%CHOICE%"=="a" goto QUICKALL
if /i "%CHOICE%"=="q" goto END
echo  Invalid choice.
goto MENU

:QUICKALL
echo.
echo  Running all quick attacks (no internet)...
echo.
echo  === [1/4] RNG Analysis ===
python analysis/rng_analysis.py --quick
echo.
echo  === [2/4] BIP32 Pattern ===
python analysis/bip32_analysis.py --test-all
echo.
echo  === [3/4] Priority Segments ===
python analysis/rng_analysis.py --segments
echo.
echo  === [4/5] Brainwallet Dictionary ===
python analysis/brainwallet_attack.py --target 71
echo.
echo  === [5/5] NIST Randomness Battery ===
python analysis/nist_randomness.py --quiet
echo.
echo  === DONE ===
echo.
if exist PREDICTED_KEY_71.txt (
    echo  *** PREDICTED_KEY_71.txt FOUND! OPEN IT NOW! ***
    type PREDICTED_KEY_71.txt
) else (
    echo  No shortcut found. Creator used real randomness.
    echo  Keep GPU lottery running: START_LOTTERY.bat
)
echo.
pause
goto MENU

:END
echo  Goodbye!
