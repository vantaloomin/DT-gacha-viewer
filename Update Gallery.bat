@echo off
rem Re-extracts everything from the game after a patch and updates the gallery.
rem Only new or changed files are processed, so later runs are much faster than the first.
rem Run "Update Gallery.bat full" to rebuild everything from scratch.
setlocal
cd /d "%~dp0_tools"
title Updating Dragon Traveler gallery
if /i "%~1"=="full" (python -u update.py --full) else (python -u update.py)
echo.
if errorlevel 1 (echo The update stopped with an error - see the messages above.) else (echo All done. Refresh the gallery in your browser to see the changes.)
pause
endlocal
