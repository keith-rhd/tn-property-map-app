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
    render_dispo_sidebar_header,
    render_dispo_county_quick_search,
    render_dispo_county_stats,
    render_dispo_top_buyers,
    render_dispo_county_rankings,
    render_dispo_overall_stats,
    render_acquisitions_guidance,
    render_acquisitions_nearby_buyers,
)

from map_build import build_map, enrich_geo_for_dispo, enrich_geo_for_acq
from enrich import enrich_county_summary


def init_state():
    """Initialize Streamlit session-state defaults in one place.

    This prevents subtle regressions as the app grows (map click vs dropdown sync, etc.).
    """
    placeholder = "— Select a county —"

    defaults = {
        # Which view is active
        "team_view": "Dispo",

        # County selection single source of truth (stored as COUNTY KEY like "DAVIDSON")
        "selected_county": "",
        "acq_selected_county": "",
        "county_source": "",  # "map" | "dropdown" | ""

        # Map click bookkeeping
        "last_map_clicked_county": "",

        # Dispo dropdown bookkeeping
        "dispo_county_lookup": placeholder,
        "_dispo_prev_county_lookup": placeholder,

        # Acquisitions dropdown bookkeeping (selectbox uses a separate widget key)
        "acq_county_select": "",
    }

    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


st.set_page_config(**DEFAULT_PAGE)
init_state()

# -----------------------------
# Load + normalize data
# -----------------------------
df = load_data()

# Ensure Year is numeric (defensive)
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

# -----------------------------
# Top controls row
# -----------------------------
col1, col3, col4 = st.columns([1.1, 1.6, 1.7], gap="small")

with col1:
    mode = st.radio("View", ["Sold", "Cut Loose", "Both"], index=0, horizontal=True)

years_available = sorted([int(y) for y in df["Year"].dropna().unique().tolist()]) if "Year" in df.columns else []
with col3:
    year_choice = st.selectbox("Year", ["All years"] + years_available, index=0)

# Filtered data bundle
fd = prepare_filtered_data(df, year_choice)

# -----------------------------
# Buyers per county (sold only) (used in map enrichment & panels)
# -----------------------------
buyers_plain, buyer_momentum = build_buyer_labels(fd.df_time_sold)

# -----------------------------
# DISPO SIDEBAR
# -----------------------------
if team_view == "Dispo":
    render_dispo_sidebar_header()

    placeholder = "— Select a county —"
    key_to_title = {c.upper(): c.title() for c in all_county_options}

    # Detect if the user just changed the dropdown (Streamlit sets widget state BEFORE rerun)
    curr_dd = st.session_state.get("dispo_county_lookup", placeholder)
    prev_dd = st.session_state.get("_dispo_prev_county_lookup", curr_dd)
    user_changed_dropdown = curr_dd != prev_dd

    # If the last selection was from the map and user hasn't touched dropdown, keep them synced
    if st.session_state.get("county_source") == "map" and not user_changed_dropdown:
        sel_key = str(st.session_state.get("selected_county", "")).strip().upper()
        if sel_key and sel_key in key_to_title:
            st.session_state["dispo_county_lookup"] = key_to_title[sel_key]

    st.session_state.setdefault("dispo_county_lookup", placeholder)

    # Render quick search
    chosen_title = render_dispo_county_quick_search(
        options_title=[placeholder] + [c.title() for c in all_county_options],
        default_index=(
            ([placeholder] + [c.title() for c in all_county_options]).index(st.session_state["dispo_county_lookup"])
            if st.session_state["dispo_county_lookup"] in ([placeholder] + [c.title() for c in all_county_options])
            else 0
        ),
        widget_key="dispo_county_lookup",
    )

    # Persist previous value for next rerun
    st.session_state["_dispo_prev_county_lookup"] = st.session_state.get("dispo_county_lookup", placeholder)
    st.sidebar.caption("Tip: you can also click a county on the map to update this.")

    # If user selected from dropdown, update selected_county
    if chosen_title and chosen_title != placeholder:
        chosen_key = str(chosen_title).strip().upper().replace(" COUNTY", "")
        if chosen_key in [c.upper() for c in all_county_options]:
            st.session_state["selected_county"] = chosen_key
            st.session_state["county_source"] = "dropdown"

    # Sidebar county stats/top buyers/rankings/overall stats
    sel_for_sidebar = st.session_state.get("selected_county", "")

    dispo_summary = enrich_county_summary(
        county_key=sel_for_sidebar,
        df_time_sold=fd.df_time_sold,
        df_time_cut=fd.df_time_cut,
        df_time_all=fd.df_time_all,
        adjacency=adjacency,
        buyers_plain=buyers_plain,
        buyers_momentum=buyer_momentum,
    )

    render_dispo_county_stats(dispo_summary)
    render_dispo_top_buyers(dispo_summary)
    render_dispo_county_rankings(fd, adjacency)
    render_dispo_overall_stats(fd, adjacency)

