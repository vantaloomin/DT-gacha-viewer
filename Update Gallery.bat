@echo off
rem Extracts everything from your Dragon Traveler client and builds the gallery, one step after another.
rem The first run sets up what's missing: if Windows has no Python 3.10+ or no FFmpeg, it offers to download
rem portable copies into the "runtime" folder (plain zips: nothing is installed on Windows, no admin rights,
rem no installers or MSIX packages). Delete the "runtime" folder to remove them. If a download can't be
rem done automatically, it explains how to put the files there by hand, and the next run finishes the setup.
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
set "PORTABLE_PY=%RT%\python\python.exe"

call "%~dp0_tools\env.bat"

rem ---- 1. Python 3.10 or newer ----
set "SETUP=python"
if /i "%PY%"=="%PORTABLE_PY%" goto :pyconfig
if defined PY goto :packages
echo Python 3.10 or newer wasn't found.
echo A portable copy can be downloaded into the "runtime" folder (about 40 MB to download, 140 MB on disk
echo with the packages it needs).
echo Nothing gets installed on Windows; delete that folder to remove it.
if not "%DT_ASSUME_YES%"=="1" (
    choice /m "Download portable Python now"
    if errorlevel 2 goto :manual
)
call :need_tools || goto :manual
if not exist "%RT%\python" mkdir "%RT%\python"
echo Downloading Python %PY_VER%...
call :fetch "%PY_URL%" "%RT%\python.zip" || goto :manual
call :unzip "%RT%\python.zip" "%RT%\python" || goto :manual
del "%RT%\python.zip"

:pyconfig
rem Finish setting up the portable Python (also picks up a copy unzipped into runtime\python by hand)
set "PY=%PORTABLE_PY%"
rem keep the portable copy self-contained: ignore packages from a per-user Python install
set "PYTHONNOUSERSITE=1"
"%PY%" -m pip --version >nul 2>&1
if not errorlevel 1 goto :packages
rem The embeddable Python ignores site-packages and the script's own folder unless its ._pth file lists them.
set "PTH=" & set "PYZIP="
for %%f in ("%RT%\python\python3*._pth") do set "PTH=%%f"
if not defined PTH set "PTH=%RT%\python\python%PY_TAG%._pth"
for %%f in ("%RT%\python\python3*.zip") do set "PYZIP=%%~nxf"
if not defined PYZIP set "PYZIP=python%PY_TAG%.zip"
(
    echo %PYZIP%
    echo .
    echo ..\..\_tools
    echo import site
) > "%PTH%"
echo Setting up pip...
if not exist "%RT%\python\get-pip.py" (
    call :need_tools || goto :manual
    call :fetch "%PIP_URL%" "%RT%\python\get-pip.py" || goto :manual
)
"%PY%" "%RT%\python\get-pip.py" --no-warn-script-location -q || goto :pipfail
rem Some packages ship only as source. pip can't build them in an isolated environment inside the
rem embeddable Python (its ._pth file hides that environment), so give it setuptools and build in place.
"%PY%" -m pip install -q --no-warn-script-location setuptools wheel || goto :pipfail
del "%RT%\python\get-pip.py"
echo.

:packages
rem ---- 2. Python packages ----
"%PY%" -c "import UnityPy, numpy, PIL" >nul 2>&1
if not errorlevel 1 goto :ffmpeg
echo Installing the Python packages this needs...
set "PIP_ARGS="
if /i "%PY%"=="%PORTABLE_PY%" set "PIP_ARGS=--no-build-isolation"
"%PY%" -m pip install --no-warn-script-location %PIP_ARGS% -r requirements.txt || goto :pipfail
echo.

:ffmpeg
rem ---- 3. FFmpeg, for videos and voice lines ----
set "SETUP=ffmpeg"
where ffmpeg >nul 2>&1
if not errorlevel 1 goto :run
echo FFmpeg wasn't found. It's needed to convert the game's videos and audio.
echo A portable copy can be downloaded into the "runtime" folder (about 200 MB to download, 160 MB on disk).
echo Nothing gets installed on Windows; delete that folder to remove it.
if not "%DT_ASSUME_YES%"=="1" (
    choice /m "Download portable FFmpeg now"
    if errorlevel 2 goto :manual
)
call :need_tools || goto :manual
echo Downloading FFmpeg...
call :fetch "%FF_URL%" "%RT%\ffmpeg.zip" || goto :manual
if exist "%RT%\ffmpeg-tmp" rmdir /s /q "%RT%\ffmpeg-tmp"
mkdir "%RT%\ffmpeg-tmp"
echo Unpacking...
call :unzip "%RT%\ffmpeg.zip" "%RT%\ffmpeg-tmp" || goto :manual
del "%RT%\ffmpeg.zip"
if not exist "%RT%\ffmpeg" mkdir "%RT%\ffmpeg"
rem Only ffmpeg.exe is needed (the zip also has ffprobe and ffplay, another 330 MB)
for /d %%d in ("%RT%\ffmpeg-tmp\*") do move /y "%%d\bin\ffmpeg.exe" "%RT%\ffmpeg\" >nul
rmdir /s /q "%RT%\ffmpeg-tmp"
if not exist "%RT%\ffmpeg\ffmpeg.exe" goto :manual
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
echo.
echo Downloading needs either the curl and tar commands or Windows PowerShell, and neither was found.
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

:manual
rem Automatic setup didn't happen: explain how to do it by hand
del "%RT%\python.zip" "%RT%\ffmpeg.zip" >nul 2>&1
if exist "%RT%\ffmpeg-tmp" rmdir /s /q "%RT%\ffmpeg-tmp"
echo.
echo ===========================================================================================
if "%SETUP%"=="python" goto :manual_python
echo  FFmpeg isn't set up. To do it by hand:
echo.
echo    1. Download this zip in your browser:
echo         %FF_URL%
echo       (or "ffmpeg-release-essentials.zip" from https://www.gyan.dev/ffmpeg/builds/)
echo    2. Open the zip, go into its "bin" folder and copy ffmpeg.exe to:
echo         %RT%\ffmpeg\ffmpeg.exe
echo    3. Run "Update Gallery.bat" again.
echo.
echo  Or put any FFmpeg build with libvpx and libopus on PATH.
goto :manual_end
:manual_python
echo  Python isn't set up. To do it by hand:
echo.
echo    1. Download this zip in your browser:
echo         %PY_URL%
echo    2. Unzip everything in it into this folder, so that python.exe ends up here:
echo         %RT%\python\python.exe
echo    3. Download this file and save it in that same folder as get-pip.py:
echo         %PIP_URL%
echo    4. Run "Update Gallery.bat" again - it finishes the setup and installs the packages.
echo.
echo  Or install Python 3.10+ normally: https://www.python.org/downloads/windows/ - the
echo  "Windows installer (64-bit)" .exe, with "Add python.exe to PATH" ticked.
:manual_end
echo ===========================================================================================
goto :fail

:pipfail
echo.
echo Couldn't install the Python packages - see the messages above. pip downloads them from pypi.org,
echo so check your internet connection (or proxy/firewall) and run "Update Gallery.bat" again.

:fail
echo.
pause
endlocal
exit /b 1
