@echo off
REM Build LuckyDownloader (PySide6) for Windows with Nuitka:
REM   dist\LuckyDownloader\LuckyDownloader.exe   (portable folder)
REM   dist\LuckyDownloader-Setup.exe             (installer, if Inno Setup is installed)
REM Usage: build_windows.bat [version]
REM Needs Python 3.10+ from python.org. Installer needs Inno Setup 6 (jrsoftware.org/isdl.php).
setlocal
cd /d "%~dp0"
set VER=%1
if "%VER%"=="" set VER=1.0

python -m pip install --upgrade pip || goto :err
python -m pip install -r requirements.txt || goto :err

if not exist build mkdir build
> build\version.txt echo %VER%

REM Windows PE version info (--product-version / --file-version in Nuitka) must be a numeric
REM sequence of up to 4 numbers (e.g. 0.8.0 or 1.0.0.0), rejecting 'v' prefixes and '-beta' suffixes.
python -c "import re, sys; v = sys.argv[1]; nums = [str(min(int(n), 65535)) for n in re.findall(r'\d+', v)[:4]] or ['1', '0']; open('build/pe_version.txt', 'w').write('.'.join(nums))" "%VER%" || goto :err
set /p PRODUCT_VER=<build\pe_version.txt
if "%PRODUCT_VER%"=="" set PRODUCT_VER=1.0.0.0

if exist dist\LuckyDownloader rmdir /s /q dist\LuckyDownloader
if exist dist\LuckyDownloader.dist rmdir /s /q dist\LuckyDownloader.dist

python -m nuitka --mode=standalone ^
  --enable-plugin=pyside6 ^
  --windows-console-mode=disable ^
  --windows-icon-from-ico=assets\icon.ico ^
  --company-name=LuckyDownloader ^
  --product-name=LuckyDownloader ^
  --product-version=%PRODUCT_VER% ^
  --file-version=%PRODUCT_VER% ^
  --output-dir=dist ^
  --output-folder-name=LuckyDownloader ^
  --output-filename=LuckyDownloader.exe ^
  --include-data-dir=assets=assets ^
  --include-data-dir=locale=locale ^
  --include-data-files=build\version.txt=version.txt ^
  --include-package=core ^
  --include-package=qt_ui ^
  --include-package=requests ^
  --include-module=luckytwitch_engine ^
  --include-module=weblink ^
  --nofollow-import-to=tkinter ^
  --nofollow-import-to=_tkinter ^
  --nofollow-import-to=pytest ^
  --assume-yes-for-downloads ^
  --update-check=never ^
  luckytwitch_qt.py || goto :err

if exist dist\LuckyDownloader.dist (
  ren dist\LuckyDownloader.dist LuckyDownloader || goto :err
)

set ISCC=
where iscc >nul 2>nul && set ISCC=iscc
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe" set ISCC="%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 7\ISCC.exe" set ISCC="%ProgramFiles%\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if defined ISCC (
  %ISCC% /DAppVersion=%VER% installer.iss || goto :err
  echo.
  echo Installer: dist\LuckyDownloader-Setup.exe
) else (
  echo.
  echo Inno Setup not found - skipping the installer. Get it from https://jrsoftware.org/isdl.php
)
echo Portable app: dist\LuckyDownloader\LuckyDownloader.exe
exit /b 0

:err
echo Build failed.
exit /b 1
