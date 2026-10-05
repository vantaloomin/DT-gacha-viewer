@echo off
rem Starts a local web server for the hero gallery and opens it in Chrome.
rem The minimized "Hero Gallery Server" window closes by itself about a minute and a half after
rem the last gallery tab is closed.
setlocal
set PORT=8765
cd /d "%~dp0"

rem Nothing extracted yet? The gallery needs Update Gallery.bat to run first.
if not exist "heroes.json" (
    echo The gallery has no content yet. Run "Update Gallery.bat" first to extract it from your game client.
    pause
    exit /b 1
)


rem Start the server only if nothing is already listening on the port.
netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul
if errorlevel 1 (
    start "Hero Gallery Server" /min python "%~dp0_tools\serve.py" %PORT%
    timeout /t 2 /nobreak >nul
)

start "" chrome "http://localhost:%PORT%/index.html?v=%RANDOM%%RANDOM%" 2>nul || start "" "http://localhost:%PORT%/index.html?v=%RANDOM%%RANDOM%"
endlocal
