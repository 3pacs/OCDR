@echo off
echo ============================================
echo   OCDR Web Application Build Script
echo ============================================
echo.
echo Installing dependencies...
pip install pyinstaller flask flask-sqlalchemy python-dotenv
echo.
echo Building ocdr_web.exe...
pyinstaller ocdr_web.spec --clean
echo.
echo ============================================
if exist dist\ocdr_web.exe (
    echo   BUILD SUCCESSFUL
    echo   Output: dist\ocdr_web.exe
    echo.
    echo   To use:
    echo     1. Copy dist\ocdr_web.exe to your working folder
    echo     2. Run: ocdr_web.exe
    echo     3. Open browser to http://localhost:5000
    echo     4. Health check: http://localhost:5000/health
) else (
    echo   BUILD FAILED — check errors above
)
echo ============================================
pause
