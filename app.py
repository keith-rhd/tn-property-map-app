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
from ui_sidebar import render_overall_stats, render_rankings
from enrich import build_top_buyers_dict, build_county_properties_view, enrich_geojson_properties
from map_build import build_map

st.set_page_config(**DEFAULT_PAGE)

# -----------------------------
# Load data
# -----------------------------
df = load_data()

# -----------------------------
# Map state (prevents "jumping" on reruns)
# - initialize once from MAP_DEFAULTS
# -----------------------------
if "map_center" not in st.session_state:
    st.session_state["map_center"] = [MAP_DEFAULTS["center_lat"], MAP_DEFAULTS["center_lon"]]
if "map_zoom" not in st.session_state:
    st.session_state["map_zoom"] = MAP_DEFAULTS["zoom_start"]

# -----------------------------
# One-row UI controls (same as before)
# -----------------------------
col1, col3, col4, col5 = st.columns([1.1, 1.6, 1.7, 0.9], gap="small")

with col1:
    mode = st.radio("View", ["Sold", "Cut Loose", "Both"], index=0, horizontal=True)

years_available = sorted([int(y) for y in df["Year"].dropna().unique().tolist() if pd.notna(y)])

with col3:
    year_choice = st.selectbox("Year", ["All years"] + years_available, index=0)

fd = prepare_filtered_data(df, year_choice)

with col4:
    if mode in ["Sold", "Both"]:
        labels, label_to_buyer = build_buyer_labels(fd.buyer_momentum, fd.buyers_plain)
        chosen_label = st.selectbox("Buyer", labels, index=0)
        buyer_choice = label_to_buyer[chosen_label]
    else:
        buyer_choice = "All buyers"
        st.selectbox("Buyer", ["All buyers"], index=0, disabled=True)

with col5:
    TOP_N = st.number_input("Top buyers", min_value=3, max_value=15, value=3, step=1)

buyer_active = (buyer_choice != "All buyers") and (mode in ["Sold", "Both"])

sel = Selection(
    mode=mode,
    year_choice=str(year_choice),
    buyer_choice=buyer_choice,
    buyer_active=buyer_active,
    top_n=int(TOP_N),
)

df_view = build_view_df(fd.df_time_sold, fd.df_time_cut, sel)

# -----------------------------
# Sidebar stats (top)
# -----------------------------
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
# County sold/cut totals (time-filtered)
# -----------------------------
df_conv = fd.df_time_filtered[fd.df_time_filtered["Status_norm"].isin(["sold", "cut loose"])].copy()
grp_all = df_conv.groupby("County_clean_up")
sold_counts = grp_all.apply(lambda g: (g["Status_norm"] == "sold").sum()).to_dict()
cut_counts = grp_all.apply(lambda g: (g["Status_norm"] == "cut loose").sum()).to_dict()

all_counties = sorted(set(list(sold_counts.keys()) + list(cut_counts.keys())))
health_score = compute_health_score(all_counties, sold_counts, cut_counts)

# Rankings DF (only Health score + Buyer count)
county_rows = []
for c_up in all_counties:
    buyer_count = int(
        fd.df_time_sold.loc[fd.df_time_sold["County_clean_up"] == c_up, "Buyer_clean"]
        .replace("", pd.NA)
        .dropna()
        .nunique()
    )
    county_rows.append(
        {
            "County": c_up.title(),
            "Health score": float(health_score.get(c_up, 0.0)),
            "Buyer count": buyer_count,
        }
    )

rank_df = pd.DataFrame(county_rows)
render_rankings(rank_df)

# -----------------------------
# Buyer-specific sold counts by county
# -----------------------------
buyer_sold_counts = {}
if buyer_active:
    df_buyer_sold = fd.df_time_sold[fd.df_time_sold["Buyer_clean"] == buyer_choice]
    buyer_sold_counts = df_buyer_sold.groupby("County_clean_up").size().to_dict()

# -----------------------------
# Map counts + address list (current view)
# -----------------------------
county_counts_view = df_view.groupby("County_clean_up").size().to_dict()
county_properties_view = build_county_properties_view(df_view)

# -----------------------------
# Live MAO tiers (one per county)
# -----------------------------
mao_df = df[["County_clean_up", "MAO_Tier", "MAO_Range_Str"]].dropna(subset=["County_clean_up"]).copy()
mao_df = mao_df.drop_duplicates(subset=["County_clean_up"], keep="first")
mao_tier_by_county = dict(zip(mao_df["County_clean_up"], mao_df["MAO_Tier"].fillna("").astype(str)))
mao_range_by_county = dict(zip(mao_df["County_clean_up"], mao_df["MAO_Range_Str"].fillna("").astype(str)))

# -----------------------------
# Top buyers by county (SOLD only, time-filtered)
# -----------------------------
top_buyers_dict = build_top_buyers_dict(fd.df_time_sold)

# -----------------------------
# Geo + enrichment + map
# -----------------------------
tn_geo = load_tn_geojson()

tn_geo = enrich_geojson_properties(
    tn_geo,
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

# Build the map using the LAST known center/zoom (prevents jumping on rerun)
m = build_map(
    tn_geo,
    mode=mode,
    buyer_active=buyer_active,
    buyer_choice=buyer_choice,
    center_lat=MAP_DEFAULTS["center_lat"],
    center_lon=MAP_DEFAULTS["center_lon"],
    zoom_start=MAP_DEFAULTS["zoom_start"],
    tiles=MAP_DEFAULTS["tiles"],
)

st.title("Closed RHD Properties Map")

# Render map FULL-WIDTH so it stays centered and stable in layout
st_folium(m, height=650, use_container_width=True)


# Persist center + zoom from the rendered map so reruns don't snap back
if isinstance(map_state, dict):
    center = map_state.get("center")
    zoom = map_state.get("zoom")

    if isinstance(center, dict) and "lat" in center and "lng" in center:
        st.session_state["map_center"] = [center["lat"], center["lng"]]

    if zoom is not None:
        st.session_state["map_zoom"] = zoom
