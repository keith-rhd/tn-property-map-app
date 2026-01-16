"""admin_view.py

Small UI wrapper for Admin tabs.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from admin import render_sales_manager_dashboard
from map_view import render_map_and_details


def render_admin_tabs(
    *,
    df_time_sold_for_view: pd.DataFrame,
    map_kwargs: dict,
) -> None:
    """Render Admin tabs (Dashboard + Map)."""

    tab_dash, tab_map = st.tabs(["Dashboard", "Map"])

    with tab_dash:
        # Dashboard expects sold rows
        sold_only = df_time_sold_for_view[df_time_sold_for_view["Status_norm"] == "sold"]
        render_sales_manager_dashboard(sold_only)

    with tab_map:
        render_map_and_details(**map_kwargs)
