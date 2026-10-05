@echo off
rem Extracts everything from your Dragon Traveler client and builds the gallery, one step after another.
rem The first run sets up what's missing: if Windows has no Python 3.10+ or no FFmpeg, it offers to download
rem portable copies into the "runtime" folder (plain zips: nothing is installed on Windows, no admin rights,
rem no installers or MSIX packages). Delete the "runtime" folder to remove them.
rem Later runs only process new or changed files, so after a game patch just run it again.
rem Run "Update Gallery.bat full" to rebuild everything from scratch.
rem Set DT_ASSUME_YES=1 to answer yes to the download questions (for unattended runs).
setlocal
cd /d "%~dp0"
title Updating Dragon Traveler gallery

rem Portable downloads (official builds)
set "PY_VER=3.13.16"
set "PY_TAG=313"
set "PY_URL=https://www.python.org/ftp/python/%PY_VER%/python-%PY_VER%-embed-amd64.zip"
set "PIP_URL=https://bootstrap.pypa.io/get-pip.py"
set "FF_URL=https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
set "RT=%~dp0runtime"

call "%~dp0_tools\env.bat"

rem ---- 1. Python 3.10 or newer ----
if defined PY goto :packages
echo Python 3.10 or newer wasn't found.
echo A portable copy can be downloaded into the "runtime" folder (about 40 MB to download, 140 MB on disk
echo with the packages it needs).
echo Nothing gets installed on Windows; delete that folder to remove it.
if not "%DT_ASSUME_YES%"=="1" (
    choice /m "Download portable Python now"
    if errorlevel 2 goto :nopython
)
call :need_tools || goto :fail
if not exist "%RT%\python" mkdir "%RT%\python"
echo Downloading Python %PY_VER%...
call :fetch "%PY_URL%" "%RT%\python.zip" || goto :dlfail
call :unzip "%RT%\python.zip" "%RT%\python" || goto :dlfail
del "%RT%\python.zip"
rem The embeddable Python ignores site-packages and the script's own folder unless its ._pth file lists them.
(
    echo python%PY_TAG%.zip
    echo .
    echo ..\..\_tools
    echo import site
) > "%RT%\python\python%PY_TAG%._pth"
rem keep the portable copy self-contained: ignore packages from a per-user Python install
set "PYTHONNOUSERSITE=1"
echo Setting up pip...
call :fetch "%PIP_URL%" "%RT%\python\get-pip.py" || goto :dlfail
"%RT%\python\python.exe" "%RT%\python\get-pip.py" --no-warn-script-location -q || goto :pipfail
rem Some packages ship only as source. pip can't build them in an isolated environment inside the
rem embeddable Python (its ._pth file hides that environment), so give it setuptools and build in place.
"%RT%\python\python.exe" -m pip install -q --no-warn-script-location setuptools wheel || goto :pipfail
del "%RT%\python\get-pip.py"
set "PY=%RT%\python\python.exe"
echo.

:packages
rem ---- 2. Python packages ----
"%PY%" -c "import UnityPy, numpy, PIL" >nul 2>&1
if not errorlevel 1 goto :ffmpeg
echo Installing the Python packages this needs...
set "PIP_ARGS="
if /i "%PY%"=="%RT%\python\python.exe" set "PIP_ARGS=--no-build-isolation"
"%PY%" -m pip install --no-warn-script-location %PIP_ARGS% -r requirements.txt || goto :pipfail
echo.

