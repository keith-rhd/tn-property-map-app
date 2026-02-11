"""map_view.py

Map rendering + below-map panel. This keeps Folium + Streamlit map logic out
of app_controller.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from app_sections import handle_map_click, render_below_map_panel
from data.enrich import (
    build_county_properties_view,
    enrich_geojson_properties,
)
from data.geo import load_tn_geojson
from map_build import build_map
from config import MAP_DEFAULTS


def render_map_and_details(
    *,
    team_view: str,
    mode: str,
    buyer_active: bool,
    buyer_choice: str,
    df_view: pd.DataFrame,
    sold_counts: dict[str, int],
    cut_counts: dict[str, int],
    buyer_count_by_county: dict[str, int],
    top_buyers_dict: dict,
    buyer_sold_counts: dict[str, int],
    mao_tier_by_county: dict[str, str],
    mao_range_by_county: dict[str, str],
    # NEW: Admin-only GP dicts (safe to pass for all views; only Admin uses them)
    gp_total_by_county: dict[str, float] | None = None,
    gp_avg_by_county: dict[str, float] | None = None,
) -> None:
    """Build + render the Folium map and the below-map panel."""

    gp_total_by_county = gp_total_by_county or {}
    gp_avg_by_county = gp_avg_by_county or {}

    county_counts_view = df_view.groupby("County_clean_up").size().to_dict() if not df_view.empty else {}
    county_properties_view = build_county_properties_view(df_view)

    tn_geo = load_tn_geojson()
    tn_geo = enrich_geojson_properties(
        tn_geo,
        team_view=team_view,
        mode=mode,
        buyer_active=buyer_active,
        buyer_choice=buyer_choice,
        top_n_buyers=10,
        county_counts_view=county_counts_view,
        sold_counts=sold_counts,
        cut_counts=cut_counts,
        buyer_sold_counts=buyer_sold_counts,
        top_buyers_dict=top_buyers_dict,
        county_properties_view=county_properties_view,
        mao_tier_by_county=mao_tier_by_county,
        mao_range_by_county=mao_range_by_county,
        buyer_count_by_county=buyer_count_by_county,
        # NEW:
        gp_total_by_county=gp_total_by_county,
        gp_avg_by_county=gp_avg_by_county,
    )

    color_scheme = "mao" if team_view == "Acquisitions" else "activity"

    m = build_map(
        tn_geo,
        team_view=team_view,
        mode=mode,
        buyer_active=buyer_active,
        buyer_choice=buyer_choice,
        center_lat=MAP_DEFAULTS["center_lat"],
        center_lon=MAP_DEFAULTS["center_lon"],
        zoom_start=MAP_DEFAULTS["zoom_start"],
        tiles=MAP_DEFAULTS["tiles"],
        color_scheme=color_scheme,
    )

    map_state = st_folium(
        m,
        height=650,
        use_container_width=True,
        returned_objects=["last_active_drawing", "last_object_clicked"],
    )

    handle_map_click(map_state, team_view)

    render_below_map_panel(
        team_view=team_view,
        df_view=df_view,
        sold_counts=sold_counts,
        cut_counts=cut_counts,
        buyer_count_by_county=buyer_count_by_county,
        mao_tier_by_county=mao_tier_by_county,
        mao_range_by_county=mao_range_by_county,
    )
