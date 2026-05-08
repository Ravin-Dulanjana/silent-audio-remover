@echo off
setlocal

set ROOT_DIR=%~dp0..
set APP_NAME=Silence Remover
set BUILD_DIR=%ROOT_DIR%\build\pyinstaller-work
set DIST_DIR=%ROOT_DIR%\dist
set CACHE_DIR=%ROOT_DIR%\build\pyinstaller-cache

cd /d "%ROOT_DIR%"
if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"
if not exist "%CACHE_DIR%" mkdir "%CACHE_DIR%"

echo Building Windows standalone app...
echo Note: this Windows packaging path is included for users, but it has not been tested by the project author yet.

set PYINSTALLER_CONFIG_DIR=%CACHE_DIR%

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --workpath "%BUILD_DIR%" ^
  --distpath "%DIST_DIR%" ^
  --name "%APP_NAME%" ^
  --add-data "LICENSE;." ^
  app.py

echo.
echo Windows app build output:
echo   %ROOT_DIR%\dist\%APP_NAME%\

endlocal
