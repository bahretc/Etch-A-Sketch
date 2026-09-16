#!/bin/bash
# Opens the Safety Eval app in your web browser. Double click this file.
cd "$(dirname "$0")" || exit 1

if [ ! -x ".venv/bin/python" ]; then
    echo
    echo " The app is not installed yet. Double click install-mac.command first."
    echo
    read -r -p " Press return to close. " _
    exit 1
fi

# The app lives inside the package and needs a launcher file next to it.
# The source zip ships one; if only the wheel was installed here, write it.
APPFILE="streamlit_app.py"
if [ ! -f "$APPFILE" ]; then
    APPFILE="_launch_app.py"
    printf 'from safety_eval.app import main\nmain()\n' > "$APPFILE"
fi

echo
echo " Starting Safety Eval. Your web browser will open in a moment."
echo
echo " Leave this window open while you work. Closing it closes the app."
echo
./.venv/bin/python -m streamlit run "$APPFILE"
read -r -p " Press return to close. " _
