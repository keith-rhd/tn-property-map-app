"""app_controller.py

Main orchestration for the Streamlit app.

`app.py` should stay tiny and simply call `run_app()`.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from admin import require_sales_manager_auth, render_sales_manager_dashboard
from app_sections import (
    render_acquisitions_sidebar,
    render_dispo_county_quick_lookup,
    handle_map_click,
    render_below_map_panel,
    compute_buyer_context_from_df,
)
from controls import render_top_controls
from config import DEFAULT_PAGE, MAP_DEFAULTS
from data import load_data, load_mao_tiers
from geo import load_tn_geojson, build_county_adjacency
from scoring import compute_health_score
from filters import Selection, build_view_df, compute_overall_stats
from ui_sidebar import (
    render_team_view_toggle,
    render_overall_stats,
    render_rankings,
    render_acquisitions_guidance,
)
from enrich import (
    build_top_buyers_dict,
    build_county_properties_view,
    enrich_geojson_properties,
)
from map_build import build_map


def _county_options(df: pd.DataFrame, tiers: pd.DataFrame | None) -> tuple[list[str], dict[str, str], dict[str, str]]:
    """Return (all_county_options, mao_tier_by_county, mao_range_by_county)."""

    mao_tier_by_county: dict[str, str] = {}
    mao_range_by_county: dict[str, str] = {}

    tier_counties: list[str] = []
    if tiers is not None and not tiers.empty:
        mao_tier_by_county = dict(zip(tiers["County_clean_up"], tiers["MAO_Tier"]))
        mao_range_by_county = dict(zip(tiers["County_clean_up"], tiers["MAO_Range_Str"]))
        tier_counties = sorted(tiers["County_clean_up"].dropna().unique().tolist())

    deal_counties = sorted(df.get("County_clean_up", pd.Series(dtype=str)).dropna().unique().tolist())
    all_county_options = tier_counties if tier_counties else deal_counties

    return all_county_options, mao_tier_by_county, mao_range_by_county


def _apply_admin_filters(
    df_sold: pd.DataFrame,
    df_cut: pd.DataFrame,
    *,
    market_choice: str,
    acq_rep_choice: str,
    dispo_rep_choice_admin: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply Admin-only filters to the sold/cut frames."""

    df_sold_f = df_sold
    df_cut_f = df_cut

    if dispo_rep_choice_admin != "All reps" and "Dispo_Rep_clean" in df_sold_f.columns:
        df_sold_f = df_sold_f[df_sold_f["Dispo_Rep_clean"] == dispo_rep_choice_admin]
        if "Dispo_Rep_clean" in df_cut_f.columns:
            df_cut_f = df_cut_f[df_cut_f["Dispo_Rep_clean"] == dispo_rep_choice_admin]

    if market_choice != "All markets" and "Market_clean" in df_sold_f.columns:
        df_sold_f = df_sold_f[df_sold_f["Market_clean"] == market_choice]
        if "Market_clean" in df_cut_f.columns:
            df_cut_f = df_cut_f[df_cut_f["Market_clean"] == market_choice]

    if acq_rep_choice != "All acquisition reps" and "Acquisition_Rep_clean" in df_sold_f.columns:
        df_sold_f = df_sold_f[df_sold_f["Acquisition_Rep_clean"] == acq_rep_choice]
        if "Acquisition_Rep_clean" in df_cut_f.columns:
            df_cut_f = df_cut_f[df_cut_f["Acquisition_Rep_clean"] == acq_rep_choice]

    return df_sold_f, df_cut_f


def _compute_sold_cut_counts(
    df_sold_for_view: pd.DataFrame,
    df_cut_for_view: pd.DataFrame,
    *,
    team_view: str,
    rep_active: bool,
    dispo_rep_choice: str,
) -> tuple[dict[str, int], dict[str, int]]:
    """Compute county sold/cut counts; Dispo rep filter applies only to SOLD."""

    if df_sold_for_view is None:
        df_sold_for_view = pd.DataFrame()
    if df_cut_for_view is None:
        df_cut_for_view = pd.DataFrame()

    df_conv = pd.concat([df_sold_for_view, df_cut_for_view], ignore_index=True)

    if team_view == "Dispo" and rep_active and "Dispo_Rep_clean" in df_conv.columns:
        df_conv = df_conv[(df_conv["Status_norm"] != "sold") | (df_conv["Dispo_Rep_clean"] == dispo_rep_choice)]

    grp = df_conv.groupby("County_clean_up")
    sold_counts = grp.apply(lambda g: (g["Status_norm"] == "sold").sum()).to_dict()
    cut_counts = grp.apply(lambda g: (g["Status_norm"] == "cut loose").sum()).to_dict()
    return sold_counts, cut_counts


