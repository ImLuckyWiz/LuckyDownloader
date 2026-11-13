@echo off
REM Build LuckyDownloader CLI for Windows with Nuitka:
REM   dist\LuckyDownloader-CLI\LuckyDownloader-CLI.exe   (portable folder)
REM   dist\LuckyDownloader-CLI-windows.zip              (portable zip archive)
REM Usage: build_windows_cli.bat [version]
setlocal
cd /d "%~dp0"
set VER=%1
if "%VER%"=="" set VER=1.0

python -m pip install --upgrade pip || goto :err
python -m pip install -r requirements-cli.txt -r requirements-build.txt || goto :err

if not exist build mkdir build
> build\version.txt echo %VER%

REM Windows PE version info
python -c "import re, sys; v = sys.argv[1]; nums = [str(min(int(n), 65535)) for n in re.findall(r'\d+', v)[:4]] or ['1', '0']; open('build/pe_version.txt', 'w').write('.'.join(nums))" "%VER%" || goto :err
set /p PRODUCT_VER=<build\pe_version.txt
if "%PRODUCT_VER%"=="" set PRODUCT_VER=1.0.0.0

if exist dist\LuckyDownloader-CLI rmdir /s /q dist\LuckyDownloader-CLI
if exist dist\LuckyDownloader-CLI.dist rmdir /s /q dist\LuckyDownloader-CLI.dist

python -m nuitka --mode=standalone ^
  --windows-console-mode=force ^
  --windows-icon-from-ico=assets\icon.ico ^
  --company-name=LuckyDownloader ^
  --product-name=LuckyDownloader-CLI ^
  --product-version=%PRODUCT_VER% ^
  --file-version=%PRODUCT_VER% ^
  --output-dir=dist ^
  --output-folder-name=LuckyDownloader-CLI ^
  --output-filename=LuckyDownloader-CLI.exe ^
  --include-data-dir=locale=locale ^
  --include-data-files=build\version.txt=version.txt ^
  --include-package=core ^
  --include-package=requests ^
  --nofollow-import-to=PySide6 ^
  --nofollow-import-to=qt_ui ^
  --nofollow-import-to=PIL ^
  --nofollow-import-to=tkinter ^
  --nofollow-import-to=_tkinter ^
  --nofollow-import-to=pytest ^
  --assume-yes-for-downloads ^
  --update-check=never ^
  cli.py || goto :err

if exist dist\LuckyDownloader-CLI.dist (
  ren dist\LuckyDownloader-CLI.dist LuckyDownloader-CLI || goto :err
)

echo Packaging CLI zip archive...
powershell -NoProfile -Command "Compress-Archive -Path dist\LuckyDownloader-CLI -DestinationPath dist\LuckyDownloader-CLI-windows.zip -Force" || goto :err

echo Done! Output in dist\LuckyDownloader-CLI and dist\LuckyDownloader-CLI-windows.zip
exit /b 0

:err
echo Build failed with error %errorlevel%.
exit /b 1
