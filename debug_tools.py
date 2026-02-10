"""debug_tools.py

Lightweight, Streamlit-friendly debugging utilities.

Enable by adding `?debug=1` to the Streamlit URL (or set st.secrets["debug"]=true).

Usage:
- Call `debug_event("name", key=value, ...)` anywhere.
- Call `render_debug_panel()` once (typically early in app startup).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st


_LOG_KEY = "debug_log"


def is_debug_mode() -> bool:
    """Return True when debugging should be shown."""
    try:
        qp = st.query_params
        if str(qp.get("debug", "")).strip() in ("1", "true", "True"):
            return True
    except Exception:
        pass

    try:
        if bool(st.secrets.get("debug", False)):
            return True
    except Exception:
        pass

    return False


def debug_event(name: str, **fields: Any) -> None:
    """Append a structured event to session_state when debug mode is enabled."""
    if not is_debug_mode():
        return

    st.session_state.setdefault(_LOG_KEY, [])
    st.session_state[_LOG_KEY].append(
        {
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "name": str(name),
            "fields": fields,
        }
    )

    # Prevent unbounded growth
    if len(st.session_state[_LOG_KEY]) > 250:
        st.session_state[_LOG_KEY] = st.session_state[_LOG_KEY][-250:]


def render_debug_panel() -> None:
    """Render a sidebar panel with recent debug events + key session state."""
    if not is_debug_mode():
        return

    with st.sidebar.expander("🛠️ Debug", expanded=False):
        st.caption("Debug mode is ON (disable by removing ?debug=1 from the URL).")

        logs = st.session_state.get(_LOG_KEY, [])
        if not logs:
            st.info("No debug events yet.")
        else:
            st.caption(f"Events: {len(logs)} (showing last 25)")
            for e in logs[-25:][::-1]:
                st.write(f"**{e['ts']}** — `{e['name']}`")
                if e.get("fields"):
                    st.json(e["fields"], expanded=False)

        st.divider()
        snapshot_keys = [
            "team_view",
            "selected_county",
            "county_source",
            "last_map_clicked_county",
            "acq_selected_county",
            "buyer_choice",
            "dispo_rep_choice",
            "acq_rep_choice",
            "market_choice",
            "admin_year_choice",
            "admin_time_bucket",
        ]
        snapshot = {k: st.session_state.get(k) for k in snapshot_keys if k in st.session_state}
        st.caption("Session snapshot (selected keys)")
        st.json(snapshot, expanded=False)
