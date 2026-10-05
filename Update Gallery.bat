@echo off
rem Extracts everything from your Dragon Traveler client and builds the gallery, one step after another.
rem The first run checks Python, installs the Python packages and offers to install FFmpeg.
rem Later runs only process new or changed files, so after a game patch just run it again.
rem Run "Update Gallery.bat full" to rebuild everything from scratch.
setlocal
cd /d "%~dp0"
title Updating Dragon Traveler gallery

rem ---- 1. Python 3.10 or newer ----
set "PY="
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "PY=python"
if not defined PY py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    echo Python 3.10 or newer is needed. Install it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" in the installer, then run this again.
    goto :fail
)

rem ---- 2. Python packages ----
%PY% -c "import UnityPy, numpy, PIL" >nul 2>&1
if errorlevel 1 (
    echo Installing the Python packages this needs...
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Couldn't install the Python packages - see the messages above.
        goto :fail
    )
    echo.
)

rem ---- 3. FFmpeg, for videos and voice lines ----
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo FFmpeg isn't installed. It's needed to convert the game's videos and audio.
    where winget >nul 2>&1
    if errorlevel 1 goto :noffmpeg
    choice /m "Install it now with winget"
    if errorlevel 2 goto :noffmpeg
    winget install --id Gyan.FFmpeg -e --accept-source-agreements
    echo.
    echo FFmpeg is installed. Close this window and run "Update Gallery.bat" again so it can be found.
    goto :fail
)

rem ---- 4. Extract and build, step by step ----
cd _tools
if /i "%~1"=="full" (%PY% -u update.py --full) else (%PY% -u update.py)
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

:noffmpeg
echo Install FFmpeg (for example: winget install Gyan.FFmpeg, or from https://ffmpeg.org/download.html),
echo make sure it's on PATH, then run this again.

:fail
echo.
pause
endlocal
exit /b 1
