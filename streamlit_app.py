# Streamlit Cloud entry point.
# Streamlit Cloud auto-detects this file when no main file is configured.
# It simply delegates to dashboard.py.
#
# In Streamlit Cloud deployment settings you can also set:
#   Main file path = dashboard.py
# which removes the need for this file entirely.

import runpy
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
runpy.run_path("dashboard.py", run_name="__main__")
