"""app_controller.py

Main orchestration for the Streamlit app.
Pure "wiring" that calls services + views.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from admin import require_sales_manager_auth
from views.admin_view import render_admin_tabs
from views.acquisitions_view import render_acquisitions_tabs
from app_sections import (
    compute_buyer_context_from_df,
    render_acquisitions_sidebar,
    render_dispo_county_quick_lookup,
)
from config import DEFAULT_PAGE
from controls import render_top_controls
from controller_services import (
    apply_admin_filters,
    build_admin_metrics,
    build_county_gp_table,
    build_rank_df,
    compute_admin_headline_metrics,
    compute_sold_cut_counts,
    county_options,
)
from data import load_data, load_mao_tiers
from enrich import build_top_buyers_dict
from filters import Selection, build_view_df, compute_overall_stats
from geo import build_county_adjacency, load_tn_geojson
from map_view import render_map_and_details
from scoring import compute_health_score
from debug_tools import debug_event, render_debug_panel
from ui_sidebar import (
    render_acquisitions_guidance,
    render_overall_stats,
    render_rankings,
    render_team_view_toggle,
)


def fmt_dollars_short(x: float) -> str:
    """Format dollars like $39K / $3.18M / $950."""
    try:
        x = float(x)
    except Exception:
        return "$0"

    if abs(x) >= 1_000_000:
        return f"${x/1_000_000:.2f}M"
    if abs(x) >= 1_000:
        return f"${x/1_000:.0f}K"
    return f"${x:,.0f}"


def run_app() -> None:
    st.set_page_config(**DEFAULT_PAGE)
    st.title("RHD Deal Intelligence")
    render_debug_panel()

    df = load_data()
    tiers = load_mao_tiers()

    tn_geo_for_adj = load_tn_geojson()
    adjacency = build_county_adjacency(tn_geo_for_adj)
    st.session_state["county_adjacency"] = adjacency

    all_county_options, mao_tier_by_county, mao_range_by_county = county_options(df, tiers)

    team_view = render_team_view_toggle(default=st.session_state.get("team_view", "Dispo"))

    debug_event("data_loaded", rows=int(len(df)) if df is not None else 0, cols=list(df.columns) if df is not None else [])
    debug_event("mao_tiers_loaded", rows=int(len(tiers)) if tiers is not None else 0)

    if team_view == "Admin":
        require_sales_manager_auth()

    controls = render_top_controls(team_view=team_view, df=df)

    mode = controls.mode
    year_choice = controls.year_choice
    buyer_choice = controls.buyer_choice
    buyer_active = controls.buyer_active
    dispo_rep_choice = controls.dispo_rep_choice
    rep_active = controls.rep_active

    acq_rep_active = controls.acq_rep_active
    acq_rep_choice = controls.dispo_acq_rep_choice


    df_time_sold_for_view = controls.fd.df_time_sold
    df_time_cut_for_view = controls.fd.df_time_cut

    # Dispo rep filter applies to SOLD (and CUT for sidebar totals + rep-specific view)
    if team_view == "Dispo" and rep_active:
        if "Dispo_Rep_clean" in df_time_sold_for_view.columns:
            df_time_sold_for_view = df_time_sold_for_view[
                df_time_sold_for_view["Dispo_Rep_clean"] == dispo_rep_choice
            ]
        if "Dispo_Rep_clean" in df_time_cut_for_view.columns:
            df_time_cut_for_view = df_time_cut_for_view[
                df_time_cut_for_view["Dispo_Rep_clean"] == dispo_rep_choice
            ]


    # Dispo: Acquisition Rep filter applies to BOTH sold + cut
    if team_view == "Dispo" and acq_rep_active:
        if "Acquisition_Rep_clean" in df_time_sold_for_view.columns:
            df_time_sold_for_view = df_time_sold_for_view[
                df_time_sold_for_view["Acquisition_Rep_clean"] == acq_rep_choice
            ]
        if "Acquisition_Rep_clean" in df_time_cut_for_view.columns:
            df_time_cut_for_view = df_time_cut_for_view[
                df_time_cut_for_view["Acquisition_Rep_clean"] == acq_rep_choice
            ]


    # Admin filters (market, reps)
    if team_view == "Admin":
        df_time_sold_for_view, df_time_cut_for_view = apply_admin_filters(
            df_time_sold_for_view,
            df_time_cut_for_view,
            market_choice=controls.market_choice,
            acq_rep_choice=controls.acq_rep_choice,
            dispo_rep_choice_admin=controls.dispo_rep_choice_admin,
        )

    # Admin-only metrics (compute ONCE; shared by tooltips + rankings)
    admin_rank_df = pd.DataFrame()
    gp_total_by_county: dict[str, float] = {}
    gp_avg_by_county: dict[str, float] = {}
    admin_dashboard_headline: dict = {}
    admin_county_gp_table = pd.DataFrame()
    admin_sold_only = pd.DataFrame()

    if team_view == "Admin":
        # Sold-only frame for Admin dashboard
        admin_sold_only = (
            df_time_sold_for_view[df_time_sold_for_view["Status_norm"] == "sold"]
            if "Status_norm" in df_time_sold_for_view.columns
            else df_time_sold_for_view
        )

        admin_rank_df, gp_total_by_county, gp_avg_by_county = build_admin_metrics(df_time_sold_for_view)

        # Option B: precompute dashboard headline + county table once
        admin_dashboard_headline = compute_admin_headline_metrics(admin_sold_only)
        admin_county_gp_table = build_county_gp_table(admin_sold_only)

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

    rank_df = build_rank_df(
        sold_counts=sold_counts,
        cut_counts=cut_counts,
        buyer_count_by_county=buyer_count_by_county,
        health_by_county=health_by_county,
    )

    # Rankings sidebar/table
    if team_view == "Dispo":
        pass  # Dispo: sidebar rankings removed

    elif team_view == "Admin":
        if admin_rank_df.empty:
            st.sidebar.info("No Admin metrics available for current filters.")
        else:
            admin_rank_df = admin_rank_df.copy()
            admin_rank_df["Total GP ($)"] = admin_rank_df["Total GP"].apply(fmt_dollars_short)
            admin_rank_df["Avg GP ($)"] = admin_rank_df["Avg GP"].apply(fmt_dollars_short)

            render_rankings(
                admin_rank_df[["County", "Total GP ($)", "Avg GP ($)", "Sold Deals", "Total GP", "Avg GP"]],
                default_rank_metric="Total GP ($)",
                rank_options=["Total GP ($)", "Avg GP ($)", "Sold Deals"],
                sort_by_map={"Total GP ($)": "Total GP", "Avg GP ($)": "Avg GP"},
            )

    else:
        acq_rows = []
        for county_up, buyer_ct in (buyer_count_by_county or {}).items():
            acq_rows.append({"County": str(county_up).title(), "Buyer count": int(buyer_ct or 0)})

        acq_rank_df = pd.DataFrame(acq_rows)

        if acq_rank_df.empty:
            st.sidebar.info("No buyer counts available for current filters.")
        else:
            render_rankings(
                acq_rank_df[["County", "Buyer count"]],
                default_rank_metric="Buyer count",
                rank_options=["Buyer count"],
            )

    if team_view == "Dispo":
        stats = compute_overall_stats(df_time_sold_for_view, df_time_cut_for_view)
        render_overall_stats(
            year_choice=year_choice,
            sold_total=stats["sold_total"],
            cut_total=stats["cut_total"],
            total_deals=stats["total_deals"],
            total_buyers=stats["total_buyers"],
            close_rate_str=stats["close_rate_str"],
        )

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

    if team_view == "Admin":
        render_admin_tabs(
            df_sold_only_for_dashboard=admin_sold_only,
            dashboard_headline=admin_dashboard_headline,
            county_gp_table=admin_county_gp_table,
            map_kwargs=map_kwargs,
        )
    elif team_view == "Acquisitions":
        render_acquisitions_tabs(
            df_time_sold_for_view=df_time_sold_for_view,
            df_time_cut_for_view=df_time_cut_for_view,
            map_kwargs=map_kwargs,
        )
    else:
        render_map_and_details(**map_kwargs)
