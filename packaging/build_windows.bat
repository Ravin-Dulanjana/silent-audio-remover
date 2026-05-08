@echo off
setlocal

set ROOT_DIR=%~dp0..
set APP_NAME=Silence Remover
set APP_VERSION_FILE=%ROOT_DIR%\packaging\version.txt
set BUILD_DIR=%ROOT_DIR%\build\pyinstaller-work
set DIST_DIR=%ROOT_DIR%\dist
set CACHE_DIR=%ROOT_DIR%\build\pyinstaller-cache
set ASSET_DIR=%ROOT_DIR%\build\assets
set ICON_PATH=%ASSET_DIR%\silence_remover.ico
set VERSION_INFO=%ASSET_DIR%\windows_version_info.txt

cd /d "%ROOT_DIR%"
if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"
if not exist "%CACHE_DIR%" mkdir "%CACHE_DIR%"
if not exist "%ASSET_DIR%" mkdir "%ASSET_DIR%"

set /p APP_VERSION=<"%APP_VERSION_FILE%"

echo Building Windows standalone app...
echo Note: this Windows packaging path is included for users, but it has not been tested by the project author yet.

set PYINSTALLER_CONFIG_DIR=%CACHE_DIR%

python packaging\generate_icons.py >nul

(
echo VSVersionInfo^(
echo   ffi=FixedFileInfo^(
echo     filevers=^(0, 1, 0, 0^),
echo     prodvers=^(0, 1, 0, 0^),
echo     mask=0x3f,
echo     flags=0x0,
echo     OS=0x40004,
echo     fileType=0x1,
echo     subtype=0x0,
echo     date=^(0, 0^)^
echo   ^),
echo   kids=[
echo     StringFileInfo^(
echo       [
echo         StringTable^(
echo           '040904B0',
echo           [StringStruct^('CompanyName', 'Ravin Dulanjana'^),
echo           StringStruct^('FileDescription', 'Silence Remover'^),
echo           StringStruct^('FileVersion', '%APP_VERSION%'^),
echo           StringStruct^('InternalName', 'Silence Remover'^),
echo           StringStruct^('OriginalFilename', 'Silence Remover.exe'^),
echo           StringStruct^('ProductName', 'Silence Remover'^),
echo           StringStruct^('ProductVersion', '%APP_VERSION%'^)]^
echo         ^)
echo       ]^
echo     ^),
echo     VarFileInfo^([VarStruct^('Translation', [1033, 1200]^)]^)
echo   ]^
echo ^)
)> "%VERSION_INFO%"

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --workpath "%BUILD_DIR%" ^
  --distpath "%DIST_DIR%" ^
  --name "%APP_NAME%" ^
  --icon "%ICON_PATH%" ^
  --version-file "%VERSION_INFO%" ^
  --add-data "LICENSE;." ^
  app.py

echo.
echo Windows app build output:
echo   %ROOT_DIR%\dist\%APP_NAME%\

endlocal
