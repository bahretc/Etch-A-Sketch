#!/bin/bash
# Opens Safety Eval in its own window. Double click this file.
cd "$(dirname "$0")" || exit 1

if [ ! -x ".venv/bin/python" ]; then
    echo
    echo " The app is not installed yet. Double click install-mac.command first."
    echo
    read -r -p " Press return to close. " _
    exit 1
fi

nohup ./.venv/bin/python -m safety_eval.desktop >/dev/null 2>&1 &
disown
echo
echo " Safety Eval is opening in its own window."
echo " You can close this terminal window; the app stays open."
sleep 2
exit 0
