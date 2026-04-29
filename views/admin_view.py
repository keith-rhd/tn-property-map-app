"""admin_view.py

Small UI wrapper for Admin tabs.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from views.admin import render_sales_manager_dashboard
from views.map_view import render_map_and_details


def render_admin_tabs(
    *,
    df_sold_only_for_dashboard: pd.DataFrame,
    dashboard_headline: dict,
    county_gp_table: pd.DataFrame,
    map_kwargs: dict,
    df_cut_loose_for_dashboard: pd.DataFrame | None = None,
    df_sold_ytd_base: pd.DataFrame | None = None,
    year_choice: str = "All years",
) -> None:
    """Render Admin tabs (Dashboard + Map)."""

    tab_dash, tab_map = st.tabs(["Dashboard", "Map"])

    with tab_dash:
        render_sales_manager_dashboard(
            df_sold_only_for_dashboard,
            headline=dashboard_headline,
            county_table=county_gp_table,
            df_cut_loose=df_cut_loose_for_dashboard,
            df_sold_ytd_base=df_sold_ytd_base,
            year_choice=year_choice,
        )

    with tab_map:
        render_map_and_details(**map_kwargs)
