from __future__ import annotations

import pandas as pd
import streamlit as st

from config import C
from filters import compute_overall_stats
from enrich import build_top_buyers_dict
from ui_sidebar import render_county_quick_search

# -----------------------------
# Buyer context helpers
# -----------------------------


def compute_buyer_context_from_df(df_time_sold: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int], dict[str, set[str]]]:
    """
    Same as compute_buyer_context(fd) but takes a sold dataframe directly.
    """
    df_sold_buyers = df_time_sold.copy()
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

    return df_sold_buyers, buyer_count_by_county, buyers_set_by_county


# -----------------------------
# Sidebar blocks
# -----------------------------

def render_acquisitions_sidebar(
    team_view: str,
    all_county_options: list[str],
    adjacency: dict[str, list[str]],
    df_sold_buyers: pd.DataFrame,
    buyer_count_by_county: dict[str, int],
    buyers_set_by_county: dict[str, set[str]],
    mao_tier_by_county: dict[str, str],
    mao_range_by_county: dict[str, str],
    render_acquisitions_guidance,
) -> None:
    if team_view != "Acquisitions":
        return

    if "acq_pending_county_title" in st.session_state:
        st.session_state["acq_county_select"] = st.session_state["acq_pending_county_title"]
        del st.session_state["acq_pending_county_title"]

    selected = st.session_state.get("acq_selected_county", "")
    selected = str(selected).strip().upper()

    buyer_count = int(buyer_count_by_county.get(selected, 0))

    neighbors = adjacency.get(selected, [])
    neighbor_buyers_union: set[str] = set()
    neighbor_rows: list[dict] = []

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
        st.session_state["county_source"] = "dropdown"
        st.rerun()

    st.sidebar.markdown("---")


def render_dispo_county_quick_lookup(
    team_view: str,
    all_county_options: list[str],
    fd,
    df_time_sold_override: pd.DataFrame | None = None,
    df_time_cut_override: pd.DataFrame | None = None,
) -> None:
    """
    Renders the Dispo county quick search block.

    Uses the shared county dropdown so it behaves the same across views and
    keeps the selected county sticky when switching between views.

    NOTE: supports overrides so Dispo rep/acq rep filters apply consistently
    to the sidebar stats.
    """
    if team_view != "Dispo":
        return

    df_time_sold_for_stats = df_time_sold_override if df_time_sold_override is not None else fd.df_time_sold
    df_time_cut_for_stats = df_time_cut_override if df_time_cut_override is not None else fd.df_time_cut

    st.sidebar.markdown("## County stats")
    st.sidebar.caption("County quick search")

    chosen_key = render_county_quick_search(
        county_options=all_county_options,
        selected_county_key=str(st.session_state.get("selected_county", "")).strip().upper(),
        widget_key="county_quick_search",
        placeholder="— Select a county —",
    )

    if not chosen_key:
        st.sidebar.info("Select a county to see Dispo stats here.")
        st.sidebar.markdown("---")
        return

    prev_key = str(st.session_state.get("selected_county", "")).strip().upper()
    if chosen_key != prev_key:
        st.session_state["selected_county"] = chosen_key
        st.session_state["county_source"] = "dropdown"
        st.rerun()

    chosen_title = chosen_key.title()

    sold_scope = df_time_sold_for_stats[df_time_sold_for_stats["County_clean_up"] == chosen_key]
    cut_scope = df_time_cut_for_stats[df_time_cut_for_stats["County_clean_up"] == chosen_key]
    cstats = compute_overall_stats(sold_scope, cut_scope)

    sold_ct = int(cstats["sold_total"])
    cut_ct = int(cstats["cut_total"])
    total_ct = int(cstats["total_deals"])
    buyer_ct = int(cstats["total_buyers"])
    close_rate_str = str(cstats["close_rate_str"])

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

    top_buyers_dict = build_top_buyers_dict(df_time_sold_for_stats)
    top_list = (top_buyers_dict.get(chosen_key, []) or [])[:10]

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
# Map click handling
# -----------------------------

def extract_clicked_county_name(state: dict) -> str | None:
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


def handle_map_click(map_state: dict, team_view: str) -> None:
    clicked_name = extract_clicked_county_name(map_state)
    clicked_key = str(clicked_name).strip().upper() if clicked_name else ""

    prev_map_click = str(st.session_state.get("last_map_clicked_county", "")).strip().upper()
    # ... (rest of your file continues unchanged)
