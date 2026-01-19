"""app.py

Thin Streamlit entrypoint.

Keep this file small so refactors are easy and merge conflicts are rare.
"""

from __future__ import annotations

from state import init_state
from app_controller import run_app


init_state()
run_app()
