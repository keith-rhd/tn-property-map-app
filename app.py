import os
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from config import DEFAULT_PAGE, MAP_DEFAULTS, C
from data import load_data, load_mao_tiers
from geo import load_tn_geojson, build_county_adjacency
from scoring import compute_health_score
from filters import (
    Selection,
    prepare_filtered_data,
    build_buyer_labels,
    build_view_df,
    compute_overall_stats,
)
from map_build import build_map
from ui_sidebar import render_team_view_toggle, render_stats_card


# -----------------------------
# Sales Manager auth
# -----------------------------
def _get_sales_manager_password() -> str | None:
    # Prefer Streamlit Secrets (Streamlit Cloud)
    try:
        pw = st.secrets.get("sales_manager_password", None)
        if pw:
            return str(pw)
    except Exception:
        pass

    # Fallback to env var
    pw = os.environ.get("SALES_MANAGER_PASSWORD")
    return str(pw) if pw else None


def _require_sales_manager_auth():
    expected = _get_sales_manager_password()
    if not expected:
        st.sidebar.error(
            "Sales Manager password is not configured.\n\n"
            "Add `sales_manager_password` in Streamlit Secrets (recommended) "
            "or set env var `SALES_MANAGER_PASSWORD`."
        )
        st.stop()

    if st.session_state.get("sales_manager_authed") is True:
        return

    st.sidebar.markdown("## Sales Manager access")
    entered = st.sidebar.text_input("Password", type="password")

    if entered and entered == expected:
        st.session_state["sales_manager_authed"] = True
        st.sidebar.success("Unlocked.")
        return

    st.sidebar.info("Enter the Sales Manager password to continue.")
    st.stop()


