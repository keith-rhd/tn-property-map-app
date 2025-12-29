import streamlit as st


def init_state() -> None:
    """Central place to initialize Streamlit session state.

    Phase A3 goal: avoid scattered `setdefault` calls and missing-key bugs.
    This function does NOT depend on data loading.
    """
    defaults = {
        # Global
        "team_view": "Dispo",

        # County selection
        "selected_county": "",
        "county_source": "",  # "map" | "dropdown" | ""
        "last_map_clicked_county": "",

        # Dispo dropdown tracking
        "dispo_county_lookup": "— Select a county —",
        "_dispo_prev_county_lookup": "— Select a county —",

        # Acquisitions selection tracking
        "acq_selected_county": "",
        "acq_county_select": "",

        # One-time handoff used after map click
        "acq_pending_county_title": "",
    }

    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


def ensure_default_county(all_county_options: list[str], preferred: str = "DAVIDSON") -> None:
    """Set a stable default county once we know the county list.

    Call this AFTER `all_county_options` is built.
    """
    if not all_county_options:
        return

    # Normalize options as UPPER keys
    options_upper = [str(c).strip().upper() for c in all_county_options]

    default_key = preferred.strip().upper() if preferred else options_upper[0]
    if default_key not in options_upper:
        default_key = options_upper[0]

    # selected_county (used by Dispo + below-map panel)
    if not str(st.session_state.get("selected_county", "")).strip():
        st.session_state["selected_county"] = default_key

    # acq_selected_county (used by Acquisitions view)
    if not str(st.session_state.get("acq_selected_county", "")).strip():
        st.session_state["acq_selected_county"] = default_key
