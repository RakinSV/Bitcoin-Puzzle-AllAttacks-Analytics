@echo off
chcp 65001 > nul
title Bitcoin Puzzle - FULL ANALYSIS (all checks, no menu)

cd /d "%~dp0"

echo +============================================================+
echo   FULL ANALYSIS RUN - every check, one shot, no menu
echo   Offline checks first (instant), then on-chain checks.
echo.
echo   To ALSO save everything to a file, run it like this:
echo      RUN_FULL_ANALYSIS.bat ^> report.txt 2^>^&1
echo +============================================================+

echo.
echo ############################################################
echo #  PART 1 - OFFLINE ANALYSES (no internet needed)
echo ############################################################

echo.
echo ===== [1/9] RNG pattern (quick) =====
python analysis/rng_analysis.py --quick

echo.
echo ===== [2/9] RNG prediction attempt for #71 =====
python analysis/rng_analysis.py --predict

echo.
echo ===== [3/9] Priority segments =====
python analysis/rng_analysis.py --segments

echo.
echo ===== [4/9] BIP32 / HD-wallet pattern =====
python analysis/bip32_analysis.py --test-all

echo.
echo ===== [5/9] Brainwallet dictionary (vs solved + #71) =====
python analysis/brainwallet_attack.py --target 71

echo.
echo ===== [6/9] NIST randomness battery =====
python analysis/nist_randomness.py

echo.
echo ############################################################
echo #  PART 2 - ON-CHAIN ANALYSES (needs internet)
echo ############################################################

echo.
echo ===== [7/9] Live puzzle status (unsolved + attack priority) =====
python analysis/puzzle_status.py --unsolved

echo.
echo ===== [8/9] Ghost-solved check (#75..130 re-verified on-chain) =====
python analysis/ghost_solved_check.py

echo.
echo ===== [9/9] Deep creator fingerprint (common-input-ownership) =====
python analysis/creator_fingerprint.py --deep

echo.
echo ############################################################
echo #  RESULT SUMMARY
echo ############################################################
echo.
if exist PREDICTED_KEY_71.txt (
    echo  *** PREDICTED_KEY_71.txt FOUND - RNG shortcut hit! ***
    type PREDICTED_KEY_71.txt
) else (
    echo  [ ] No RNG/predicted key for #71 (expected - keys are random).
)
echo.
if exist BRAINWALLET_KEY_71.txt (
    echo  *** BRAINWALLET_KEY_71.txt FOUND - weak passphrase hit! ***
    type BRAINWALLET_KEY_71.txt
) else (
    echo  [ ] No brainwallet match for #71.
)
echo.
echo  Exposed-pubkey files on disk (ready for Kangaroo):
dir /b pubkey_puzzle*.txt 2>nul
if errorlevel 1 echo    (none yet)
echo.
echo  NEXT STEP: nothing above = no shortcut, run the GPU lottery:
echo     START_LOTTERY.bat        (puzzle #71)
echo     CHOOSE_PUZZLE.bat        (any unsolved target)
echo  Or watch for competitors' spends to snipe pubkeys live:
echo     RUN_MULTI_SNIPER.bat
echo.
echo  === FULL ANALYSIS COMPLETE ===
echo.
pause
