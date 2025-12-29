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
from state import init_state, ensure_default_county

st.set_page_config(**DEFAULT_PAGE)
init_state()
st.title("Closed RHD Properties Map")

df = load_data()

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

# Phase A3: set a stable default county once we know county options.
ensure_default_county(all_county_options, preferred="DAVIDSON")

# -----------------------------
# Sidebar: Team view toggle
# -----------------------------
team_view = render_team_view_toggle(default=st.session_state["team_view"])
st.session_state["team_view"] = team_view

# -----------------------------
# Controls row (top)
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

# -----------------------------
# Acquisitions sidebar (MAO guidance + quick search + nearby buyers)
# -----------------------------
if team_view == "Acquisitions":
    if st.session_state.get("acq_pending_county_title"):
        st.session_state["acq_county_select"] = st.session_state["acq_pending_county_title"]
        st.session_state["acq_pending_county_title"] = ""

    selected = st.session_state.get("acq_selected_county")
    if not selected:
        selected = "DAVIDSON" if "DAVIDSON" in [c.upper() for c in all_county_options] else (all_county_options[0] if all_county_options else "")
    selected = str(selected).strip().upper()

    buyer_count = int(buyer_count_by_county.get(selected, 0))

    buyers_set_by_county = (
        df_sold_buyers[df_sold_buyers["Buyer_clean"] != ""]
        .groupby("County_clean_up")["Buyer_clean"]
        .apply(lambda s: set(s.dropna().tolist()))
        .to_dict()
    )

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

    if chosen_key and chosen_key != selected:
        st.session_state["acq_selected_county"] = chosen_key
        st.session_state["selected_county"] = chosen_key
        st.session_state["county_source"] = "dropdown"  # keep consistent
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

    buyer_active = buyer_choice != "All buyers" and mode in ["Sold", "Both"]
else:
    with col4:
        buyer_choice = "All buyers"
        st.selectbox("Buyer", ["All buyers"], disabled=True)
    buyer_active = False

TOP_N = 10

sel = Selection(
    mode=mode,
    year_choice=str(year_choice),
    buyer_choice=buyer_choice,
    buyer_active=buyer_active,
    top_n=int(TOP_N),
)

df_view = build_view_df(fd.df_time_sold, fd.df_time_cut, sel)