# -----------------------------
# ACQUISITIONS SIDEBAR
# -----------------------------
if team_view == "Acquisitions":
    if "acq_pending_county_title" in st.session_state:
        st.session_state["acq_county_select"] = st.session_state["acq_pending_county_title"]
        del st.session_state["acq_pending_county_title"]

    selected = st.session_state.get("acq_selected_county")
    if not selected:
        selected = "DAVIDSON" if "DAVIDSON" in [c.upper() for c in all_county_options] else (all_county_options[0] if all_county_options else "")

    chosen_key = render_acquisitions_guidance(
        county_options=all_county_options,
        selected_county_key=selected,
        mao_tier=str(mao_tier_by_county.get(selected, "")) or "—",
        mao_range=str(mao_range_by_county.get(selected, "")) or "—",
        widget_key="acq_county_select",
    )

    if chosen_key and chosen_key != selected:
        st.session_state["acq_selected_county"] = chosen_key
        st.session_state["selected_county"] = chosen_key
        st.session_state["county_source"] = "dropdown"

    acq_sel = st.session_state.get("acq_selected_county", selected)
    render_acquisitions_nearby_buyers(
        county_key=acq_sel,
        adjacency=adjacency,
        df_time_sold=fd.df_time_sold,
    )

# -----------------------------
# MAIN MAP
# -----------------------------
# Base geojson (TN only)
tn_geo = load_tn_geojson()

# Build view df
view_df = build_view_df(fd, mode=mode)

# Enrich geo for map based on view
if team_view == "Dispo":
    geo_enriched = enrich_geo_for_dispo(
        tn_geo=tn_geo,
        fd=fd,
        adjacency=adjacency,
        buyers_plain=buyers_plain,
        buyer_momentum=buyer_momentum,
    )
else:
    geo_enriched = enrich_geo_for_acq(
        tn_geo=tn_geo,
        tiers=tiers,
    )

# Build map
m = build_map(geo_enriched, defaults=MAP_DEFAULTS, team_view=team_view)

# Render map with st_folium
out = st_folium(m, width=None, height=MAP_DEFAULTS.get("height", 650), returned_objects=["last_active_drawing", "last_object_clicked"])

# -----------------------------
# Map click handling
# -----------------------------
clicked_key = None
if out and isinstance(out, dict):
    # Prefer last_object_clicked when available
    obj = out.get("last_object_clicked") or {}
    props = obj.get("properties") or {}
    clicked_name = props.get("NAME") or props.get("name") or ""
    if clicked_name:
        clicked_key = str(clicked_name).strip().upper()

if clicked_key and clicked_key != st.session_state.get("last_map_clicked_county", ""):
    st.session_state["last_map_clicked_county"] = clicked_key
    st.session_state["selected_county"] = clicked_key
    st.session_state["county_source"] = "map"

    # Keep Acq selected in sync if on Acq view
    if team_view == "Acquisitions":
        st.session_state["acq_selected_county"] = clicked_key
        st.session_state["acq_pending_county_title"] = clicked_key.title()
        st.rerun()

# -----------------------------
# BELOW MAP: County details panel
# -----------------------------
selected_for_panel = st.session_state.get("selected_county")
if team_view == "Acquisitions":
    selected_for_panel = st.session_state.get("acq_selected_county", selected_for_panel)

if selected_for_panel:
    st.markdown(f"### {selected_for_panel.title()} County — Properties")

    county_df = view_df[view_df["County_clean_up"].astype(str).str.upper() == str(selected_for_panel).upper()].copy()

    # Best effort sort by date if present
    if "Date_dt" in county_df.columns:
        county_df = county_df.sort_values("Date_dt", ascending=False)

    # Display a useful subset first, keep URL if present
    cols = []
    for c in ["Address", "City", "County", "Status", "Buyer", "Date", "Salesforce_URL"]:
        if c in county_df.columns:
            cols.append(c)

    st.dataframe(county_df[cols] if cols else county_df, use_container_width=True)

else:
    st.info("Select a county (click on the map or use the sidebar) to see the properties list.")
