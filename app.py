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
from ui_sidebar import (
    render_team_view_toggle,
    render_overall_stats,
    render_acquisitions_guidance,
    render_rankings,
)
from enrich import (
    build_top_buyers_dict,
    build_buyer_counts_by_county,
    build_neighbor_buyers,
)
from map_build import build_map


st.set_page_config(
    page_title=DEFAULT_PAGE.get("title", "TN Heatmap"),
    layout=DEFAULT_PAGE.get("layout", "wide"),
)

st.title(DEFAULT_PAGE.get("title", "TN Heatmap"))


# -----------------------------
# Load data
# -----------------------------
df = load_data()
tiers = load_mao_tiers()

# Geo + adjacency (cached)
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


# -----------------------------
# Controls row (top)
# - Dispo: Mode / Year / Buyer
# - Acq:  Mode / Year (Buyer still shown disabled for consistency)
# -----------------------------
col1, col3, col4 = st.columns([1.2, 1.0, 1.6], gap="small")

with col1:
    mode = st.selectbox("Status mode", ["Sold", "Cut Loose", "Both"], index=2)

with col3:
    # Year options come from the data
    years = sorted([y for y in df[C.DATE].dropna().dt.year.unique().tolist() if pd.notna(y)])
    year_labels = ["All years"] + [str(y) for y in years]
    year_choice = st.selectbox("Year", year_labels, index=0)

# Buyer: active only for Dispo and Sold/Both
if team_view == "Dispo":
    with col4:
        buyer_labels = build_buyer_labels(df)
        buyer_choice = st.selectbox("Buyer", buyer_labels, index=0)
    buyer_active = buyer_choice != "All buyers" and mode in ["Sold", "Both"]
else:
    with col4:
        buyer_choice = "All buyers"
        st.selectbox("Buyer", ["All buyers"], disabled=True)
    buyer_active = False

# We don't need a "Top buyers" control anymore; keep a consistent internal top-N for displays
TOP_N = 10


# -----------------------------
# Build selection + filtered data
# -----------------------------
sel = Selection(
    mode=mode,
    year_choice=str(year_choice),
    buyer_choice=str(buyer_choice),
    buyer_active=bool(buyer_active),
)

fd = prepare_filtered_data(df, sel)

df_view = build_view_df(fd.df_time_sold, fd.df_time_cut, sel)


# -----------------------------
# Compute county-level metrics (for map + sidebar rankings)
# -----------------------------
rank_df = compute_health_score(df_view)

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
# Dispo: Stats scope (overall vs county) + stats card
# -----------------------------
if team_view == "Dispo":
    # Keep the Dispo dropdown in sync with map clicks
    clicked_or_selected = str(st.session_state.get("selected_county", "")).strip().upper()

    dispo_options_title = ["Overall (all counties)"] + [c.title() for c in all_county_options]
    default_title = clicked_or_selected.title() if clicked_or_selected in set(all_county_options) else "Overall (all counties)"

    # If a map click changed selected_county, reflect it in the dropdown before the widget renders
    if st.session_state.get("dispo_county_select") != default_title:
        st.session_state["dispo_county_select"] = default_title

    chosen_title = st.sidebar.selectbox(
        "County quick search",
        dispo_options_title,
        index=dispo_options_title.index(default_title) if default_title in dispo_options_title else 0,
        key="dispo_county_select",
        help="Click a county on the map OR use this dropdown to view county-level Dispo stats. Choose 'Overall' to go back.",
    )

    # Apply chosen scope
    if chosen_title == "Overall (all counties)":
        st.session_state["selected_county"] = ""
        sold_scope = fd.df_time_sold
        cut_scope = fd.df_time_cut
        stats_title = "Overall stats"
        scope_caption = None
    else:
        chosen_key = str(chosen_title).strip().upper()
        st.session_state["selected_county"] = chosen_key
        sold_scope = fd.df_time_sold[fd.df_time_sold["County_key"] == chosen_key]
        cut_scope = fd.df_time_cut[fd.df_time_cut["County_key"] == chosen_key]
        stats_title = "County stats"
        scope_caption = f"County: **{chosen_title}**"

    stats = compute_overall_stats(sold_scope, cut_scope)
    render_overall_stats(
        title=stats_title,
        scope_caption=scope_caption,
        year_choice=year_choice,
        sold_total=stats["sold_total"],
        cut_total=stats["cut_total"],
        total_deals=stats["total_deals"],
        total_buyers=stats["total_buyers"],
        close_rate_str=stats["close_rate_str"],
    )


# -----------------------------
# Build top buyers dict (used in Dispo sidebar + below-map panel metrics)
# -----------------------------
top_buyers_dict = build_top_buyers_dict(fd.df_time_sold)


