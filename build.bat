@echo off
echo ============================================
echo   OCDR Build Script
echo ============================================
echo.
echo Installing PyInstaller...
pip install pyinstaller
echo.
echo Building ocdr.exe...
pyinstaller ocdr.spec --clean
echo.
echo ============================================
if exist dist\ocdr.exe (
    echo   BUILD SUCCESSFUL
    echo   Output: dist\ocdr.exe
    echo.
    echo   To use:
    echo     1. Copy dist\ocdr.exe to your working folder
    echo     2. Place OCMRI.xlsx in a data\ subfolder next to it
    echo     3. Run: ocdr.exe --help
) else (
    echo   BUILD FAILED — check errors above
)
echo ============================================
pause
