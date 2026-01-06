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

from app_sections import (
    render_acquisitions_sidebar,
    render_dispo_county_quick_lookup,
    handle_map_click,
    render_below_map_panel,
)

from map_build import build_map


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

# -----------------------------
# Controls row (top)
# -----------------------------
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

else:
    # Acquisitions view keeps layout aligned
    with col3:
        buyer_choice = "All buyers"
        st.selectbox("Buyer", ["All buyers"], disabled=True)

    with col4:
        st.empty()

    buyer_active = False
    rep_active = False
    dispo_rep_choice = "All reps"

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

# -------------------------------------------------
# Buyer context (sold-only)
#  - In Dispo: respects rep filter
#  - In Acq: uses full sold data (rep filter off anyway)
# -------------------------------------------------
df_sold_buyers = df_time_sold_for_view.copy() if team_view == "Dispo" else fd.df_time_sold.copy()
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
df_view = build_view_df(df_time_sold_for_view, fd.df_time_cut, sel)

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
