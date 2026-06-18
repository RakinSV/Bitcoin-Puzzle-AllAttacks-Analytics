@echo off
chcp 65001 > nul
title Bitcoin Puzzle - Deep Creator Fingerprint

echo ============================================================
echo  DEEP CREATOR/SOLVER FINGERPRINT (common-input-ownership)
echo ============================================================
echo.
echo  The normal fingerprint clusters by destination-address reuse
echo  and fee/timing patterns (heuristics). This --deep pass adds the
echo  STRONGEST evidence: common-input-ownership. If two puzzle keys
echo  were ever co-spent as inputs in the same later transaction, the
echo  same person provably controls both - that is cryptographic
echo  proof, not a guess.
echo.
echo  Needs internet. ~70 extra API calls, a couple of minutes.
echo ============================================================
echo.

cd /d "%~dp0"
python analysis/creator_fingerprint.py --deep

echo.
pause
