@echo off
:: Re-enable AMD RX 6600 after TDR crash (Code 22 = disabled)
:: Must run as Administrator

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator rights...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo ============================================================
echo  FIX: Re-enabling AMD Radeon RX 6600 (Code 22)
echo ============================================================
echo.

set HWID=PCI\VEN_1002^&DEV_73FF^&SUBSYS_2413148C^&REV_C7\6^&2106E7BC^&0^&00000019

echo [1] Enabling GPU via pnputil...
pnputil /enable-device "%HWID%"
echo.

echo [2] Checking status...
powershell -Command "$g = Get-WmiObject Win32_VideoController | Where-Object {$_.Name -match 'AMD Radeon RX 6600'}; Write-Host ('Status: ' + $g.Status + '  Code: ' + $g.ConfigManagerErrorCode)"
echo.

echo [3] Restarting display driver (Win+Ctrl+Shift+B equivalent)...
powershell -Command "pnputil /restart-device '%HWID%'"
echo.

echo [4] Final check...
powershell -Command "
    Start-Sleep -Seconds 2
    $g = Get-WmiObject Win32_VideoController | Where-Object {$_.Name -match 'AMD Radeon RX 6600'}
    Write-Host ('GPU Status: ' + $g.Status + '  ErrorCode: ' + $g.ConfigManagerErrorCode)
    Add-Type -AssemblyName System.Windows.Forms
    $screens = [System.Windows.Forms.Screen]::AllScreens
    Write-Host ('Active monitors: ' + $screens.Count)
    foreach ($s in $screens) { Write-Host ('  ' + $s.DeviceName + ' Primary=' + $s.Primary + ' ' + $s.Bounds.Width + 'x' + $s.Bounds.Height) }
"
echo.
echo Done! If second monitor still missing - try unplugging and replugging the cable.
echo.
pause
