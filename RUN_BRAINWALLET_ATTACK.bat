@echo off
chcp 65001 > nul
title Bitcoin Puzzle - Brainwallet/Dictionary Attack

echo ============================================================
echo  HACKER ATTACK #4: Brainwallet / Dictionary Attack
echo ============================================================
echo.
echo  IDEA: Early Bitcoin "brainwallets" derived private keys directly
echo  from a memorable passphrase: privkey = SHA256(passphrase)
echo  This was common practice in 2013-2015 - exactly this puzzle's era.
echo.
echo  STEP 1: Test phrases against all 70 SOLVED keys (proves the method
echo           was used at all - if it matches a solved key, we know the
echo           exact phrase pattern to extend to unsolved puzzles)
echo  STEP 2: Test the same phrases directly against your target puzzle
echo.
echo  Cost: a few seconds. Covers thousands of weak-passphrase keys that
echo  the GPU lottery would take forever to randomly stumble onto.
echo ============================================================
echo.

cd /d "%~dp0"

set /p PUZZLE_NUM="Target puzzle number (default 71): "
if "%PUZZLE_NUM%"=="" set PUZZLE_NUM=71

echo.
python analysis/brainwallet_attack.py --target %PUZZLE_NUM%

echo.
if exist BRAINWALLET_KEY_%PUZZLE_NUM%.txt (
    echo  *** BRAINWALLET_KEY_%PUZZLE_NUM%.txt FOUND! ***
    type BRAINWALLET_KEY_%PUZZLE_NUM%.txt
) else (
    echo  No match in the built-in wordlist. To try a bigger wordlist:
    echo    RUN_BRAINWALLET_ATTACK.bat  (then edit to add --wordlist your_file.txt)
)
echo.
pause
