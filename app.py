import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from config import DEFAULT_PAGE, MAP_DEFAULTS
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
from map_build import build_map

st.set_page_config(**DEFAULT_PAGE)
st.title("Closed RHD Properties Map")

df = load_data()
tiers = load_mao_tiers()

# Load geojson once (cached). We'll also use it for adjacency.
tn_geo_for_adj = load_tn_geojson()
adjacency = build_county_adjacency(tn_geo_for_adj)

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

# Buyers per county (sold only)
df_sold_buyers = fd.df_time_sold.copy()
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

# For "touching counties": use unique buyers across neighboring counties
buyers_set_by_county = (
    df_sold_buyers[df_sold_buyers["Buyer_clean"] != ""]
    .groupby("County_clean_up")["Buyer_clean"]
    .apply(lambda s: set(s.dropna().tolist()))
    .to_dict()
)

# -----------------------------
# Acquisitions sidebar (MAO guidance + quick search + nearby buyers)
# -----------------------------
if team_view == "Acquisitions":
    # Determine current selection
    selected = st.session_state.get("acq_selected_county")
    if not selected:
        selected = all_county_options[0] if all_county_options else ""

    selected = str(selected).strip().upper()

    buyer_count = int(buyer_count_by_county.get(selected, 0))

    neighbors = adjacency.get(selected, [])
    neighbor_buyers_union = set()
    neighbor_rows = []
    for n in neighbors:
        bset = buyers_set_by_county.get(n, set())
        neighbor_buyers_union |= bset
        neighbor_rows.append({"County": n.title(), "# Buyers": len(bset)})

    neighbor_unique_buyers = len(neighbor_buyers_union)

    neighbor_breakdown = pd.DataFrame(neighbor_rows)
    if not neighbor_breakdown.empty:
        neighbor_breakdown = neighbor_breakdown.sort_values("# Buyers", ascending=False).head(10)

    chosen_key = render_acquisitions_guidance(
        county_options=all_county_options,
        selected_county_key=selected,
        mao_tier=str(mao_tier_by_county.get(selected, "")) or "—",
        mao_range=str(mao_range_by_county.get(selected, "")) or "—",
        buyer_count=buyer_count,
        neighbor_unique_buyers=neighbor_unique_buyers,
        neighbor_breakdown=neighbor_breakdown,
    )

    # If dropdown selection changed, sync session + rerun
    if chosen_key and chosen_key != selected:
        st.session_state["acq_selected_county"] = chosen_key
        st.rerun()

    st.sidebar.markdown("---")

# -----------------------------
# Buyer controls (Dispo view only)
# -----------------------------
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
# Overall stats (Dispo only)
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

counties_for_health = sorted(set(list(sold_counts.keys()) + list(cut_counts.keys())))
health = compute_health_score(counties_for_health, sold_counts, cut_counts)

# -----------------------------
# Rankings table rows
# -----------------------------
rows = []
for c in deal_counties:
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

# Rankings stay the same; in Acq view they will now appear BELOW MAO guidance
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
# Enrich geojson for map tooltips/popups
# -----------------------------
county_counts_view = df_view.groupby("County_clean_up").size().to_dict()
county_properties_view = build_county_properties_view(df_view)
top_buyers_dict = build_top_buyers_dict(fd.df_time_sold)

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

# -----------------------------
# Render map and capture clicks
# -----------------------------
map_state = st_folium(m, height=650, use_container_width=True)

clicked_name = None
if isinstance(map_state, dict):
    lad = map_state.get("last_active_drawing")
    if isinstance(lad, dict):
        props = lad.get("properties", {})
        if isinstance(props, dict):
            clicked_name = props.get("NAME")

if team_view == "Acquisitions" and clicked_name:
    clicked_key = str(clicked_name).strip().upper()
    prev_key = st.session_state.get("acq_selected_county")
    if clicked_key and clicked_key != prev_key:
        st.session_state["acq_selected_county"] = clicked_key
        st.rerun()
