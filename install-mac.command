#!/bin/bash
# ---------------------------------------------------------------------------
# Safety Eval installer for Mac and Linux. Double click this file in Finder.
# It puts everything in a .venv folder next to this script and changes
# nothing else on the machine. Run it again any time to repair or update.
# ---------------------------------------------------------------------------
cd "$(dirname "$0")" || exit 1

echo
echo " ==========================================================="
echo "  Safety Eval installer"
echo " ==========================================================="
echo
echo " This takes about five minutes. Leave the window open."
echo

fail() {
    echo
    echo " [X] Something went wrong above. The last lines of error text say"
    echo "     what. Send that text along and it can be sorted out. Nothing on"
    echo "     this computer was changed outside this folder."
    echo
    read -r -p " Press return to close. " _
    exit 1
}

# ---- 1. find Python -------------------------------------------------------
PYCMD=""
for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
            PYCMD="$candidate"
            break
        fi
    fi
done

if [ -z "$PYCMD" ]; then
    echo " [X] Python 3.11 or newer was not found on this computer."
    echo
    echo "     1. Go to   https://www.python.org/downloads/"
    echo "     2. Click the big yellow \"Download Python\" button."
    echo "     3. Open the file you downloaded and follow the installer."
    echo "     4. When it finishes, double click this installer again."
    echo
    read -r -p " Press return to close. " _
    exit 1
fi

echo " [1/5] Found $("$PYCMD" --version 2>&1)"

# ---- 2. private Python folder for this app --------------------------------
echo " [2/5] Making a private Python folder for the app"
if [ ! -x ".venv/bin/python" ]; then
    "$PYCMD" -m venv .venv || fail
fi
VPY="$PWD/.venv/bin/python"

# ---- 3. the app and everything it needs -----------------------------------
echo " [3/5] Downloading and installing the app. This is the slow part."
"$VPY" -m pip install --quiet --upgrade pip || fail
WHEEL="$(ls -1 ./*.whl 2>/dev/null | head -n 1)"
if [ -n "$WHEEL" ]; then
    "$VPY" -m pip install "${WHEEL}[pdf,ocr,ui,deliverables,maps,llm]" || fail
else
    "$VPY" -m pip install ".[pdf,ocr,ui,deliverables,maps,llm]" || fail
fi

# ---- 4. the browser that prints the map PDFs ------------------------------
echo " [4/5] Installing the browser that prints the map PDFs"
if ! "$VPY" -m playwright install chromium; then
    echo "     (Chromium did not install. Maps will still be written as web"
    echo "      pages you can open and print by hand.)"
fi

# ---- 5. report -------------------------------------------------------------
echo
echo " [5/5] Checking what is available on this machine"
echo
"$VPY" -m safety_eval.cli doctor || fail

chmod +x "./run-app-mac.command" 2>/dev/null

echo
echo " ==========================================================="
echo "  Done. To open the app, double click:  run-app-mac.command"
echo " ==========================================================="
echo
read -r -p " Press return to close. " _
