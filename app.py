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
    render_rankings,
    render_acquisitions_guidance,
)
from enrich import (
    build_top_buyers_dict,
    build_county_properties_view,
    enrich_geojson_properties,
)
from map_build import build_map


def init_state():
    """Central place for Streamlit session-state defaults.

    Keeps state keys consistent so map clicks, dropdowns, and view switches stay in sync.
    """
    placeholder = "— Select a county —"
    defaults = {
        # Which view is active
        "team_view": "Dispo",

        # County selection (stored as COUNTY KEY like "DAVIDSON")
        "selected_county": "",
        "acq_selected_county": "",
        "county_source": "",  # "map" | "dropdown" | ""

        # Map click bookkeeping
        "last_map_clicked_county": "",

        # Dispo dropdown bookkeeping
        "dispo_county_lookup": placeholder,
        "_dispo_prev_county_lookup": placeholder,

        # Acquisitions dropdown widget key
        "acq_county_select": "",
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


st.set_page_config(**DEFAULT_PAGE)
init_state()

st.title("Closed RHD Properties Map")

df = load_data()

# -----------------------------
# Sidebar: Team view toggle
# -----------------------------
team_view = render_team_view_toggle(default=st.session_state.get("team_view", "Dispo"))
st.session_state["team_view"] = team_view

# -----------------------------
# Controls row (top)
# -----------------------------
col1, col3, col4 = st.columns([1.1, 1.6, 1.7], gap="small")

with col1:
    mode = st.radio("View", ["Sold", "Cut Loose", "Both"], index=0, horizontal=True)

years_available = (
    sorted([int(y) for y in df["Year"].dropna().unique().tolist()])
    if "Year" in df.columns
    else []
)

with col3:
    year_choice = st.selectbox("Year", ["All years"] + years_available, index=0)

# Filtered data bundle
fd = prepare_filtered_data(df, year_choice)

# Buyers labels/momentum (used in sidebar + map enrichment)
buyers_plain, buyer_momentum = build_buyer_labels(fd.df_time_sold)

# Geo + adjacency
tn_geo = load_tn_geojson()
adjacency = build_county_adjacency(tn_geo)

# MAO tiers (for acquisitions)
tiers = load_mao_tiers()

mao_tier_by_county = {}
mao_range_by_county = {}
if tiers is not None and not tiers.empty:
    mao_tier_by_county = dict(zip(tiers["County_clean_up"], tiers["MAO_Tier"]))
    mao_range_by_county = dict(zip(tiers["County_clean_up"], tiers["MAO_Range_Str"]))

# -----------------------------------
# Sidebar content by team view
# -----------------------------------
placeholder = "— Select a county —"

if team_view == "Dispo":
    st.sidebar.subheader("Dispo")

    # Dropdown options
    dispo_counties = sorted(df["County_clean_up"].dropna().unique().tolist())

    # Ensure widget key exists (kept for backwards compatibility)
    st.session_state.setdefault("dispo_county_lookup", placeholder)

    # Detect user change vs map-driven sync
    curr_dd = st.session_state.get("dispo_county_lookup", placeholder)
    prev_dd = st.session_state.get("_dispo_prev_county_lookup", curr_dd)
    user_changed_dropdown = curr_dd != prev_dd

    # If map was the source and user hasn't touched dropdown, keep dropdown synced
    if st.session_state.get("county_source") == "map" and not user_changed_dropdown:
        sel_key = str(st.session_state.get("selected_county", "")).strip().upper()
        if sel_key:
            st.session_state["dispo_county_lookup"] = sel_key.title()

    st.sidebar.caption("Tip: you can also click a county on the map to update this.")

    chosen_title = st.sidebar.selectbox(
        "County quick search",
        [placeholder] + [c.title() for c in dispo_counties],
        index=0
        if st.session_state.get("dispo_county_lookup", placeholder) == placeholder
        else ([placeholder] + [c.title() for c in dispo_counties]).index(
            st.session_state.get("dispo_county_lookup", placeholder)
        )
        if st.session_state.get("dispo_county_lookup", placeholder)
        in ([placeholder] + [c.title() for c in dispo_counties])
        else 0,
        key="dispo_county_lookup",
    )

    # Persist previous value for next rerun
    st.session_state["_dispo_prev_county_lookup"] = st.session_state.get(
        "dispo_county_lookup", placeholder
    )

    # If user selected a county from dropdown, update selection
    if chosen_title and chosen_title != placeholder:
        chosen_key = str(chosen_title).strip().upper().replace(" COUNTY", "")
        st.session_state["selected_county"] = chosen_key
        st.session_state["county_source"] = "dropdown"

    # Dispo sidebar stats
    selected_county = st.session_state.get("selected_county", "")

    # Top buyers dict and rankings
    top_buyers_dict = build_top_buyers_dict(fd.df_time_sold, adjacency)
    render_rankings(fd, adjacency)

    # Overall stats shown at bottom (matches your current layout)
    overall = compute_overall_stats(fd, adjacency)
    render_overall_stats(overall)

else:
    st.sidebar.subheader("Acquisitions")

    # Default county preference (keeps your workflow)
    all_counties = (
        sorted(tiers["County_clean_up"].dropna().unique().tolist())
        if tiers is not None and not tiers.empty
        else sorted(df["County_clean_up"].dropna().unique().tolist())
    )
    default_acq = (
        "DAVIDSON" if "DAVIDSON" in [c.upper() for c in all_counties] else (all_counties[0] if all_counties else "")
    )

    acq_selected = st.session_state.get("acq_selected_county", "") or default_acq

    # Render the Acq guidance panel + county selector
    chosen_key = render_acquisitions_guidance(
        county_options=all_counties,
        selected_county_key=acq_selected,
        mao_tier=str(mao_tier_by_county.get(acq_selected, "")) or "—",
        mao_range=str(mao_range_by_county.get(acq_selected, "")) or "—",
        widget_key="acq_county_select",
    )

    if chosen_key:
        st.session_state["acq_selected_county"] = chosen_key
        st.session_state["selected_county"] = chosen_key
        st.session_state["county_source"] = "dropdown"

# -----------------------------
# Build view df (for below-map table)
# -----------------------------
view_df = build_view_df(fd, mode=mode)

# -----------------------------
# Map enrichment + build
# -----------------------------
geo_enriched = enrich_geojson_properties(
    tn_geo=tn_geo,
    fd=fd,
    adjacency=adjacency,
    buyers_plain=buyers_plain,
    buyer_momentum=buyer_momentum,
    mao_tier_by_county=mao_tier_by_county,
    mao_range_by_county=mao_range_by_county,
    team_view=team_view,
)

m = build_map(geo_enriched, defaults=MAP_DEFAULTS, team_view=team_view)

out = st_folium(
    m,
    width=None,
    height=MAP_DEFAULTS.get("height", 650),
    returned_objects=["last_object_clicked"],
)

# -----------------------------
# Map click handling
# -----------------------------
clicked_key = None
if out and isinstance(out, dict):
    obj = out.get("last_object_clicked") or {}
    props = obj.get("properties") or {}
    clicked_name = props.get("NAME") or props.get("name") or ""
    if clicked_name:
        clicked_key = str(clicked_name).strip().upper()

if clicked_key and clicked_key != st.session_state.get("last_map_clicked_county", ""):
    st.session_state["last_map_clicked_county"] = clicked_key
    st.session_state["selected_county"] = clicked_key
    st.session_state["county_source"] = "map"

    if team_view == "Acquisitions":
        st.session_state["acq_selected_county"] = clicked_key
        st.rerun()

# -----------------------------
# Below map: Properties table
# -----------------------------
selected_for_panel = st.session_state.get("selected_county", "")
if team_view == "Acquisitions":
    selected_for_panel = st.session_state.get("acq_selected_county", selected_for_panel)

if selected_for_panel:
    st.markdown(f"### {selected_for_panel.title()} County — Properties")

    df_props = build_county_properties_view(view_df, selected_for_panel)

    if df_props is not None and not df_props.empty:
        st.dataframe(
            df_props,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Salesforce": st.column_config.LinkColumn("Salesforce", display_text="Open"),
            }
            if "Salesforce" in df_props.columns
            else None,
        )
    else:
        st.info("No properties match the current filters for this county.")
else:
    st.caption("Tip: Click a county to see details below the map.")
