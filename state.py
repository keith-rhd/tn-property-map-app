# state.py
import streamlit as st


def init_state() -> None:
    """Initialize all session_state keys used by the app."""

    placeholder = "— Select a county —"

    defaults = {
        # View selection
        "team_view": "Dispo",  # Dispo | Acquisitions | Admin

        # County selection
        "selected_county": "",
        "acq_selected_county": "",
        "county_source": "",  # map | dropdown | ""
        "last_map_clicked_county": "",
        # NEW: prevents dropdown from constantly being forced back to last map county
        "last_map_synced_county": "",

        "county_quick_search": placeholder,  # shared dropdown title

        # Dispo Rep filter memory
        "dispo_rep_choice": "All dispo reps",
        "dispo_acq_rep_choice": "All acquisition reps",

        # Admin auth
        "sales_manager_authed": False,
    }

    for k, v in defaults.items():
        st.session_state.setdefault(k, v)
            # Migration: if an existing session still has the old label, upgrade it
    if st.session_state.get("dispo_rep_choice") == "All reps":
        st.session_state["dispo_rep_choice"] = "All dispo reps"

