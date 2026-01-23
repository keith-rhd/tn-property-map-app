"""app_controller.py

Main orchestration for the Streamlit app.
Pure "wiring" that calls services + views.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from admin import require_sales_manager_auth
from admin_view import render_admin_tabs
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
    build_rank_df,
    compute_sold_cut_counts,
    county_options,
)
from data import load_data, load_mao_tiers
from enrich import build_top_buyers_dict
from filters import Selection, build_view_df, compute_overall_stats
from geo import build_county_adjacency, load_tn_geojson
from map_view import render_map_and_details
from scoring import compute_health_score
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

    # Admin-only metrics (compute ONCE; shared by tooltips + rankings)
    admin_rank_df = pd.DataFrame()
    gp_total_by_county: dict[str, float] = {}
    gp_avg_by_county: dict[str, float] = {}
    if team_view == "Admin":
        admin_rank_df, gp_total_by_county, gp_avg_by_county = build_admin_metrics(df_time_sold_for_view)

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
    top_buyers_dict = build_top_buyers_dict(
        df_time_sold_for_view if team_view == "Dispo" else controls.fd.df_time_sold
    )

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

    elif team_view == "Admin":
        if admin_rank_df.empty:
            st.sidebar.info("No Admin metrics available for current filters.")
        else:
            # Add display columns once, keep numeric columns for sorting
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
        # Acquisitions: rank counties by # of buyers (most buyers first)
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
