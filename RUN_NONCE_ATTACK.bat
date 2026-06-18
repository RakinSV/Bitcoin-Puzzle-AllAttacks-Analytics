@echo off
chcp 65001 > nul
title Bitcoin Puzzle #71 - NONCE ATTACK (Creator Key Recovery)

echo ============================================================
echo  HACKER ATTACK #1: ECDSA Nonce Reuse
echo  Target: Puzzle Creator's master key
echo ============================================================
echo.
echo  IDEA: When the creator funded all 256 puzzle addresses,
echo  they signed transactions with their private key.
echo  If they reused a random nonce (k) in ANY two signatures:
echo    -> Private key recoverable in milliseconds (one formula!)
echo    -> If it's a BIP32 master key -> all 256 puzzle keys
echo.
echo  This is INSTANT if the creator made this mistake.
echo  Known exploits: PS3 hack, Android Bitcoin wallet 2013.
echo.
echo ============================================================
echo  STEP 1: Quick check (funding TX only, ~5 sec)
echo ============================================================
echo.
python analysis/nonce_attack.py --quick
echo.
echo ============================================================
echo  STEP 2: Deep analysis (creator addresses, depth=2)
echo  This fetches ~100 transactions - takes 1-3 minutes
echo ============================================================
echo.
set /p DEEP="Run deep analysis? (y/n): "
if /i "%DEEP%"=="y" (
    echo.
    echo  Running deep nonce analysis...
    echo  Results saved to: nonce_sigs.json
    echo.
    python analysis/nonce_attack.py --depth 2 --max-tx 150 --save nonce_sigs.json
    echo.
    echo ============================================================
    echo  STEP 3: LLL lattice attack (biased nonces)
    echo  Even if nonces not reused - check for BIAS
    echo ============================================================
    echo.
    python analysis/nonce_attack.py --load nonce_sigs.json --lll --lll-bits 8
)
echo.
echo  If CREATOR_KEY_FOUND.txt exists - run BIP32 analysis next:
echo    python analysis/bip32_analysis.py --master-key 0x...
echo.
if exist CREATOR_KEY_FOUND.txt (
    echo  *** CREATOR_KEY_FOUND.txt EXISTS! ***
    echo  Contents:
    type CREATOR_KEY_FOUND.txt
)
echo.
pause
