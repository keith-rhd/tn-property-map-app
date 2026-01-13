import os
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
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

from app_sections import (
    render_acquisitions_sidebar,
    render_dispo_county_quick_lookup,
    handle_map_click,
    render_below_map_panel,
)

from map_build import build_map

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
            "Add `sales_manager_password` in Streamlit Secrets "
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
# Sales Manager dashboard
# -----------------------------
def _safe_sum(series) -> float:
    try:
        return float(pd.to_numeric(series, errors="coerce").fillna(0).sum())
    except Exception:
        return 0.0


def _add_quarter(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "Date_dt" in df.columns:
        df["Quarter"] = df["Date_dt"].dt.to_period("Q").astype(str)
    else:
        df["Quarter"] = ""
    return df


def render_sales_manager_dashboard(df_sold: pd.DataFrame):
    st.subheader("Financial dashboard")

    if df_sold is None or df_sold.empty:
        st.info("No SOLD deals found for the current filters.")
        return

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

    st.markdown("#### GP by quarter")
    gp_by_q = df_sold.groupby("Quarter")["Gross_Profit"].sum().sort_index()
    st.line_chart(gp_by_q)

    st.markdown("#### Sold deals by quarter")
    deals_by_q = df_sold.groupby("Quarter").size().sort_index()
    st.bar_chart(deals_by_q)

    if "Dispo_Rep_clean" in df_sold.columns:
        st.markdown("#### GP by Dispo Rep (share of total, top 10)")

        gp_by_rep = (
            df_sold[df_sold["Dispo_Rep_clean"].astype(str).str.strip() != ""]
            .groupby("Dispo_Rep_clean")["Gross_Profit"]
            .sum()
            .sort_values(ascending=False)
    )

    # Keep pie readable: show top 10 + bucket the rest as "Other"
    top_n = 10
    if len(gp_by_rep) > top_n:
        top = gp_by_rep.head(top_n)
        other = gp_by_rep.iloc[top_n:].sum()
        gp_by_rep_plot = pd.concat([top, pd.Series({"Other": other})])
    else:
        gp_by_rep_plot = gp_by_rep

    # Remove non-positive values (pies get weird with negatives/zeros)
    gp_by_rep_plot = gp_by_rep_plot[gp_by_rep_plot > 0]

    if gp_by_rep_plot.empty:
        st.info("Not enough positive GP values to display a pie chart for Dispo Reps.")
    else:
        fig, ax = plt.subplots()
        ax.pie(gp_by_rep_plot.values, labels=gp_by_rep_plot.index, autopct="%1.1f%%", startangle=90)
        ax.axis("equal")
        st.pyplot(fig)


    if "Market_clean" in df_sold.columns:
        st.markdown("#### GP by Market (share of total)")

        gp_by_mkt = (
            df_sold[df_sold["Market_clean"].astype(str).str.strip() != ""]
            .groupby("Market_clean")["Gross_Profit"]
            .sum()
            .sort_values(ascending=False)
    )

    # Bucket small slices into "Other" if there are many markets
    top_n = 8
    if len(gp_by_mkt) > top_n:
        top = gp_by_mkt.head(top_n)
        other = gp_by_mkt.iloc[top_n:].sum()
        gp_by_mkt_plot = pd.concat([top, pd.Series({"Other": other})])
    else:
        gp_by_mkt_plot = gp_by_mkt

    gp_by_mkt_plot = gp_by_mkt_plot[gp_by_mkt_plot > 0]

    if gp_by_mkt_plot.empty:
        st.info("Not enough positive GP values to display a pie chart for Markets.")
    else:
        fig, ax = plt.subplots()
        ax.pie(gp_by_mkt_plot.values, labels=gp_by_mkt_plot.index, autopct="%1.1f%%", startangle=90)
        ax.axis("equal")
        st.pyplot(fig)

def init_state():
    """
    Central place for Streamlit session-state defaults.
    Keeps state keys consistent and prevents regressions when the app grows.
    """
    placeholder = "— Select a county —"
    defaults = {
        "team_view": "Dispo",
        "selected_county": "",
        "acq_selected_county": "",
        "county_source": "",  # "map" | "dropdown" | ""
        "last_map_clicked_county": "",
        "dispo_county_lookup": placeholder,
        "_dispo_prev_county_lookup": placeholder,
        # Dispo Rep filter memory (optional)
        "dispo_rep_choice": "All reps",
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


st.set_page_config(**DEFAULT_PAGE)
init_state()

st.title("Closed RHD Properties Map")

df = load_data()

# -----------------------------
# HARDENING: ensure Date is datetime so Year logic won't break
# -----------------------------
if hasattr(C, "date") and C.date in df.columns:
    df[C.date] = pd.to_datetime(df[C.date], errors="coerce")

if "Year" not in df.columns:
    if hasattr(C, "date") and C.date in df.columns:
        df["Year"] = df[C.date].dt.year

if "Year" in df.columns:
    df["Year"] = pd.to_numeric(df["Year"], errors="coerce")

tiers = load_mao_tiers()

# Geo + adjacency
tn_geo_for_adj = load_tn_geojson()
adjacency = build_county_adjacency(tn_geo_for_adj)

# Tier mappings
mao_tier_by_county = {}
mao_range_by_county = {}
tier_counties = []

if tiers is not None and not tiers.empty:
    mao_tier_by_county = dict(zip(tiers["County_clean_up"], tiers["MAO_Tier"]))
    mao_range_by_county = dict(zip(tiers["County_clean_up"], tiers["MAO_Range_Str"]))
    tier_counties = sorted(tiers["County_clean_up"].dropna().unique().tolist())

deal_counties = sorted(df["County_clean_up"].dropna().unique().tolist())
all_county_options = tier_counties if tier_counties else deal_counties

# -----------------------------
# Sidebar: Team view toggle
# -----------------------------
team_view = render_team_view_toggle(default=st.session_state.get("team_view", "Dispo"))
st.session_state["team_view"] = team_view

if team_view == "Sales Manager":
    _require_sales_manager_auth()

# -----------------------------
# Controls row (top)
# -----------------------------
if team_view == "Sales Manager":
    col1, col2, col3, col4, col5 = st.columns([1.0, 1.4, 1.4, 1.5, 1.3], gap="small")
else:
    col1, col2, col3, col4 = st.columns([1.1, 1.6, 1.7, 1.4], gap="small")

# --- View ---
with col1:
    mode = st.radio("View", ["Sold", "Cut Loose", "Both"], index=0, horizontal=True)

# --- Year ---
years_available = (
    sorted([int(y) for y in df["Year"].dropna().unique().tolist()])
    if "Year" in df.columns
    else []
)
with col2:
    year_choice = st.selectbox("Year", ["All years"] + years_available, index=0)

# Filtered data bundle (immutable dataclass-ish object)
fd = prepare_filtered_data(df, year_choice)

# -------------------------------------------------
# Buyer + Dispo Rep controls (Dispo only)
# -------------------------------------------------
rep_active = False
dispo_rep_choice = "All reps"

market_choice = "All markets"
acq_rep_choice = "All acquisition reps"

if team_view == "Dispo":

    # --- Buyer filter ---
    with col3:
        if mode in ["Sold", "Both"]:
            labels, label_to_buyer = build_buyer_labels(fd.buyer_momentum, fd.buyers_plain)
            chosen_label = st.selectbox("Buyer", labels, index=0)
            buyer_choice = label_to_buyer[chosen_label]
        else:
            buyer_choice = "All buyers"
            st.selectbox("Buyer", ["All buyers"], disabled=True)

    buyer_active = buyer_choice != "All buyers" and mode in ["Sold", "Both"]

    # --- Dispo Rep filter ---
    with col4:
        rep_values = []
        if mode in ["Sold", "Both"] and "Dispo_Rep_clean" in fd.df_time_sold.columns:
            rep_values = sorted(
                [
                    r for r in fd.df_time_sold["Dispo_Rep_clean"]
                    .dropna()
                    .astype(str)
                    .str.strip()
                    .unique()
                    .tolist()
                    if r
                ]
            )

        dispo_rep_choice = st.selectbox(
            "Dispo rep",
            ["All reps"] + rep_values,
            index=0
            if st.session_state.get("dispo_rep_choice", "All reps") == "All reps"
            else (["All reps"] + rep_values).index(st.session_state.get("dispo_rep_choice", "All reps"))
            if st.session_state.get("dispo_rep_choice", "All reps") in (["All reps"] + rep_values)
            else 0,
            disabled=(mode == "Cut Loose"),
            key="dispo_rep_choice",
        )

        rep_active = (dispo_rep_choice != "All reps") and (mode in ["Sold", "Both"])

elif team_view == "Sales Manager":
    # Sales Manager: all filters on the top row
    with col3:
        markets = []
        if "Market_clean" in df.columns:
            markets = sorted([m for m in df["Market_clean"].dropna().astype(str).str.strip().unique().tolist() if m])
        market_choice = st.selectbox("Market", ["All markets"] + markets, index=0)

    with col4:
        acq_reps = []
        if "Acquisition_Rep_clean" in df.columns:
            acq_reps = sorted([r for r in df["Acquisition_Rep_clean"].dropna().astype(str).str.strip().unique().tolist() if r])
        acq_rep_choice = st.selectbox("Acquisition Rep", ["All acquisition reps"] + acq_reps, index=0)

    with col5:
        dispo_reps = []
        if "Dispo_Rep_clean" in df.columns:
            dispo_reps = sorted([r for r in df["Dispo_Rep_clean"].dropna().astype(str).str.strip().unique().tolist() if r])
        dispo_rep_choice_sm = st.selectbox("Dispo rep", ["All reps"] + dispo_reps, index=0)

    buyer_choice = "All buyers"
    buyer_active = False
    rep_active = False
    dispo_rep_choice = "All reps"  # keep stable for other logic

else:
    with col3:
        buyer_choice = "All buyers"
        st.selectbox("Buyer", ["All buyers"], disabled=True)

    with col4:
        dispo_rep_choice = "All reps"
        st.selectbox("Dispo rep", ["All reps"], disabled=True, key="dispo_rep_choice")

    buyer_active = False
    rep_active = False
    dispo_rep_choice = "All reps"
    dispo_rep_choice_sm = "All reps"

TOP_N = 10

# -------------------------------------------------
# SOLD dataframe respecting Dispo Rep filter
# (Cut loose remains unchanged)
# -------------------------------------------------
df_time_sold_for_view = fd.df_time_sold
if team_view == "Dispo" and rep_active and "Dispo_Rep_clean" in df_time_sold_for_view.columns:
    df_time_sold_for_view = df_time_sold_for_view[
        df_time_sold_for_view["Dispo_Rep_clean"] == dispo_rep_choice
    ]

df_time_cut_for_view = fd.df_time_cut

if team_view == "Sales Manager":
    if dispo_rep_choice_sm != "All reps" and "Dispo_Rep_clean" in df_time_sold_for_view.columns:
        df_time_sold_for_view = df_time_sold_for_view[df_time_sold_for_view["Dispo_Rep_clean"] == dispo_rep_choice_sm]
        if "df_time_cut_for_view" in globals() and "Dispo_Rep_clean" in df_time_cut_for_view.columns:
            df_time_cut_for_view = df_time_cut_for_view[df_time_cut_for_view["Dispo_Rep_clean"] == dispo_rep_choice_sm]

if team_view == "Sales Manager":
    if market_choice != "All markets" and "Market_clean" in df_time_sold_for_view.columns:
        df_time_sold_for_view = df_time_sold_for_view[df_time_sold_for_view["Market_clean"] == market_choice]
        df_time_cut_for_view = df_time_cut_for_view[df_time_cut_for_view["Market_clean"] == market_choice]

    if acq_rep_choice != "All acquisition reps" and "Acquisition_Rep_clean" in df_time_sold_for_view.columns:
        df_time_sold_for_view = df_time_sold_for_view[df_time_sold_for_view["Acquisition_Rep_clean"] == acq_rep_choice]
        df_time_cut_for_view = df_time_cut_for_view[df_time_cut_for_view["Acquisition_Rep_clean"] == acq_rep_choice]

# -------------------------------------------------
# Buyer context (sold-only)
#  - In Dispo: respects rep filter
#  - In Acq: uses full sold data (rep filter off anyway)
# -------------------------------------------------
df_sold_buyers = df_time_sold_for_view.copy() if team_view in ["Dispo", "Sales Manager"] else fd.df_time_sold.copy()
if "Buyer_clean" in df_sold_buyers.columns:
    df_sold_buyers["Buyer_clean"] = df_sold_buyers["Buyer_clean"].astype(str).str.strip()
else:
    df_sold_buyers["Buyer_clean"] = ""

buyer_count_by_county = (
    df_sold_buyers[df_sold_buyers["Buyer_clean"] != ""]
    .groupby("County_clean_up")["Buyer_clean"]
    .nunique()
    .to_dict()
)

buyers_set_by_county = (
    df_sold_buyers[df_sold_buyers["Buyer_clean"] != ""]
    .groupby("County_clean_up")["Buyer_clean"]
    .apply(lambda s: set(s.dropna().tolist()))
    .to_dict()
)

# -----------------------------
# Acquisitions sidebar
# -----------------------------
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

# -----------------------------
# Build selection + view df
# -----------------------------
sel = Selection(
    mode=mode,
    year_choice=str(year_choice),
    buyer_choice=buyer_choice,
    buyer_active=buyer_active,
    top_n=int(TOP_N),
)

# IMPORTANT: pass rep-filtered SOLD df into build_view_df so the table/map respect Dispo rep
df_view = build_view_df(
    df_time_sold_for_view,
    df_time_cut_for_view if "df_time_cut_for_view" in globals() else fd.df_time_cut,
    sel
)
# -----------------------------
# Dispo: County quick lookup (rep-aware via override)
# -----------------------------
render_dispo_county_quick_lookup(
    team_view=team_view,
    all_county_options=all_county_options,
    fd=fd,
    df_time_sold_override=df_time_sold_for_view,
)

# -----------------------------
# Top buyers dict (sold only, rep-aware on Dispo)
# -----------------------------
top_buyers_dict = build_top_buyers_dict(df_time_sold_for_view if team_view == "Dispo" else fd.df_time_sold)

# -----------------------------
# County totals for sold/cut
# (rep filter applies ONLY to sold rows in Dispo)
# -----------------------------
# Build conversion base using filtered sold/cut if available
if "df_time_cut_for_view" in globals():
    df_conv = pd.concat([df_time_sold_for_view, df_time_cut_for_view], ignore_index=True)
else:
    df_conv = fd.df_time_filtered[fd.df_time_filtered["Status_norm"].isin(["sold", "cut loose"])]

if team_view == "Dispo" and rep_active and "Dispo_Rep_clean" in df_conv.columns:
    df_conv = df_conv[(df_conv["Status_norm"] != "sold") | (df_conv["Dispo_Rep_clean"] == dispo_rep_choice)]

grp = df_conv.groupby("County_clean_up")
sold_counts = grp.apply(lambda g: (g["Status_norm"] == "sold").sum()).to_dict()
cut_counts = grp.apply(lambda g: (g["Status_norm"] == "cut loose").sum()).to_dict()

counties_for_health = sorted(set(list(sold_counts.keys()) + list(cut_counts.keys())))
health = compute_health_score(counties_for_health, sold_counts, cut_counts)

# Rankings
rows = []
for c in counties_for_health:
    sold = int(sold_counts.get(c, 0))
    cut = int(cut_counts.get(c, 0))
    total = sold + cut
    close_rate = (sold / total) if total else 0.0
    rows.append(
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

rank_df = pd.DataFrame(rows)

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

# -----------------------------
# Overall stats (Dispo only)
# (uses rep-filtered sold df so close rate/stats match what user sees)
# -----------------------------
if team_view == "Dispo":
    stats = compute_overall_stats(df_time_sold_for_view, fd.df_time_cut)
    render_overall_stats(
        year_choice=year_choice,
        sold_total=stats["sold_total"],
        cut_total=stats["cut_total"],
        total_deals=stats["total_deals"],
        total_buyers=stats["total_buyers"],
        close_rate_str=stats["close_rate_str"],
    )

# buyer_sold_counts (only when filtering by a buyer in Dispo)
buyer_sold_counts = {}
if buyer_active and mode in ["Sold", "Both"]:
    buyer_sold_counts = (
        df_time_sold_for_view[df_time_sold_for_view["Buyer_clean"] == buyer_choice]
        .groupby("County_clean_up")
        .size()
        .to_dict()
    )

if team_view == "Sales Manager":
    tab_dash, tab_map = st.tabs(["Dashboard", "Map"])

    with tab_dash:
        # Dashboard should use SOLD deals for financials
        # If your sold df variable has a different name earlier in your app,
        # we can swap df_time_sold_for_view to that name.
        render_sales_manager_dashboard(df_time_sold_for_view[df_time_sold_for_view["Status_norm"] == "sold"])

    with tab_map:
        # -----------------------------
        # Enrich geojson for map
        # -----------------------------
        county_counts_view = df_view.groupby("County_clean_up").size().to_dict()
        county_properties_view = build_county_properties_view(df_view)

        tn_geo = load_tn_geojson()

        tn_geo = enrich_geojson_properties(
            tn_geo,
            team_view=team_view,
            mode=mode,
            buyer_active=buyer_active,
            buyer_choice=buyer_choice,
            top_n_buyers=int(TOP_N),
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

        # -----------------------------
        # Render map and capture clicks
        # -----------------------------
        map_state = st_folium(
            m,
            height=650,
            use_container_width=True,
            returned_objects=["last_active_drawing", "last_object_clicked"],
        )

        handle_map_click(map_state, team_view)

        # -----------------------------
        # BELOW MAP: County details panel
        # -----------------------------
        render_below_map_panel(
            team_view=team_view,
            df_view=df_view,
            sold_counts=sold_counts,
            cut_counts=cut_counts,
            buyer_count_by_county=buyer_count_by_county,
            mao_tier_by_county=mao_tier_by_county,
            mao_range_by_county=mao_range_by_county,
        )

else:
    # -----------------------------
    # Enrich geojson for map
    # -----------------------------
    county_counts_view = df_view.groupby("County_clean_up").size().to_dict()
    county_properties_view = build_county_properties_view(df_view)

    tn_geo = load_tn_geojson()

    tn_geo = enrich_geojson_properties(
        tn_geo,
        team_view=team_view,
        mode=mode,
        buyer_active=buyer_active,
        buyer_choice=buyer_choice,
        top_n_buyers=int(TOP_N),
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

    # -----------------------------
    # Render map and capture clicks
    # -----------------------------
    map_state = st_folium(
        m,
        height=650,
        use_container_width=True,
        returned_objects=["last_active_drawing", "last_object_clicked"],
    )

    handle_map_click(map_state, team_view)

    # -----------------------------
    # BELOW MAP: County details panel
    # -----------------------------
    render_below_map_panel(
        team_view=team_view,
        df_view=df_view,
        sold_counts=sold_counts,
        cut_counts=cut_counts,
        buyer_count_by_county=buyer_count_by_county,
        mao_tier_by_county=mao_tier_by_county,
        mao_range_by_county=mao_range_by_county,
    )