# -----------------------------
# Dispo: Sidebar "Top buyers in selected county" (below stats card)
# -----------------------------
if team_view == "Dispo":
    sel_county = str(st.session_state.get("selected_county", "")).strip().upper()
    if sel_county:
        top_list = (top_buyers_dict.get(sel_county, []) or [])[:TOP_N]
        st.sidebar.markdown("## Top buyers in selected county")
        st.sidebar.caption(f"County: **{sel_county.title()}** (sold only)")
        if top_list:
            st.sidebar.dataframe(
                pd.DataFrame(top_list, columns=["Buyer", "Sold deals"]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.sidebar.info("No sold deals found for this county (in the current filters).")
        st.sidebar.markdown("---")


# -----------------------------
# Acquisitions guidance block (sidebar)
# -----------------------------
if team_view == "Acquisitions":
    # Determine county for guidance (map click + dropdown)
    selected_key = str(st.session_state.get("acq_selected_county", "")).strip().upper()
    if not selected_key:
        # Default to Davidson if nothing selected yet
        selected_key = "DAVIDSON"
        st.session_state["acq_selected_county"] = selected_key
        st.session_state["selected_county"] = selected_key

    # Buyer counts for county + neighbor counties
    buyer_counts = build_buyer_counts_by_county(fd.df_time_sold)
    buyer_count = int(buyer_counts.get(selected_key, 0))

    neighbor_unique_buyers, neighbor_breakdown = build_neighbor_buyers(
        sold_df=fd.df_time_sold,
        county_key=selected_key,
        adjacency=adjacency,
        top_n=TOP_N,
    )

    chosen_key = render_acquisitions_guidance(
        county_options=all_county_options,
        selected_county_key=selected_key,
        mao_tier=str(mao_tier_by_county.get(selected_key.title(), "—")),
        mao_range=str(mao_range_by_county.get(selected_key.title(), "—")),
        buyer_count=buyer_count,
        neighbor_unique_buyers=int(neighbor_unique_buyers),
        neighbor_breakdown=neighbor_breakdown,
    )

    # Save chosen county back into state
    chosen_key = str(chosen_key).strip().upper()
    if chosen_key and chosen_key != selected_key:
        st.session_state["acq_selected_county"] = chosen_key
        st.session_state["selected_county"] = chosen_key
        st.rerun()


# -----------------------------
# Build map
# -----------------------------
m = build_map(
    geojson=tn_geo_for_adj,
    rank_df=rank_df,
    df_view=df_view,
    mode=mode,
    year_choice=year_choice,
    buyer_choice=buyer_choice,
    buyer_active=buyer_active,
    map_defaults=MAP_DEFAULTS,
)


# -----------------------------
# Render map and capture clicks
# -----------------------------
map_state = st_folium(m, height=650, use_container_width=True)


def _extract_clicked_county_name(state: dict) -> str | None:
    if not isinstance(state, dict):
        return None

    lad = state.get("last_active_drawing")
    if isinstance(lad, dict):
        props = lad.get("properties", {})
        if isinstance(props, dict) and props.get("NAME"):
            return props.get("NAME")

    loc = state.get("last_object_clicked")
    if isinstance(loc, dict):
        props = loc.get("properties", {})
        if isinstance(props, dict) and props.get("NAME"):
            return props.get("NAME")

    return None


clicked_name = _extract_clicked_county_name(map_state)
clicked_key = str(clicked_name).strip().upper() if clicked_name else ""

# Always store clicked county (both views)
if clicked_key:
    prev_selected = str(st.session_state.get("selected_county", "")).strip().upper()
    st.session_state["selected_county"] = clicked_key

    # Dispo: rerun immediately so sidebar updates on click
    if team_view == "Dispo" and clicked_key != prev_selected:
        st.rerun()

# Acquisitions: clicking should update sidebar + below map
if team_view == "Acquisitions" and clicked_key:
    prev_key = str(st.session_state.get("acq_selected_county", "")).strip().upper()
    if clicked_key != prev_key:
        st.session_state["acq_selected_county"] = clicked_key
        st.session_state["selected_county"] = clicked_key
        st.session_state["acq_pending_county_title"] = clicked_key.title()
        st.rerun()


# -----------------------------
# BELOW MAP: County details panel
# -----------------------------
selected_for_panel = st.session_state.get("selected_county")
if team_view == "Acquisitions":
    selected_for_panel = st.session_state.get("acq_selected_county", selected_for_panel)

# (Your existing below-map panel logic continues as-is in your repo.
#  If you want, next we can make the below-map panel also respect the Dispo "Overall vs County" scope.)
