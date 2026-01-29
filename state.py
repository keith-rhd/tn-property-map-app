"""state.py

Single place for Streamlit session_state defaults.

Keeping this separate prevents `app.py` from growing again and reduces
"mystery keys" sprinkled around the codebase.
"""

from __future__ import annotations

import streamlit as st


def init_state() -> None:
    """Initialize all session_state keys used by the app."""

    placeholder = "— Select a county —"

    defaults = {
        # View selection
        "team_view": "Dispo",  # Dispo | Acquisitions | Admin

        "county_quick_search": placeholder,  # shared dropdown title

        # County selection
        "selected_county": "",
        "acq_selected_county": "",
        "county_source": "",  # map | dropdown | ""
        "last_map_clicked_county": "",

        # Dispo quick lookup dropdown
        "dispo_county_lookup": placeholder,
        "_dispo_prev_county_lookup": placeholder,

        # Dispo Rep filter memory
        "dispo_rep_choice": "All reps",

        # Admin auth
        "sales_manager_authed": False,
    }

    for k, v in defaults.items():
        st.session_state.setdefault(k, v)
