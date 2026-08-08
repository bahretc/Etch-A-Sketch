"""Launcher for the Streamlit app.

Run with:  streamlit run streamlit_app.py

The app lives in the package (safety_eval/app.py) and uses package-relative
imports, which ``streamlit run`` cannot resolve when pointed at a file inside
the package; this shim at the repo root is the supported entry point.
"""
from safety_eval.app import main

main()
