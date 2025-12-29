import streamlit as st


def _extract_clicked_county(map_out: dict) -> str:
    """
    Extract clicked county name from st_folium output.
    Returns UPPER county name or "".
    """
    if not map_out or not isinstance(map_out, dict):
        return ""

    clicked = None
    try:
        clicked = map_out.get("last_active_drawing") or map_out.get("last_clicked")
    except Exception:
        clicked = None

    if not clicked or not isinstance(clicked, dict):
        return ""

    props = clicked.get("properties") or {}
    name = str(props.get("NAME") or props.get("name") or "").strip().upper()
    return name


def handle_map_click(map_out: dict, all_county_options: list[str]) -> bool:
    """
    Handle map click -> session_state updates.

    Returns:
      True if the function triggered a rerun (i.e. county changed),
      False otherwise.

    Side effects (only when county changed):
      - selected_county
      - county_source = "map"
      - last_map_clicked_county
      - acq_pending_county_title (Title Case)
    """
    clicked_name = _extract_clicked_county(map_out)
    if not clicked_name:
        return False

    valid = {str(c).strip().upper() for c in (all_county_options or [])}
    if clicked_name not in valid:
        return False

    current = str(st.session_state.get("selected_county", "")).strip().upper()
    if clicked_name == current:
        return False

    st.session_state["selected_county"] = clicked_name
    st.session_state["county_source"] = "map"
    st.session_state["last_map_clicked_county"] = clicked_name
    st.session_state["acq_pending_county_title"] = clicked_name.title()

    st.rerun()
    return True
