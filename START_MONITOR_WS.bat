@echo off
chcp 65001 > nul

set PUZZLE_NUM=%1
if "%PUZZLE_NUM%"=="" set PUZZLE_NUM=71

title Bitcoin Puzzle #%PUZZLE_NUM% - Monitor WebSocket (INSTANT detection)

echo ============================================================
echo  Bitcoin Puzzle #%PUZZLE_NUM% - WEBSOCKET MONITOR (INSTANT)
echo  - Detection: < 1 second via mempool.space WebSocket
echo  - Kangaroo engine: prewarm (ready to fire instantly)
echo  - Requires: pip install websockets
echo.
echo  Usage: START_MONITOR_WS.bat [puzzle_number]   (default 71)
echo ============================================================
echo.

cd /d "%~dp0"

python -c "import websockets" 2>nul
if errorlevel 1 (
    echo [!] websockets not installed. Installing...
    pip install websockets
    echo.
)

python run_all.py --puzzle %PUZZLE_NUM% --no-brute --websocket

pause