:ffmpeg
rem ---- 3. FFmpeg, for videos and voice lines ----
where ffmpeg >nul 2>&1
if not errorlevel 1 goto :run
echo FFmpeg wasn't found. It's needed to convert the game's videos and audio.
echo A portable copy can be downloaded into the "runtime" folder (about 200 MB to download, 160 MB on disk).
echo Nothing gets installed on Windows; delete that folder to remove it.
if not "%DT_ASSUME_YES%"=="1" (
    choice /m "Download portable FFmpeg now"
    if errorlevel 2 goto :noffmpeg
)
call :need_tools || goto :fail
echo Downloading FFmpeg...
call :fetch "%FF_URL%" "%RT%\ffmpeg.zip" || goto :dlfail
if exist "%RT%\ffmpeg-tmp" rmdir /s /q "%RT%\ffmpeg-tmp"
mkdir "%RT%\ffmpeg-tmp"
echo Unpacking...
call :unzip "%RT%\ffmpeg.zip" "%RT%\ffmpeg-tmp" || goto :dlfail
del "%RT%\ffmpeg.zip"
if not exist "%RT%\ffmpeg" mkdir "%RT%\ffmpeg"
rem Only ffmpeg.exe is needed (the zip also has ffprobe and ffplay, another 330 MB)
for /d %%d in ("%RT%\ffmpeg-tmp\*") do move /y "%%d\bin\ffmpeg.exe" "%RT%\ffmpeg\" >nul
rmdir /s /q "%RT%\ffmpeg-tmp"
if not exist "%RT%\ffmpeg\ffmpeg.exe" goto :dlfail
set "PATH=%RT%\ffmpeg;%PATH%"
echo.

:run
rem ---- 4. Extract and build, step by step ----
cd _tools
if /i "%~1"=="full" ("%PY%" -u update.py --full) else ("%PY%" -u update.py)
if errorlevel 1 (
    echo.
    echo The update stopped with an error - see the messages above.
    goto :fail
)
echo.
echo All done. Run "Open Gallery.bat", or refresh the gallery if it's already open.
pause
endlocal
exit /b 0

:need_tools
rem Downloads and unzips with curl and tar (part of Windows 10 1803+ and 11). Some trimmed-down Windows
rem builds remove them, so fall back to Windows PowerShell's Invoke-WebRequest and Expand-Archive.
set "CURL=" & set "TAR=" & set "PSH="
if exist "%SystemRoot%\System32\curl.exe" set "CURL=%SystemRoot%\System32\curl.exe"
if not defined CURL for /f "delims=" %%x in ('where curl 2^>nul') do if not defined CURL set "CURL=%%x"
if exist "%SystemRoot%\System32\tar.exe" set "TAR=%SystemRoot%\System32\tar.exe"
if not defined TAR for /f "delims=" %%x in ('where tar 2^>nul') do if not defined TAR set "TAR=%%x"
if exist "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" set "PSH=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not defined PSH for /f "delims=" %%x in ('where pwsh powershell 2^>nul') do if not defined PSH set "PSH=%%x"
if defined PSH exit /b 0
if defined CURL if defined TAR exit /b 0
echo Downloading needs either the curl and tar commands or Windows PowerShell, and neither was found.
echo Install Python and FFmpeg yourself instead - see below.
exit /b 1

:fetch
rem :fetch url file
if defined CURL (
    "%CURL%" -L --fail --progress-bar -o "%~2" "%~1"
    exit /b
)
set "DL_URL=%~1"
set "DL_OUT=%~2"
"%PSH%" -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference = 'SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -UseBasicParsing -Uri $env:DL_URL -OutFile $env:DL_OUT } catch { Write-Host $_; exit 1 }"
exit /b

:unzip
rem :unzip file.zip folder
if defined TAR (
    "%TAR%" -xf "%~1" -C "%~2"
    exit /b
)
set "UZ_ZIP=%~1"
set "UZ_DIR=%~2"
"%PSH%" -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference = 'SilentlyContinue'; try { Expand-Archive -Force -LiteralPath $env:UZ_ZIP -DestinationPath $env:UZ_DIR } catch { Write-Host $_; exit 1 }"
exit /b

:nopython
echo Install Python 3.10 or newer from https://www.python.org/downloads/windows/ (the "Windows installer
echo (64-bit)" .exe; tick "Add python.exe to PATH"), or run this again and let it download the portable copy.
goto :fail

:noffmpeg
echo Put FFmpeg on PATH (e.g. the zip from https://www.gyan.dev/ffmpeg/builds/), or run this again and let it
echo download the portable copy.
goto :fail

:dlfail
echo The download or unpacking failed - check your internet connection and try again.
goto :fail

:pipfail
echo Couldn't install the Python packages - see the messages above.

:fail
echo.
pause
endlocal
exit /b 1
