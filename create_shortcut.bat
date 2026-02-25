@echo off
:: Creates an OCDR desktop shortcut with icon
:: Run this once: double-click create_shortcut.bat

set "SCRIPT_DIR=%~dp0"
set "SHORTCUT=%USERPROFILE%\Desktop\OCDR Launcher.lnk"
set "TARGET=%SCRIPT_DIR%start_ocdr.bat"
set "ICON=%SCRIPT_DIR%static\ocdr.ico"
set "WORKDIR=%SCRIPT_DIR%"

:: Generate the icon first
python "%SCRIPT_DIR%generate_icon.py"

:: Create shortcut via PowerShell
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$s = $ws.CreateShortcut('%SHORTCUT%');" ^
  "$s.TargetPath = '%TARGET%';" ^
  "$s.WorkingDirectory = '%WORKDIR%';" ^
  "$s.Description = 'OCDR Billing Reconciliation System';" ^
  "if (Test-Path '%ICON%') { $s.IconLocation = '%ICON%,0' };" ^
  "$s.WindowStyle = 1;" ^
  "$s.Save();"

echo.
echo Desktop shortcut created: %SHORTCUT%
echo.
pause