# -----------------------------
# Dashboard helpers
# -----------------------------
def _add_quarter(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "Date_dt" in df.columns:
        q = df["Date_dt"].dt.to_period("Q").astype(str)
        df["Quarter"] = q
    else:
        df["Quarter"] = ""
    return df


def _safe_sum(series: pd.Series) -> float:
    try:
        return float(pd.to_numeric(series, errors="coerce").fillna(0).sum())
    except Exception:
        return 0.0


def render_sales_manager_dashboard(df_sold: pd.DataFrame):
    st.subheader("Financial dashboard")

    if df_sold is None or df_sold.empty:
        st.info("No SOLD deals found for the current filters.")
        return

    # Core metrics
    total_gp = _safe_sum(df_sold.get("Gross_Profit"))
    total_wholesale = _safe_sum(df_sold.get("Wholesale_Price_num"))
    sold_count = int(len(df_sold))
    avg_gp = total_gp / sold_count if sold_count else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Gross Profit (GP)", f"${total_gp:,.0f}")
    c2.metric("Total Wholesale Volume", f"${total_wholesale:,.0f}")
    c3.metric("Sold Deals", f"{sold_count:,}")
    c4.metric("Avg GP / Sold Deal", f"${avg_gp:,.0f}")

    st.divider()

    df_sold = _add_quarter(df_sold)

    # GP by quarter
    gp_by_q = (
        df_sold.groupby("Quarter", dropna=False)["Gross_Profit"]
        .sum(min_count=1)
        .sort_index()
    )
    st.markdown("#### GP by quarter")
    st.line_chart(gp_by_q)

    # Sold deals by quarter
    deals_by_q = (
        df_sold.groupby("Quarter", dropna=False)
        .size()
        .sort_index()
    )
    st.markdown("#### Sold deals by quarter")
    st.bar_chart(deals_by_q)

    # GP by Dispo Rep
    if "Dispo_Rep_clean" in df_sold.columns:
        gp_by_rep = (
            df_sold[df_sold["Dispo_Rep_clean"].astype(str).str.strip() != ""]
            .groupby("Dispo_Rep_clean")["Gross_Profit"]
            .sum(min_count=1)
            .sort_values(ascending=False)
            .head(15)
        )
        st.markdown("#### GP by Dispo Rep (top 15)")
        st.bar_chart(gp_by_rep)

    # In-area vs Out-of-area GP (based on Market)
    if "Market_clean" in df_sold.columns:
        market_gp = (
            df_sold[df_sold["Market_clean"].astype(str).str.strip() != ""]
            .groupby("Market_clean")["Gross_Profit"]
            .sum(min_count=1)
            .sort_values(ascending=False)
        )
        st.markdown("#### GP by Market")
        st.bar_chart(market_gp)

    st.caption("Next: we can add IA vs OOA deal flow, close rate by rep, discount rate (amended), and more.")


# -----------------------------
# App
# -----------------------------
st.set_page_config(**DEFAULT_PAGE)

df = load_data()
tiers = load_mao_tiers()

# Sidebar: choose view
team_view = render_team_view_toggle(default="Dispo")

# Sales Manager password gate
if team_view == "Sales Manager":
    _require_sales_manager_auth()

# Load geo
gdf_geo = load_tn_geojson()
adj = build_county_adjacency(gdf_geo)

st.title("TN Heatmap")

# -----------------------------
# Controls row (top)
# -----------------------------
col1, col2, col3, col4 = st.columns([1.2, 1.2, 1.6, 1.6], vertical_alignment="bottom")

with col1:
    mode = st.radio("View", ["Sold", "Cut Loose", "Both"], index=0, horizontal=True)

# Ensure Year is present
if "Year" not in df.columns and "Date_dt" in df.columns:
    df["Year"] = df["Date_dt"].dt.year

years_available = (
    sorted([int(y) for y in df["Year"].dropna().unique().tolist()])
    if "Year" in df.columns
    else []
)
with col2:
    year_choice = st.selectbox("Year", ["All years"] + years_available, index=0)

# Filtered data bundle
fd = prepare_filtered_data(df, year_choice)

# Default filter values
buyer_choice = "All buyers"
dispo_rep_choice = "All reps"
buyer_active = False
rep_active = False

# Extra filters depending on view
market_choice = "All markets"
acq_rep_choice = "All acquisition reps"

if team_view == "Dispo":
    # Buyer
    with col3:
        if mode in ["Sold", "Both"]:
            labels, label_to_buyer = build_buyer_labels(fd.buyer_momentum, fd.buyers_plain)
            chosen_label = st.selectbox("Buyer", labels, index=0)
            buyer_choice = label_to_buyer[chosen_label]
        else:
            buyer_choice = "All buyers"
            st.selectbox("Buyer", ["All buyers"], disabled=True)
    buyer_active = buyer_choice != "All buyers" and mode in ["Sold", "Both"]

    # Dispo Rep
    with col4:
        rep_values = []
        if mode in ["Sold", "Both"] and "Dispo_Rep_clean" in fd.df_time_sold.columns:
            rep_values = sorted(
                [
                    r for r in fd.df_time_sold["Dispo_Rep_clean"]
                    .dropna().astype(str).str.strip().unique().tolist()
                    if r
                ]
            )

        dispo_rep_choice = st.selectbox(
            "Dispo rep",
            ["All reps"] + rep_values,
            index=0,
            disabled=(mode == "Cut Loose"),
            key="dispo_rep_choice",
        )
    rep_active = (dispo_rep_choice != "All reps") and (mode in ["Sold", "Both"])

elif team_view == "Sales Manager":
    # Market + Acquisition Rep filters
    with col3:
        markets = []
        if "Market_clean" in df.columns:
            markets = sorted([m for m in df["Market_clean"].dropna().astype(str).str.strip().unique().tolist() if m])
        market_choice = st.selectbox("Market", ["All markets"] + markets, index=0)

    with col4:
        reps = []
        if "Acquisition_Rep_clean" in df.columns:
            reps = sorted([r for r in df["Acquisition_Rep_clean"].dropna().astype(str).str.strip().unique().tolist() if r])
        acq_rep_choice = st.selectbox("Acquisition Rep", ["All acquisition reps"] + reps, index=0)

else:
    # Acquisitions view: keep aligned layout
    with col3:
        st.selectbox("Buyer", ["All buyers"], disabled=True)
    with col4:
        st.selectbox("Dispo rep", ["All reps"], disabled=True, key="dispo_rep_choice")


TOP_N = 10

# -----------------------------
# SOLD dataframe respecting filters
# -----------------------------
df_time_sold_for_view = fd.df_time_sold.copy()
df_time_cut_for_view = fd.df_time_cut.copy()

# Dispo rep filter only in Dispo view
if team_view == "Dispo" and rep_active and "Dispo_Rep_clean" in df_time_sold_for_view.columns:
    df_time_sold_for_view = df_time_sold_for_view[df_time_sold_for_view["Dispo_Rep_clean"] == dispo_rep_choice]

# Sales Manager filters
if team_view == "Sales Manager":
    if market_choice != "All markets" and "Market_clean" in df_time_sold_for_view.columns:
        df_time_sold_for_view = df_time_sold_for_view[df_time_sold_for_view["Market_clean"] == market_choice]
        df_time_cut_for_view = df_time_cut_for_view[df_time_cut_for_view["Market_clean"] == market_choice]
    if acq_rep_choice != "All acquisition reps" and "Acquisition_Rep_clean" in df_time_sold_for_view.columns:
        df_time_sold_for_view = df_time_sold_for_view[df_time_sold_for_view["Acquisition_Rep_clean"] == acq_rep_choice]
        df_time_cut_for_view = df_time_cut_for_view[df_time_cut_for_view["Acquisition_Rep_clean"] == acq_rep_choice]

# Buyer filter affects the “view df” logic (only if active)
sel = Selection(
    mode=mode,
    year_choice=year_choice,
    buyer_choice=buyer_choice,
    buyer_active=buyer_active,
    top_n=TOP_N,
)

df_view = build_view_df(df_time_sold_for_view, df_time_cut_for_view, sel)

# Stats card (overall)
stats = compute_overall_stats(df_time_sold_for_view, df_time_cut_for_view)
render_stats_card(
    year_choice=year_choice,
    sold_total=int(stats.get("sold_total", 0)),
    cut_total=int(stats.get("cut_total", 0)),
    total_deals=int(stats.get("total_deals", 0)),
    total_buyers=int(stats.get("total_buyers", 0)),
    close_rate_str=str(stats.get("close_rate_str", "—")),
    title="Overall stats",
)

# Compute health score per county (existing behavior)
health_df = compute_health_score(df_view, tiers)

# -----------------------------
# Sales Manager: Tabs (Dashboard / Map)
# -----------------------------
if team_view == "Sales Manager":
    tab_dash, tab_map = st.tabs(["Dashboard", "Map"])

    with tab_dash:
        render_sales_manager_dashboard(df_time_sold_for_view[df_time_sold_for_view["Status_norm"] == "sold"])

    with tab_map:
        m = build_map(
            geo=gdf_geo,
            health_df=health_df,
            mao_tiers=tiers,
            defaults=MAP_DEFAULTS,
            team_view="Dispo",  # reuse map styling logic
        )
        st_folium(m, width=1100, height=650)
else:
    # Normal map behavior for Dispo/Acquisitions
    m = build_map(
        geo=gdf_geo,
        health_df=health_df,
        mao_tiers=tiers,
        defaults=MAP_DEFAULTS,
        team_view=team_view,
    )
    st_folium(m, width=1100, height=650)
