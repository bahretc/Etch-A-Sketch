@echo off
rem ---------------------------------------------------------------------------
rem Safety Eval installer for Windows. Double click this file.
rem It puts everything in a .venv folder next to this script and changes
rem nothing else on the machine. Run it again any time to repair or update.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"
title Installing Safety Eval

echo.
echo  ===========================================================
echo   Safety Eval installer
echo  ===========================================================
echo.
echo  This takes about five minutes. Leave the window open.
echo.

rem ---- 1. find Python --------------------------------------------------------
set "PYCMD="
py -3 --version >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3"
if defined PYCMD goto have_python
python --version >nul 2>nul
if not errorlevel 1 set "PYCMD=python"
if defined PYCMD goto have_python

echo  [X] Python is not installed on this computer.
echo.
echo      1. Go to   https://www.python.org/downloads/
echo      2. Click the big yellow "Download Python" button.
echo      3. Run the file you downloaded.
echo      4. IMPORTANT: on the first screen, tick the box that says
echo         "Add python.exe to PATH" before you click Install Now.
echo      5. When it finishes, double click this installer again.
echo.
pause
exit /b 1

:have_python
for /f "tokens=*" %%v in ('%PYCMD% --version 2^>^&1') do set "PYVER=%%v"
echo  [1/5] Found %PYVER%
%PYCMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo.
  echo  [X] That version is too old. Safety Eval needs Python 3.11 or newer.
  echo      Install the current version from https://www.python.org/downloads/
  echo      and tick "Add python.exe to PATH", then run this installer again.
  echo.
  pause
  exit /b 1
)

rem ---- 2. private Python folder for this app ---------------------------------
echo  [2/5] Making a private Python folder for the app
if exist ".venv\Scripts\python.exe" goto have_venv
%PYCMD% -m venv .venv
if errorlevel 1 goto failed
:have_venv
set "VPY=%~dp0.venv\Scripts\python.exe"

rem ---- 3. the app and everything it needs ------------------------------------
echo  [3/5] Downloading and installing the app. This is the slow part.
"%VPY%" -m pip install --quiet --upgrade pip
set "WHEEL="
for %%f in ("%~dp0*.whl") do set "WHEEL=%%~ff"
if defined WHEEL (
  "%VPY%" -m pip install "%WHEEL%[pdf,ocr,ui,deliverables,maps,llm]"
) else (
  "%VPY%" -m pip install ".[pdf,ocr,ui,deliverables,maps,llm]"
)
if errorlevel 1 goto failed

rem ---- 4. the browser that prints the map PDFs -------------------------------
echo  [4/5] Installing the browser that prints the map PDFs
"%VPY%" -m playwright install chromium
if errorlevel 1 echo      (Chromium did not install. Maps will still be written
if errorlevel 1 echo       as web pages you can open and print by hand.)

rem ---- 5. report --------------------------------------------------------------
echo.
echo  [5/5] Checking what is available on this machine
echo.
"%VPY%" -m safety_eval.cli doctor
if errorlevel 1 goto failed

echo.
echo  ===========================================================
echo   Done. To open the app, double click:  start-windows.bat
echo  ===========================================================
echo.
pause
exit /b 0

:failed
echo.
echo  [X] Something went wrong above. The last lines of red or error text say
echo      what. Send that text along and it can be sorted out. Nothing on this
echo      computer was changed outside this folder.
echo.
pause
exit /b 1