def _render_map_and_details(
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
) -> None:
    """Build + render the Folium map and the below-map panel."""

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


def run_app() -> None:
    st.set_page_config(**DEFAULT_PAGE)

    st.title("Closed RHD Properties Map")

    df = load_data()
    tiers = load_mao_tiers()

    tn_geo_for_adj = load_tn_geojson()
    adjacency = build_county_adjacency(tn_geo_for_adj)

    all_county_options, mao_tier_by_county, mao_range_by_county = _county_options(df, tiers)

    # Sidebar: Team view toggle
    team_view = render_team_view_toggle(default=st.session_state.get("team_view", "Dispo"))
    st.session_state["team_view"] = team_view

    if team_view == "Admin":
        require_sales_manager_auth()

    # Top row controls
    controls = render_top_controls(team_view=team_view, df=df)

    mode = controls.mode
    year_choice = controls.year_choice
    buyer_choice = controls.buyer_choice
    buyer_active = controls.buyer_active
    dispo_rep_choice = controls.dispo_rep_choice
    rep_active = controls.rep_active

    # Start from year-filtered sold/cut
    df_time_sold_for_view = controls.fd.df_time_sold
    df_time_cut_for_view = controls.fd.df_time_cut

    # Dispo rep filter applies to SOLD only
    if team_view == "Dispo" and rep_active and "Dispo_Rep_clean" in df_time_sold_for_view.columns:
        df_time_sold_for_view = df_time_sold_for_view[df_time_sold_for_view["Dispo_Rep_clean"] == dispo_rep_choice]

    # Admin filters (market, reps)
    if team_view == "Admin":
        df_time_sold_for_view, df_time_cut_for_view = _apply_admin_filters(
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

    # Build selection + view df
    sel = Selection(
        mode=mode,
        year_choice=str(year_choice),
        buyer_choice=buyer_choice,
        buyer_active=buyer_active,
        top_n=10,
    )

    df_view = build_view_df(df_time_sold_for_view, df_time_cut_for_view, sel)

    # Dispo quick lookup (rep-aware)
    render_dispo_county_quick_lookup(
        team_view=team_view,
        all_county_options=all_county_options,
        fd=controls.fd,
        df_time_sold_override=df_time_sold_for_view,
    )

    # Top buyers dict (sold only)
    top_buyers_dict = build_top_buyers_dict(df_time_sold_for_view if team_view == "Dispo" else controls.fd.df_time_sold)

    # County totals + health
    sold_counts, cut_counts = _compute_sold_cut_counts(
        df_time_sold_for_view,
        df_time_cut_for_view,
        team_view=team_view,
        rep_active=rep_active,
        dispo_rep_choice=dispo_rep_choice,
    )

    counties_for_health = sorted(set(list(sold_counts.keys()) + list(cut_counts.keys())))
    health = compute_health_score(counties_for_health, sold_counts, cut_counts)

    rank_rows: list[dict] = []
    for c in counties_for_health:
        sold = int(sold_counts.get(c, 0))
        cut = int(cut_counts.get(c, 0))
        total = sold + cut
        close_rate = (sold / total) if total else 0.0
        rank_rows.append(
            {
                "County": c.title(),
                "Sold": sold,
                "Cut loose": cut,
                "Total": total,
                "Buyer count": int(buyer_count_by_county.get(c, 0)),
                "Health score": round(float(health.get(c, 0.0)), 3),
                "Close rate": round(close_rate * 100, 1),
            }
        )

    rank_df = pd.DataFrame(rank_rows)

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

    # Buyer county counts (only when filtering by a buyer in Dispo)
    buyer_sold_counts: dict[str, int] = {}
    if buyer_active and mode in ["Sold", "Both"] and "Buyer_clean" in df_time_sold_for_view.columns:
        buyer_sold_counts = (
            df_time_sold_for_view[df_time_sold_for_view["Buyer_clean"] == buyer_choice]
            .groupby("County_clean_up")
            .size()
            .to_dict()
        )

    if team_view == "Admin":
        tab_dash, tab_map = st.tabs(["Dashboard", "Map"])

        with tab_dash:
            render_sales_manager_dashboard(
                df_time_sold_for_view[df_time_sold_for_view["Status_norm"] == "sold"]
            )

        with tab_map:
            _render_map_and_details(
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
            )
    else:
        _render_map_and_details(
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
        )
