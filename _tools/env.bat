@echo off
rem Shared by the launchers: finds the Python and FFmpeg the gallery tools should use.
rem   PY    full path of python.exe: the portable copy in runtime\python (set up by Update Gallery.bat
rem         when Windows has no usable Python), else Python 3.10+ from PATH or the py launcher
rem   PATH  gets runtime\ffmpeg prepended when the portable FFmpeg is there
rem Nothing is downloaded here; see Update Gallery.bat for that.
for %%i in ("%~dp0..") do set "RUNTIME=%%~fi\runtime"
set "PY="
if exist "%RUNTIME%\python\python.exe" (
    set "PY=%RUNTIME%\python\python.exe"
    rem keep the portable copy self-contained: ignore packages from a per-user Python install
    set "PYTHONNOUSERSITE=1"
) else (
    for /f "delims=" %%p in ('python -c "import sys; print(sys.executable) if sys.version_info.__ge__((3, 10)) else 0" 2^>nul') do set "PY=%%p"
    if not defined PY for /f "delims=" %%p in ('py -3 -c "import sys; print(sys.executable) if sys.version_info.__ge__((3, 10)) else 0" 2^>nul') do set "PY=%%p"
)
if exist "%RUNTIME%\ffmpeg\ffmpeg.exe" set "PATH=%RUNTIME%\ffmpeg;%PATH%"
exit /b 0
