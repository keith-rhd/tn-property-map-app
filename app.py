import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from config import DEFAULT_PAGE, MAP_DEFAULTS
from data import load_data
from geo import load_tn_geojson
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
from map_build import build_map

st.set_page_config(**DEFAULT_PAGE)
st.title("Closed RHD Properties Map")

# -----------------------------
# Load data
# -----------------------------
df = load_data()

# -----------------------------
# Sidebar: Team view toggle
# -----------------------------
team_view = render_team_view_toggle(default=st.session_state.get("team_view", "Dispo"))
st.session_state["team_view"] = team_view

# -----------------------------
# Build MAO dicts early (so Acquisitions guidance can be at top)
# -----------------------------
mao_df = df[["County_clean_up", "MAO_Tier", "MAO_Range_Str"]].drop_duplicates("County_clean_up")
mao_tier_by_county = dict(zip(mao_df["County_clean_up"], mao_df["MAO_Tier"]))
mao_range_by_county = dict(zip(mao_df["County_clean_up"], mao_df["MAO_Range_Str"]))

# -----------------------------
# Acquisitions sidebar: MAO lookup at TOP (and remove overall stats)
# -----------------------------
if team_view == "Acquisitions":
    counties_upper = sorted(df["County_clean_up"].dropna().unique().tolist())
    acq_county = st.sidebar.selectbox(
        "County (quick MAO lookup)",
        [c.title() for c in counties_upper],
        index=0,
    )
    acq_key = acq_county.upper()
    render_acquisitions_guidance(
        county_choice=acq_county,
        mao_tier=str(mao_tier_by_county.get(acq_key, "")) or "—",
        mao_range=str(mao_range_by_county.get(acq_key, "")) or "—",
        note="If a county has no tier yet, it will show as blank (—).",
    )
    st.sidebar.markdown("---")

# -----------------------------
# Controls row (top)
# -----------------------------
col1, col3, col4, col5 = st.columns([1.1, 1.6, 1.7, 0.9], gap="small")

with col1:
    mode = st.radio("View", ["Sold", "Cut Loose", "Both"], index=0, horizontal=True)

years_available = sorted([int(y) for y in df["Year"].dropna().unique().tolist()])

with col3:
    year_choice = st.selectbox("Year", ["All years"] + years_available, index=0)

fd = prepare_filtered_data(df, year_choice)

# Buyer controls (Dispo view only)
if team_view == "Dispo":
    with col4:
        if mode in ["Sold", "Both"]:
            labels, label_to_buyer = build_buyer_labels(fd.buyer_momentum, fd.buyers_plain)
            chosen_label = st.selectbox("Buyer", labels, index=0)
            buyer_choice = label_to_buyer[chosen_label]
        else:
            buyer_choice = "All buyers"
            st.selectbox("Buyer", ["All buyers"], disabled=True)

    with col5:
        TOP_N = st.number_input("Top buyers", min_value=3, max_value=15, value=3)

    buyer_active = buyer_choice != "All buyers" and mode in ["Sold", "Both"]
else:
    with col4:
        buyer_choice = "All buyers"
        st.selectbox("Buyer", ["All buyers"], disabled=True)

    with col5:
        TOP_N = 3
        st.number_input("Top buyers", min_value=3, max_value=15, value=3, disabled=True)

    buyer_active = False

sel = Selection(
    mode=mode,
    year_choice=str(year_choice),
    buyer_choice=buyer_choice,
    buyer_active=buyer_active,
    top_n=int(TOP_N),
)

df_view = build_view_df(fd.df_time_sold, fd.df_time_cut, sel)

# -----------------------------
# Sidebar overall stats (DISPO ONLY)
# -----------------------------
if team_view == "Dispo":
    stats = compute_overall_stats(fd.df_time_sold, fd.df_time_cut)
    render_overall_stats(
        year_choice=year_choice,
        sold_total=stats["sold_total"],
        cut_total=stats["cut_total"],
        total_deals=stats["total_deals"],
        total_buyers=stats["total_buyers"],
        close_rate_str=stats["close_rate_str"],
    )

# -----------------------------
# County health + counts
# -----------------------------
df_conv = fd.df_time_filtered[fd.df_time_filtered["Status_norm"].isin(["sold", "cut loose"])]
grp = df_conv.groupby("County_clean_up")
sold_counts = grp.apply(lambda g: (g["Status_norm"] == "sold").sum()).to_dict()
cut_counts = grp.apply(lambda g: (g["Status_norm"] == "cut loose").sum()).to_dict()

counties = sorted(set(list(sold_counts.keys()) + list(cut_counts.keys())))
health = compute_health_score(counties, sold_counts, cut_counts)

# -----------------------------
# Rankings table rows
# -----------------------------
rows = []
all_counties = sorted(df["County_clean_up"].dropna().unique().tolist())

for c in all_counties:
    sold = int(sold_counts.get(c, 0))
    cut = int(cut_counts.get(c, 0))
    total = sold + cut
    close_rate = (sold / total) if total > 0 else 0.0

    buyer_ct = (
        fd.df_time_sold[fd.df_time_sold["County_clean_up"] == c]["Buyer_clean"]
        .replace("", pd.NA)
        .dropna()
        .nunique()
    )

    rows.append(
        {
            "County": c.title(),
            "Health score": float(health.get(c, 0)),
            "Buyer count": int(buyer_ct),
            "Sold": sold,
            "Cut loose": cut,
            "Total": total,
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
# Buyer-specific sold counts
# -----------------------------
buyer_sold_counts = {}
if buyer_active:
    buyer_sold_counts = (
        fd.df_time_sold[fd.df_time_sold["Buyer_clean"] == buyer_choice]
        .groupby("County_clean_up")
        .size()
        .to_dict()
    )

# -----------------------------
# County counts + properties in view
# -----------------------------
county_counts_view = df_view.groupby("County_clean_up").size().to_dict()
county_properties_view = build_county_properties_view(df_view)

# -----------------------------
# Top buyers (for Dispo view popups)
# -----------------------------
top_buyers_dict = build_top_buyers_dict(fd.df_time_sold)

# -----------------------------
# Geo + map
# -----------------------------
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
)

# Choose map coloring based on view
color_scheme = "mao" if team_view == "Acquisitions" else "activity"

m = build_map(
    tn_geo,
    mode=mode,
    buyer_active=buyer_active,
    buyer_choice=buyer_choice,
    center_lat=MAP_DEFAULTS["center_lat"],
    center_lon=MAP_DEFAULTS["center_lon"],
    zoom_start=MAP_DEFAULTS["zoom_start"],
    tiles=MAP_DEFAULTS["tiles"],
    color_scheme=color_scheme,
)

st_folium(m, height=650, use_container_width=True)
