from __future__ import annotations

import pandas as pd
import streamlit as st

from app_sections import (
    compute_buyer_context_from_df,
    render_acquisitions_sidebar,
    render_dispo_county_quick_lookup,
)
from controls import render_top_controls
from controller_services import (
    apply_admin_filters,
    build_admin_metrics,
    build_county_gp_table,
    compute_admin_headline_metrics,
    compute_health_score,
    compute_sold_cut_counts,
    county_options,
    fmt_dollars_short,
    load_data,
    load_mao_tiers,
    load_tn_geojson,
    render_acquisitions_guidance,
    render_rankings,
    render_team_view_toggle,
    require_sales_manager_auth,
)
from enrich import build_top_buyers_dict
from filters import Selection, build_view_df
from geo import build_county_adjacency
from map_view import render_map_and_details
from config import DEFAULT_PAGE


def run_app() -> None:
    st.set_page_config(**DEFAULT_PAGE)
    st.title("Closed RHD Properties Map")

    df = load_data()
    tiers = load_mao_tiers()

    tn_geo_for_adj = load_tn_geojson()
    adjacency = build_county_adjacency(tn_geo_for_adj)

    all_county_options, mao_tier_by_county, mao_range_by_county = county_options(df, tiers)

    team_view = render_team_view_toggle(default=st.session_state.get("team_view", "Dispo"))

    if team_view == "Admin":
        require_sales_manager_auth()

    controls = render_top_controls(team_view=team_view, df=df)

    mode = controls.mode
    year_choice = controls.year_choice
    buyer_choice = controls.buyer_choice
    buyer_active = controls.buyer_active

    dispo_rep_choice = controls.dispo_rep_choice
    rep_active = controls.rep_active

    acq_rep_choice = controls.acq_rep_choice
    acq_rep_active = controls.acq_rep_active

    df_time_sold_for_view = controls.fd.df_time_sold
    df_time_cut_for_view = controls.fd.df_time_cut

    # ----------------------------
    # Dispo filters
    # ----------------------------

    # Dispo rep filter applies only to SOLD
    if team_view == "Dispo" and rep_active and "Dispo_Rep_clean" in df_time_sold_for_view.columns:
        df_time_sold_for_view = df_time_sold_for_view[df_time_sold_for_view["Dispo_Rep_clean"] == dispo_rep_choice]

    # Acquisition rep filter applies to BOTH sold + cut
    if team_view == "Dispo" and acq_rep_active and "Acquisition_Rep_clean" in df_time_sold_for_view.columns:
        df_time_sold_for_view = df_time_sold_for_view[df_time_sold_for_view["Acquisition_Rep_clean"] == acq_rep_choice]
    if team_view == "Dispo" and acq_rep_active and "Acquisition_Rep_clean" in df_time_cut_for_view.columns:
        df_time_cut_for_view = df_time_cut_for_view[df_time_cut_for_view["Acquisition_Rep_clean"] == acq_rep_choice]

    # ----------------------------
    # Admin filters (market, reps)
    # ----------------------------
    if team_view == "Admin":
        df_time_sold_for_view, df_time_cut_for_view = apply_admin_filters(
            df_time_sold_for_view,
            df_time_cut_for_view,
            market_choice=controls.market_choice,
            acq_rep_choice=controls.acq_rep_choice,
            dispo_rep_choice_admin=controls.dispo_rep_choice_admin,
        )

    # Buyer context (sold-only)
    df_sold_buyers, buyer_count_by_county, buyers_set_by_county = compute_buyer_context_from_df(
        df_time_sold_for_view if team_view in ["Dispo", "Admin"] else controls.fd.df_time_sold
    )

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

    sel = Selection(
        mode=mode,
        year_choice=str(year_choice),
        buyer_choice=buyer_choice,
        buyer_active=buyer_active,
        top_n=10,
    )

    df_view = build_view_df(df_time_sold_for_view, df_time_cut_for_view, sel)

    # Dispo county sidebar stats should respect Dispo filters, so pass both overrides
    render_dispo_county_quick_lookup(
        team_view=team_view,
        all_county_options=all_county_options,
        fd=controls.fd,
        df_time_sold_override=df_time_sold_for_view,
        df_time_cut_override=df_time_cut_for_view,
    )

    top_buyers_dict = build_top_buyers_dict(
        df_time_sold_for_view if team_view == "Dispo" else controls.fd.df_time_sold
    )

    sold_counts, cut_counts = compute_sold_cut_counts(
        df_time_sold_for_view,
        df_time_cut_for_view,
        team_view=team_view,
        rep_active=rep_active,
        dispo_rep_choice=dispo_rep_choice,
    )

    counties_for_health = sorted(set(list(sold_counts.keys()) + list(cut_counts.keys())))
    health_by_county = compute_health_score(counties_for_health, sold_counts, cut_counts)

    # (rest of your file continues unchanged)
    render_map_and_details(
        df_view=df_view,
        fd=controls.fd,
        team_view=team_view,
        all_county_options=all_county_options,
        top_buyers_dict=top_buyers_dict,
        buyer_count_by_county=buyer_count_by_county,
        buyers_set_by_county=buyers_set_by_county,
        adjacency=adjacency,
        mao_tier_by_county=mao_tier_by_county,
        mao_range_by_county=mao_range_by_county,
        sold_counts=sold_counts,
        cut_counts=cut_counts,
        health_by_county=health_by_county,
    )
