"""admin.py

Admin-only authentication + the financial dashboard.

This module is split out of `app.py` so the main app stays easy to reason about.
"""

from __future__ import annotations

import os
import time
import hmac

import altair as alt
import pandas as pd
import streamlit as st


def _get_sales_manager_password() -> str | None:
    """Read the admin password.

    Prefers Streamlit secrets (Streamlit Cloud), falls back to an env var.
    """
    try:
        pw = st.secrets.get("sales_manager_password", None)
        if pw:
            return str(pw)
    except Exception:
        pass

    pw = os.environ.get("SALES_MANAGER_PASSWORD")
    return str(pw) if pw else None


def require_sales_manager_auth(*, session_timeout_seconds: int = 2 * 60 * 60) -> None:
    """Gate Admin view behind a password in the sidebar.

    Minimal internal-only protection:
    - timing-safe compare
    - logout button
    - session timeout (default: 2 hours)
    """
    expected = _get_sales_manager_password()
    if not expected:
        st.sidebar.error(
            "Admin password is not configured.\n\n"
            "Add `sales_manager_password` in Streamlit Secrets "
            "or set env var `SALES_MANAGER_PASSWORD`."
        )
        st.stop()

    # Already authed? Enforce timeout + offer logout.
    if st.session_state.get("sales_manager_authed") is True:
        authed_at = float(st.session_state.get("sales_manager_authed_at", 0) or 0)
        if authed_at and (time.time() - authed_at) > session_timeout_seconds:
            st.session_state["sales_manager_authed"] = False
            st.session_state["sales_manager_authed_at"] = 0

        if st.session_state.get("sales_manager_authed") is True:
            st.sidebar.markdown("## Admin access")
            if st.sidebar.button("Log out"):
                st.session_state["sales_manager_authed"] = False
                st.session_state["sales_manager_authed_at"] = 0
                st.experimental_rerun()
            return

    st.sidebar.markdown("## Admin access")
    entered = st.sidebar.text_input("Password", type="password")

    if entered and hmac.compare_digest(str(entered), str(expected)):
        st.session_state["sales_manager_authed"] = True
        st.session_state["sales_manager_authed_at"] = time.time()
        st.sidebar.success("Unlocked.")
        return

    st.sidebar.info("Enter the Admin password to continue.")
    st.stop()


# --- everything below here is unchanged from your current file ---


def _money(x: float) -> str:
    try:
        return f"${float(x):,.0f}"
    except Exception:
        return "$0"


def _money_short(x: float) -> str:
    try:
        x = float(x)
    except Exception:
        return "$0"

    if abs(x) >= 1_000_000:
        return f"${x/1_000_000:.2f}M"
    if abs(x) >= 1_000:
        return f"${x/1_000:.0f}K"
    return f"${x:,.0f}"


def _pct(x: float) -> str:
    try:
        return f"{float(x) * 100:.1f}%"
    except Exception:
        return "0.0%"


def _safe_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _safe_title(s: str) -> str:
    return str(s).strip().title()


# (rest of your existing admin dashboard code continues below)
# NOTE: keep your existing functions exactly as they are under this point.
