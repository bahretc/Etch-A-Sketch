@echo off
rem Opens the Safety Eval app in your web browser. Double click this file.
setlocal
cd /d "%~dp0"
title Safety Eval

if exist ".venv\Scripts\python.exe" goto installed
echo.
echo  The app is not installed yet. Double click install-windows.bat first.
echo.
pause
exit /b 1

:installed
rem The app lives inside the package and needs a launcher file next to it.
rem The source zip ships one; if only the wheel was installed here, write it.
set "APPFILE=streamlit_app.py"
if exist "streamlit_app.py" goto run
set "APPFILE=_launch_app.py"
> "_launch_app.py" echo from safety_eval.app import main
>> "_launch_app.py" echo main()

:run
echo.
echo  Starting Safety Eval. Your web browser will open in a moment.
echo.
echo  Leave this black window open while you work. Closing it closes the app.
echo.
".venv\Scripts\python.exe" -m streamlit run "%APPFILE%"
pause
