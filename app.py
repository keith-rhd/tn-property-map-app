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


st.set_page_config(**DEFAULT_PAGE)
st.title("Closed RHD Properties Map")

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
# -----------------------------
col1, col2, col3, col4 = st.columns([1.2, 1.0, 1.0, 1.6], gap="small")

with col1:
    mode = st.radio("View", ["Sold", "Cut Loose", "Both"], index=0, horizontal=True)

with col2:
    TOP_N = st.selectbox("Top buyers", [5, 10, 15, 20], index=1)

with col3:
    years = sorted([y for y in df[C.date].dropna().dt.year.unique().tolist() if pd.notna(y)])
    year_labels = ["All years"] + [str(y) for y in years]
    year_choice = st.selectbox("Year", year_labels, index=0)

# -----------------------------
# Acquisition selectbox
# -----------------------------
if team_view == "Acquisitions":
    if "acq_pending_county_title" in st.session_state:
        st.session_state["acq_county_select"] = st.session_state["acq_pending_county_title"]
        del st.session_state["acq_pending_county_title"]

    selected = st.session_state.get("acq_selected_county")
    if not selected:
        selected = all_county_options[0] if all_county_options else ""

    selected = str(selected).strip().upper()

    # Buyer count in selected county (sold-only)
    df_sold_all = df[df["Status_norm"] == "sold"].copy()
    buyer_count_by_county = df_sold_all.groupby("County_clean_up")["Buyer_clean"].nunique().to_dict()
    buyer_count = int(buyer_count_by_county.get(selected, 0))

    # Neighbor buyers (touching counties)
    buyers_set_by_county = (
        df_sold_all.groupby("County_clean_up")["Buyer_clean"]
        .apply(lambda s: set(x for x in s.dropna().tolist() if str(x).strip()))
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
        neighbor_breakdown = neighbor_breakdown.sort_values("# Buyers", ascending=False)

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
        st.rerun()

    st.sidebar.markdown("---")

# -----------------------------
# Build selection + filtered data
# -----------------------------
buyer_choice = st.session_state.get("buyer_choice", "All buyers") if team_view == "Dispo" else "All buyers"

sel = Selection(
    mode=mode,
    year_choice=str(year_choice),
    buyer_choice=str(buyer_choice),
    buyer_active=bool(team_view == "Dispo" and buyer_choice != "All buyers" and mode in ["Sold", "Both"]),
    top_n=int(TOP_N),
)

fd = prepare_filtered_data(df, sel)

# Buyer dropdown (Dispo view only)
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

    sel = Selection(
        mode=mode,
        year_choice=str(year_choice),
        buyer_choice=str(buyer_choice),
        buyer_active=bool(buyer_active),
        top_n=int(TOP_N),
    )
    fd = prepare_filtered_data(df, sel)

df_view = build_view_df(fd.df_time_sold, fd.df_time_cut, sel)

# -----------------------------
# Dispo stats (overall OR county scope)
# -----------------------------
if team_view == "Dispo":
    clicked_or_selected = str(st.session_state.get("selected_county", "")).strip().upper()

    dispo_option_titles = ["Overall (all counties)"] + [c.title() for c in all_county_options]
    title_to_key = {c.title(): c.upper() for c in all_county_options}

    # If user clicked a county on the map, sync the dropdown to it.
    # If nothing selected, default to Overall.
    if clicked_or_selected and clicked_or_selected in set([c.upper() for c in all_county_options]):
        st.session_state["dispo_stats_scope"] = clicked_or_selected.title()
    else:
        st.session_state.setdefault("dispo_stats_scope", "Overall (all counties)")

    chosen_title = st.sidebar.selectbox(
        "County quick search (stats)",
        dispo_option_titles,
        index=dispo_option_titles.index(st.session_state.get("dispo_stats_scope", "Overall (all counties)"))
        if st.session_state.get("dispo_stats_scope", "Overall (all counties)") in dispo_option_titles
        else 0,
        key="dispo_stats_scope",
        help="Click a county on the map OR use this dropdown to view county-level Dispo stats. Choose Overall to go back.",
    )

    if chosen_title == "Overall (all counties)":
        # Clear county selection so other county-only panels hide
        st.session_state["selected_county"] = ""
        sold_scope = fd.df_time_sold
        cut_scope = fd.df_time_cut
        stats_title = "Overall stats"
        scope_caption = None
    else:
        county_key = title_to_key.get(chosen_title, "").strip().upper()
        st.session_state["selected_county"] = county_key
        sold_scope = fd.df_time_sold[fd.df_time_sold["County_clean_up"] == county_key]
        cut_scope = fd.df_time_cut[fd.df_time_cut["County_clean_up"] == county_key]
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
# Dispo: Sidebar "Top buyers in selected county" (below stats)
# -----------------------------
if team_view == "Dispo":
    sel_county = str(st.session_state.get("selected_county", "")).strip().upper()
    if sel_county:
        top_list = (top_buyers_dict.get(sel_county, []) or [])[:10]
        st.sidebar.markdown("## Top buyers in selected county")
        st.sidebar.caption(f"County: **{sel_county.title()}** (sold only)")
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
# County totals for sold/cut (filtered)
# -----------------------------
df_conv = fd.df_time_filtered[fd.df_time_filtered["Status_norm"].isin(["sold", "cut loose"])]
grp = df_conv.groupby("County_clean_up")
sold_counts = grp.apply(lambda g: (g["Status_norm"] == "sold").sum()).to_dict()
cut_counts = grp.apply(lambda g: (g["Status_norm"] == "cut loose").sum()).to_dict()

counties_for_health = sorted(set(list(sold_counts.keys()) + list(cut_counts.keys())))
health = compute_health_score(counties_for_health, sold_counts, cut_counts)

# -----------------------------
# Rankings
# -----------------------------
if team_view == "Dispo":
    rank_df = (
        pd.DataFrame({"County": counties_for_health, "Health score": [health.get(c, 0.0) for c in counties_for_health]})
        .assign(**{"Buyer count": lambda d: d["County"].map(lambda x: int(fd.df_time_sold[fd.df_time_sold["County_clean_up"] == x]["Buyer_clean"].nunique()))})
    )
    render_rankings(
        rank_df[["County", "Health score", "Buyer count"]],
        default_rank_metric="Health score",
        rank_options=["Health score", "Buyer count"],
    )
else:
    rows = []
    for c in counties_for_health:
        s = int(sold_counts.get(c, 0))
        k = int(cut_counts.get(c, 0))
        total = s + k
        close = (s / total) if total else 0.0
        rows.append((c, close, s, total, k))

    rank_df = pd.DataFrame(rows, columns=["County", "Close rate", "Sold", "Total", "Cut loose"])
    render_rankings(
        rank_df[["County", "Close rate", "Sold", "Total", "Cut loose"]],
        default_rank_metric="Close rate",
        rank_options=["Close rate", "Sold", "Total"],
    )

# -----------------------------
# Build map view df + geo enrich
# -----------------------------
county_counts_view = df_view.groupby("County_clean_up").size().to_dict()
county_properties_view = build_county_properties_view(df_view)

tn_geo = load_tn_geojson()

tn_geo = enrich_geojson_properties(
    tn_geo,
    team_view=team_view,
    mode=mode,
    buyer_active=bool(team_view == "Dispo" and buyer_choice != "All buyers" and mode in ["Sold", "Both"]),
    buyer_choice=buyer_choice,
    top_n_buyers=int(TOP_N),
    county_counts_view=county_counts_view,
    sold_counts=sold_counts,
    cut_counts=cut_counts,
    county_properties_view=county_properties_view,
    top_buyers_dict=top_buyers_dict,
    mao_tier_by_county=mao_tier_by_county,
    mao_range_by_county=mao_range_by_county,
)

m = build_map(
    tn_geo=tn_geo,
    team_view=team_view,
    mode=mode,
    year_choice=year_choice,
    buyer_choice=buyer_choice,
    buyer_active=bool(team_view == "Dispo" and buyer_choice != "All buyers" and mode in ["Sold", "Both"]),
)

map_state = st_folium(m, height=650, use_container_width=True)

# -----------------------------
# Click handling
# -----------------------------
def _extract_clicked_county_name(state: dict):
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
