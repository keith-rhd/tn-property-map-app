"""app_controller.py

Main orchestration for the Streamlit app.
Now slim: pure "wiring" that calls services + views.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from admin import require_sales_manager_auth
from admin_view import render_admin_tabs
from app_sections import (
    render_acquisitions_sidebar,
    render_dispo_county_quick_lookup,
    compute_buyer_context_from_df,
)
from config import DEFAULT_PAGE
from controls import render_top_controls
from controller_services import (
    county_options,
    apply_admin_filters,
    compute_sold_cut_counts,
    build_rank_df,
    compute_gp_by_county,
)
from data import load_data, load_mao_tiers
from filters import Selection, build_view_df, compute_overall_stats
from geo import load_tn_geojson, build_county_adjacency
from map_view import render_map_and_details
from scoring import compute_health_score
from enrich import build_top_buyers_dict
from ui_sidebar import (
    render_team_view_toggle,
    render_overall_stats,
    render_rankings,
    render_acquisitions_guidance,
)


def run_app() -> None:
    st.set_page_config(**DEFAULT_PAGE)
    st.title("Closed RHD Properties Map")

    df = load_data()
    tiers = load_mao_tiers()

    tn_geo_for_adj = load_tn_geojson()
    adjacency = build_county_adjacency(tn_geo_for_adj)

    all_county_options, mao_tier_by_county, mao_range_by_county = county_options(df, tiers)

    # Sidebar view toggle
    team_view = render_team_view_toggle(default=st.session_state.get("team_view", "Dispo"))
    st.session_state["team_view"] = team_view

    if team_view == "Admin":
        require_sales_manager_auth()

    # Top controls
    controls = render_top_controls(team_view=team_view, df=df)

    mode = controls.mode
    year_choice = controls.year_choice
    buyer_choice = controls.buyer_choice
    buyer_active = controls.buyer_active
    dispo_rep_choice = controls.dispo_rep_choice
    rep_active = controls.rep_active

    # Year-filtered base frames
    df_time_sold_for_view = controls.fd.df_time_sold
    df_time_cut_for_view = controls.fd.df_time_cut

    # Dispo rep filter applies only to SOLD
    if team_view == "Dispo" and rep_active and "Dispo_Rep_clean" in df_time_sold_for_view.columns:
        df_time_sold_for_view = df_time_sold_for_view[df_time_sold_for_view["Dispo_Rep_clean"] == dispo_rep_choice]

    # Admin filters (market, reps)
    if team_view == "Admin":
        df_time_sold_for_view, df_time_cut_for_view = apply_admin_filters(
            df_time_sold_for_view,
            df_time_cut_for_view,
            market_choice=controls.market_choice,
            acq_rep_choice=controls.acq_rep_choice,
            dispo_rep_choice_admin=controls.dispo_rep_choice_admin,
        )

    # NEW: Admin-only GP per county for map tooltips
    gp_total_by_county: dict[str, float] = {}
    gp_avg_by_county: dict[str, float] = {}
    if team_view == "Admin":
        gp_total_by_county, gp_avg_by_county = compute_gp_by_county(
            df_time_sold_for_view[df_time_sold_for_view["Status_norm"] == "sold"]
            if "Status_norm" in df_time_sold_for_view.columns
            else df_time_sold_for_view
        )


    # Buyer context (sold-only)
    df_sold_buyers, buyer_count_by_county, buyers_set_by_county = compute_buyer_context_from_df(
        df_time_sold_for_view if team_view in ["Dispo", "Admin"] else controls.fd.df_time_sold
    )

    # Acquisitions sidebar
    render_acquisitions_sidebar(
        team_view=team_view,
        all_county_options=all_county_options,
        adjacency=adjacency,
        df_sold_buyers=df_sold_buyers,
        buyer_count_by_county=buyer_count_by_county,
        buyers_set_by_county=buyers_set_by_county,
        mao_tier_by_county=mao_tier_by_county,
        mao_range_by_county=mao_range_by_county,
        render_acquisitions_guidance=render_acquisitions_guidance,
    )

    # Build selection + df_view
    sel = Selection(
        mode=mode,
        year_choice=str(year_choice),
        buyer_choice=buyer_choice,
        buyer_active=buyer_active,
        top_n=10,
    )

    df_view = build_view_df(df_time_sold_for_view, df_time_cut_for_view, sel)

    # Dispo quick lookup
    render_dispo_county_quick_lookup(
        team_view=team_view,
        all_county_options=all_county_options,
        fd=controls.fd,
        df_time_sold_override=df_time_sold_for_view,
    )

    # Top buyers (sold only)
    top_buyers_dict = build_top_buyers_dict(df_time_sold_for_view if team_view == "Dispo" else controls.fd.df_time_sold)

    # Sold/cut counts + health
    sold_counts, cut_counts = compute_sold_cut_counts(
        df_time_sold_for_view,
        df_time_cut_for_view,
        team_view=team_view,
        rep_active=rep_active,
        dispo_rep_choice=dispo_rep_choice,
    )

    counties_for_health = sorted(set(list(sold_counts.keys()) + list(cut_counts.keys())))
    health_by_county = compute_health_score(counties_for_health, sold_counts, cut_counts)

    rank_df = build_rank_df(
        sold_counts=sold_counts,
        cut_counts=cut_counts,
        buyer_count_by_county=buyer_count_by_county,
        health_by_county=health_by_county,
    )

    # Rankings sidebar/table
    if team_view == "Dispo":
        render_rankings(
            rank_df[["County", "Health score", "Buyer count"]],
            default_rank_metric="Health score",
            rank_options=["Health score", "Buyer count"],
        )
    else:
        render_rankings(
            rank_df[["County", "Close rate", "Sold", "Total", "Cut loose"]],
            default_rank_metric="Close rate",
            rank_options=["Close rate", "Sold", "Total"],
        )

    # Overall stats (Dispo only)
    if team_view == "Dispo":
        stats = compute_overall_stats(df_time_sold_for_view, controls.fd.df_time_cut)
        render_overall_stats(
            year_choice=year_choice,
            sold_total=stats["sold_total"],
            cut_total=stats["cut_total"],
            total_deals=stats["total_deals"],
            total_buyers=stats["total_buyers"],
            close_rate_str=stats["close_rate_str"],
        )

    # Buyer sold counts by county (for buyer-active map tooltips)
    buyer_sold_counts: dict[str, int] = {}
    if buyer_active and mode in ["Sold", "Both"] and "Buyer_clean" in df_time_sold_for_view.columns:
        buyer_sold_counts = (
            df_time_sold_for_view[df_time_sold_for_view["Buyer_clean"] == buyer_choice]
            .groupby("County_clean_up")
            .size()
            .to_dict()
        )

    map_kwargs = dict(
        team_view=team_view,
        mode=mode,
        buyer_active=buyer_active,
        buyer_choice=buyer_choice,
        df_view=df_view,
        sold_counts=sold_counts,
        cut_counts=cut_counts,
        buyer_count_by_county=buyer_count_by_county,
        top_buyers_dict=top_buyers_dict,
        buyer_sold_counts=buyer_sold_counts,
        mao_tier_by_county=mao_tier_by_county,
        mao_range_by_county=mao_range_by_county,
        gp_total_by_county=gp_total_by_county,
        gp_avg_by_county=gp_avg_by_county,
    )

    # Admin: Dashboard + Map tabs. Others: Map only.
    if team_view == "Admin":
        render_admin_tabs(df_time_sold_for_view=df_time_sold_for_view, map_kwargs=map_kwargs)
    else:
        render_map_and_details(**map_kwargs)
