@echo off
chcp 65001 > nul
title Bitcoin Puzzle - Desktop App
cd /d "%~dp0"

REM Launch the PySide6 desktop GUI (dev mode).
REM Needs:  pip install PySide6 pyopencl numpy requests
python app_entry.py

if errorlevel 1 (
    echo.
    echo  App exited with an error. Missing deps? Run:
    echo     pip install PySide6 pyopencl numpy requests
    echo.
    pause
)