# -----------------------------
# Dispo: County quick lookup (Acq-style format)
# -----------------------------
if team_view == "Dispo":
    st.sidebar.markdown("## County stats")
    st.sidebar.caption("County quick search")

    placeholder = "— Select a county —"
    county_titles = [c.title() for c in all_county_options]
    options_title = [placeholder] + county_titles
    title_to_key = {c.title(): c.upper() for c in all_county_options}
    key_to_title = {c.upper(): c.title() for c in all_county_options}

    # Detect if the user just changed the dropdown (Streamlit sets widget state BEFORE rerun)
    curr_dd = st.session_state.get("dispo_county_lookup", placeholder)
    prev_dd = st.session_state.get("_dispo_prev_county_lookup", curr_dd)
    user_changed_dropdown = curr_dd != prev_dd

    # Only auto-sync dropdown from map if the map was last source AND user didn't just change dropdown
    if st.session_state.get("county_source") == "map" and not user_changed_dropdown:
        sel_key = str(st.session_state.get("selected_county", "")).strip().upper()
        if sel_key and sel_key in key_to_title:
            st.session_state["dispo_county_lookup"] = key_to_title[sel_key]

    chosen_title = st.sidebar.selectbox(
        "County quick search",
        options_title,
        index=options_title.index(st.session_state["dispo_county_lookup"])
        if st.session_state["dispo_county_lookup"] in options_title
        else 0,
        key="dispo_county_lookup",
        label_visibility="collapsed",
        help="Use this if you can’t easily click the county on the map.",
    )

    # Persist previous value for next rerun
    st.session_state["_dispo_prev_county_lookup"] = st.session_state.get("dispo_county_lookup", placeholder)

    st.sidebar.caption("Tip: you can also click a county on the map to update this.")

    if chosen_title == placeholder:
        st.sidebar.info("Select a county to see Dispo stats here.")
        st.sidebar.markdown("---")
    else:
        new_key = title_to_key.get(chosen_title, "").strip().upper()
        prev_key = str(st.session_state.get("selected_county", "")).strip().upper()

        # If dropdown changed county, make it the source of truth and rerun
        if new_key and new_key != prev_key:
            st.session_state["selected_county"] = new_key
            st.session_state["county_source"] = "dropdown"
            st.rerun()

        # County scope data (already filtered by year + view filters via fd)
        sold_scope = fd.df_time_sold[fd.df_time_sold["County_clean_up"] == new_key]
        cut_scope = fd.df_time_cut[fd.df_time_cut["County_clean_up"] == new_key]
        cstats = compute_overall_stats(sold_scope, cut_scope)

        sold_ct = int(cstats["sold_total"])
        cut_ct = int(cstats["cut_total"])
        total_ct = int(cstats["total_deals"])
        buyer_ct = int(cstats["total_buyers"])
        close_rate_str = str(cstats["close_rate_str"])
        
        # Acq-style card
        st.sidebar.markdown(
            f"""<div style="
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.14);
            border-radius: 10px;
            padding: 10px 12px;
        ">
            <div style="margin-bottom:6px;"><b>County:</b> {chosen_title}</div>
            <div style="margin-bottom:6px;"><b>Sold:</b> {sold_ct}</div>
            <div style="margin-bottom:6px;"><b>Cut loose:</b> {cut_ct}</div>
            <div style="margin-bottom:6px;"><b>Total deals:</b> {total_ct}</div>
            <div style="margin-bottom:6px;"><b># Buyers:</b> {buyer_ct}</div>
            <div><b>Close rate:</b> {close_rate_str}</div>
        </div>""",
            unsafe_allow_html=True,
        )

        st.sidebar.markdown("---")

        # Top buyers in this county (sold-only, respects current year filter via fd.df_time_sold)
        top_buyers_dict = build_top_buyers_dict(fd.df_time_sold)
        top_list = (top_buyers_dict.get(new_key, []) or [])[:10]

        st.sidebar.markdown("## Top buyers in selected county")
        st.sidebar.caption(f"County: **{chosen_title}** (sold only)")
        if top_list:
            st.sidebar.dataframe(
                pd.DataFrame(top_list, columns=["Buyer", "Sold deals"]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.sidebar.info("No sold buyers found for this county yet.")

        st.sidebar.markdown("---")


# -----------------------------
# Build top buyers dict (sold only)
# -----------------------------
top_buyers_dict = build_top_buyers_dict(fd.df_time_sold)

# -----------------------------
# County totals for sold/cut
# -----------------------------
df_conv = fd.df_time_filtered[fd.df_time_filtered["Status_norm"].isin(["sold", "cut loose"])]
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

# buyer_sold_counts (only when filtering by a buyer in Dispo)
buyer_sold_counts = {}
if buyer_active and mode in ["Sold", "Both"]:
    buyer_sold_counts = (
        fd.df_time_sold[fd.df_time_sold["Buyer_clean"] == buyer_choice]
        .groupby("County_clean_up")
        .size()
        .to_dict()
    )

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

# IMPORTANT: st_folium often repeats the LAST click on every rerun.
# Only treat it as a "new click" if the county actually changed.
prev_map_click = str(st.session_state.get("last_map_clicked_county", "")).strip().upper()

if clicked_key and clicked_key != prev_map_click:
    st.session_state["last_map_clicked_county"] = clicked_key
    st.session_state["selected_county"] = clicked_key
    st.session_state["county_source"] = "map"

    # Dispo: rerun so sidebar updates immediately
    if team_view == "Dispo":
        st.rerun()

    # Acquisitions: update the acquisition-selected county too
    if team_view == "Acquisitions":
        st.session_state["acq_selected_county"] = clicked_key
        st.session_state["acq_pending_county_title"] = clicked_key.title()
        st.rerun()


# -----------------------------
# BELOW MAP: County details panel (THIS IS THE TABLE YOU MISSED)
# -----------------------------
selected_for_panel = st.session_state.get("selected_county")
if team_view == "Acquisitions":
    selected_for_panel = st.session_state.get("acq_selected_county", selected_for_panel)

if selected_for_panel:
    ckey = str(selected_for_panel).strip().upper()

    sold = int(sold_counts.get(ckey, 0))
    cut = int(cut_counts.get(ckey, 0))
    total = sold + cut
    close_rate = (sold / total) if total > 0 else None
    close_rate_str = f"{close_rate*100:.1f}%" if close_rate is not None else "N/A"

    mao_tier = str(mao_tier_by_county.get(ckey, "")) or "—"
    mao_range = str(mao_range_by_county.get(ckey, "")) or "—"
    buyer_ct = int(buyer_count_by_county.get(ckey, 0))

    st.markdown("---")
    st.subheader(f"{ckey.title()} County details")

    a, b, c, d, e = st.columns([1, 1, 1.2, 1.2, 1.6], gap="small")
    a.metric("Sold", sold)
    b.metric("Cut loose", cut)
    c.metric("Close rate", close_rate_str)
    d.metric("# Buyers", buyer_ct)
    e.metric("MAO", f"{mao_tier} ({mao_range})" if mao_tier != "—" or mao_range != "—" else "—")

    # Properties table (from df_view)
    df_props = df_view[df_view["County_clean_up"] == ckey].copy()
    if not df_props.empty:
        show_cols = [C.address, C.city, C.status, C.buyer, C.date, C.sf_url]
        show_cols = [col for col in show_cols if col in df_props.columns]
        df_props = df_props[show_cols].copy()

        # Make Salesforce link column if present
        if C.sf_url in df_props.columns:
            df_props["Salesforce"] = df_props[C.sf_url]
            df_props = df_props.drop(columns=[C.sf_url])

        st.markdown("#### Properties in current view")
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
