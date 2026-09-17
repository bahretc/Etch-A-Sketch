@echo off
rem Opens Safety Eval in its own window. Double click this file.
rem This console closes itself at once; the app window follows in a few
rem seconds. Closing the app window shuts everything down.
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" goto run
echo.
echo  The app is not installed yet. Double click install-windows.bat first.
echo.
pause
exit /b 1

:run
start "" ".venv\Scripts\pythonw.exe" -m safety_eval.desktop
exit /b 0
