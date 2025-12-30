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
    render_dispo_county_panel,
)
from ui_panels import render_selected_county_details
from enrich import (
    build_top_buyers_dict,
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
if tiers is not None and not tiers.empty:
    mao_tier_by_county = (
        tiers.dropna(subset=["County_clean_up"])
        .assign(County_clean_up=lambda d: d["County_clean_up"].astype(str).str.strip().str.upper())
        .set_index("County_clean_up")["MAO_Tier"]
        .to_dict()
    )
    mao_range_by_county = (
        tiers.dropna(subset=["County_clean_up"])
        .assign(County_clean_up=lambda d: d["County_clean_up"].astype(str).str.strip().str.upper())
        .set_index("County_clean_up")["MAO_Range_Str"]
        .to_dict()
    )

# County options (prefer tiers list if available)
tier_counties = (
    sorted(set((tiers["County_clean_up"].dropna().astype(str).str.strip().str.upper().tolist())))
    if tiers is not None and not tiers.empty
    else []
)
deal_counties = sorted(set(df["County_clean_up"].dropna().astype(str).str.strip().str.upper().tolist()))
all_county_options = tier_counties if tier_counties else deal_counties

ensure_default_county(all_county_options, preferred="DAVIDSON")

# -----------------------------
# Top controls
# -----------------------------
team_view = render_team_view_toggle(default=st.session_state.get("team_view", "Dispo"))
st.session_state["team_view"] = team_view

col1, col2, col3, col4 = st.columns([1, 1, 1, 2])

with col1:
    mode = st.selectbox("Mode", ["Sold", "Cut Loose", "Both"], index=0)

# Year options
years = sorted([y for y in df["Year"].dropna().unique().tolist() if int(y) > 0])
year_options = ["All"] + [str(int(y)) for y in years]

with col2:
    year_choice = st.selectbox("Year", year_options, index=0)

with col3:
    map_labels = st.selectbox("Map labels", ["Health score", "Close rate", "Sold count"], index=0)

# -----------------------------
# Prepare filtered data
# -----------------------------
fd = prepare_filtered_data(df, year_choice=year_choice, mode=mode)

# County buyer sets
buyers_set_by_county = fd.df_time_sold.groupby("County_clean_up")["Buyer_clean"].agg(
    lambda s: set([x for x in s if str(x).strip()])
).to_dict()
buyer_count_by_county = {k: len(v) for k, v in buyers_set_by_county.items()}

# Selected county (single source of truth)
selected = str(st.session_state.get("selected_county", "")).strip().upper()
if not selected:
    selected = (all_county_options[0] if all_county_options else "")
    st.session_state["selected_county"] = selected

# Neighbor unique buyers (touching counties) for selected
neighbors = adjacency.get(selected, []) if selected else []
neighbor_buyers_u = set()
for n in neighbors:
    neighbor_buyers_u |= buyers_set_by_county.get(n, set())
neighbor_unique_buyers = len(neighbor_buyers_u)

# -----------------------------
# Buyer controls (Dispo view only)
# -----------------------------
if team_view == "Dispo":
    with col4:
        if mode in ["Sold", "Both"]:
            labels, label_to_buyer = build_buyer_labels(fd.buyer_momentum, fd.buyers_plain)
            chosen_label = st.selectbox("Buyer", labels, index=0)
            buyer_choice = label_to_buyer.get(chosen_label, "All buyers")
        else:
            buyer_choice = "All buyers"
            st.selectbox("Buyer", ["All buyers"], disabled=True)

    buyer_active = buyer_choice != "All buyers" and mode in ["Sold", "Both"]
else:
    with col4:
        buyer_choice = "All buyers"
        st.selectbox("Buyer", ["All buyers"], disabled=True)
    buyer_active = False

sel = Selection(
    mode=mode,
    year_choice=str(year_choice),
    buyer_choice=buyer_choice,
    buyer_active=buyer_active,
    top_n=10,
)

df_view = build_view_df(fd.df_time_sold, fd.df_time_cut, sel)

# Top buyers (sold only) used for sidebar + map enrichment
top_buyers_dict = build_top_buyers_dict(fd.df_time_sold)

# -----------------------------
# Dispo sidebar county panel (Phase B1)
# -----------------------------
if team_view == "Dispo":
    top_list = (top_buyers_dict.get(selected, []) or [])[:10]
    top_df = (
        pd.DataFrame(top_list, columns=["Buyer", "Sold deals"])
        if top_list
        else pd.DataFrame(columns=["Buyer", "Sold deals"])
    )

    chosen_key = render_dispo_county_panel(
        county_options=all_county_options,
        selected_county_key=selected,
        mao_tier=str(mao_tier_by_county.get(selected, "")) or "—",
        mao_range=str(mao_range_by_county.get(selected, "")) or "—",
        buyer_count=int(buyer_count_by_county.get(selected, 0)),
        neighbor_unique_buyers=int(neighbor_unique_buyers),
        top_buyers_df=top_df,
    )

    if chosen_key and chosen_key != selected:
        st.session_state["selected_county"] = chosen_key
        st.session_state["county_source"] = "dropdown"
        st.rerun()

# -----------------------------
# County totals for sold/cut
# -----------------------------
df_conv = fd.df_time_filtered[fd.df_time_filtered["Status_norm"].isin(["sold", "cut loose"])]
grp = df_conv.groupby("County_clean_up")
sold_counts = grp.apply(lambda g: (g["Status_norm"] == "sold").sum()).to_dict()
cut_counts = grp.apply(lambda g: (g["Status_norm"] == "cut loose").sum()).to_dict()

# Compute actual close rate for any county
def county_close_rate_pct(county_key: str) -> float | None:
    if not county_key:
        return None
    s = int(sold_counts.get(county_key, 0))
    c = int(cut_counts.get(county_key, 0))
    t = s + c
    if t <= 0:
        return None
    return (s / t) * 100.0

# --- Tier vs actual close rate (Acq guidance) ---
# Aggregate sold/cut by tier using tier mapping
tier_sold = {}
tier_cut = {}
tier_deals = {}

for county_key in set(list(sold_counts.keys()) + list(cut_counts.keys())):
    tier = str(mao_tier_by_county.get(county_key, "")).strip().upper()
    if not tier:
        continue
    s = int(sold_counts.get(county_key, 0))
    c = int(cut_counts.get(county_key, 0))
    tier_sold[tier] = tier_sold.get(tier, 0) + s
    tier_cut[tier] = tier_cut.get(tier, 0) + c
    tier_deals[tier] = tier_deals.get(tier, 0) + (s + c)

def tier_close_rate_pct(tier: str) -> float | None:
    t = str(tier or "").strip().upper()
    if not t:
        return None
    s = int(tier_sold.get(t, 0))
    c = int(tier_cut.get(t, 0))
    tot = s + c
    if tot <= 0:
        return None
    return (s / tot) * 100.0

# Health score
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
    render_rankings(rank_df=rank_df, selected_county_key=selected, key_name="selected_county", label="County rankings")
else:
    render_rankings(
        rank_df=rank_df,
        selected_county_key=str(st.session_state.get("acq_selected_county", selected)).strip().upper(),
        key_name="acq_selected_county",
        label="County rankings",
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
tn_geo = load_tn_geojson()
tn_geo = enrich_geojson_properties(
    tn_geo=tn_geo,
    sold_counts=sold_counts,
    cut_counts=cut_counts,
    health=health,
    close_rate_mode=(mode if mode != "Both" else "Both"),
    buyer_count_by_county=buyer_count_by_county,
    top_buyers_dict=top_buyers_dict,
    buyer_sold_counts=buyer_sold_counts,
)

# -----------------------------
# Build map
# -----------------------------
m = build_map(
    tn_geo=tn_geo,
    map_defaults=MAP_DEFAULTS,
    selected_county=selected,
    map_labels=map_labels,
)

map_out = st_folium(m, width=None, height=650)

# -----------------------------
# Map click handling -> update selected county
# -----------------------------
clicked = None
try:
    if map_out and isinstance(map_out, dict):
        clicked = map_out.get("last_active_drawing") or map_out.get("last_clicked")
except Exception:
    clicked = None

clicked_name = ""
if clicked and isinstance(clicked, dict):
    props = clicked.get("properties") or {}
    clicked_name = str(props.get("NAME") or props.get("name") or "").strip().upper()

if clicked_name and clicked_name in [c.upper() for c in all_county_options]:
    if clicked_name != selected:
        st.session_state["selected_county"] = clicked_name
        st.session_state["county_source"] = "map"
        st.session_state["last_map_clicked_county"] = clicked_name
        st.session_state["acq_pending_county_title"] = clicked_name.title()
        st.rerun()

# -----------------------------
# Below-map panels (Phase B2)
# -----------------------------
render_selected_county_details(
    df_view=df_view,
    selected_county_key=st.session_state.get("selected_county", ""),
    df_sold=fd.df_time_sold,
    df_cut=fd.df_time_cut,
)

# -----------------------------
# Acquisitions sidebar guidance (now includes Tier vs Actual Close Rate)
# -----------------------------
if team_view == "Acquisitions":
    acq_selected = str(st.session_state.get("acq_selected_county", str(st.session_state.get("selected_county", "")))).strip().upper()
    if not acq_selected and all_county_options:
        acq_selected = all_county_options[0].upper()
        st.session_state["acq_selected_county"] = acq_selected

    if st.session_state.get("acq_pending_county_title"):
        st.session_state["acq_county_select"] = st.session_state["acq_pending_county_title"]
        st.session_state["acq_pending_county_title"] = ""

    neighbor_acq_buyers = set()
    for n in adjacency.get(acq_selected, []):
        neighbor_acq_buyers |= buyers_set_by_county.get(n, set())

    acq_tier = str(mao_tier_by_county.get(acq_selected, "")).strip().upper()
    render_acquisitions_guidance(
        county_options=all_county_options,
        selected_county_key=acq_selected,
        mao_tier=str(mao_tier_by_county.get(acq_selected, "")) or "—",
        mao_range=str(mao_range_by_county.get(acq_selected, "")) or "—",
        buyer_count=int(buyer_count_by_county.get(acq_selected, 0)),
        neighbor_unique_buyers=int(len(neighbor_acq_buyers)),
        county_close_rate_pct=county_close_rate_pct(acq_selected),
        tier_close_rate_pct=tier_close_rate_pct(acq_tier) if acq_tier else None,
        tier_deals_n=int(tier_deals.get(acq_tier, 0)) if acq_tier else None,
    )

# -----------------------------
# Overall stats at bottom of sidebar (always)
# -----------------------------
overall = compute_overall_stats(fd.df_time_sold, fd.df_time_cut)
render_overall_stats(overall)
