"""acquisitions_view.py

Small UI wrapper for Acquisitions tabs.

Acquisitions wants a single-screen experience where the map and the
"Should We Contract This?" calculator live together.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from views.acquisitions_calculator import render_contract_calculator
from views.map_view import render_map_and_details


def render_acquisitions_tabs(
    *,
    df_time_sold_for_view: pd.DataFrame,
    df_time_cut_for_view: pd.DataFrame,
    map_kwargs: dict,
) -> None:
    """Render Acquisitions tabs (Map + Calculator)."""

    tab_map, tab_calc = st.tabs(["Map", "RHD Feasibility Calculator"])

    with tab_map:
        render_map_and_details(**map_kwargs)

    with tab_calc:
        render_contract_calculator(
            df_time_sold_for_view=df_time_sold_for_view,
            df_time_cut_for_view=df_time_cut_for_view,
        )
