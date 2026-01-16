# state.py
import streamlit as st


def init_state():
    """
    Central place for Streamlit session-state defaults.
    Keeps state keys consistent and prevents regressions when the app grows.
    """
    placeholder = "— Select a county —"
    defaults = {
        "team_view": "Dispo",
        "selected_county": "",
        "acq_selected_county": "",
        "county_source": "",  # "map" | "dropdown" | ""
        "last_map_clicked_county": "",
        "dispo_county_lookup": placeholder,
        "_dispo_prev_county_lookup": placeholder,
        # Dispo Rep filter memory (optional)
        "dispo_rep_choice": "All reps",
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)
