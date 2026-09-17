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
rem The wildcard must NOT be quoted here: cmd only expands an unquoted one,
rem and a quoted pattern silently yields nothing, which would send a
rem wheel-only folder down the install-the-folder path and fail there.
rem cd /d at the top already put us in the script's own folder.
set "WHEEL="
for %%f in (*.whl) do set "WHEEL=%%~ff"
if defined WHEEL goto install_wheel
if exist "pyproject.toml" goto install_folder
echo.
echo  [X] This folder has neither the app's wheel file (.whl) nor its source
echo      (pyproject.toml), so there is nothing to install. Unzip the whole
echo      folder you were sent and run this installer from inside it.
echo.
pause
exit /b 1

:install_wheel
"%VPY%" -m pip install "%WHEEL%[pdf,ocr,ui,deliverables,maps,llm]"
if errorlevel 1 goto failed
goto installed

:install_folder
"%VPY%" -m pip install ".[pdf,ocr,ui,deliverables,maps,llm]"
if errorlevel 1 goto failed

:installed

rem The desktop window library is best-effort: without it the launcher
rem falls back to an Edge or Chrome app window, so a failure here only
rem changes which window opens, and must not fail the install.
"%VPY%" -m pip install --quiet pywebview
if not errorlevel 1 goto webview_ok
echo      The native window library did not install; the app will open
echo      in an Edge or Chrome window instead.
:webview_ok

rem ---- 4. the browser that prints the map PDFs -------------------------------
echo  [4/5] Installing the browser that prints the map PDFs
"%VPY%" -m playwright install chromium
rem Not fatal, so no goto failed here. Note the goto rather than a second
rem "if errorlevel 1 echo": echo resets errorlevel, so the follow-on line
rem would never print, and a leading "(" in an if body opens a command
rem block instead of echoing.
if not errorlevel 1 goto chromium_ok
echo      Chromium did not install. The maps will still be written as web
echo      pages you can open in any browser and print by hand.
:chromium_ok

rem ---- 5. report --------------------------------------------------------------
echo.
echo  [5/5] Checking what is available on this machine
echo.
"%VPY%" -m safety_eval.cli doctor
if errorlevel 1 goto failed

echo.
echo  ===========================================================
echo   Done. To open the app, double click:  run-app-windows.bat
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
