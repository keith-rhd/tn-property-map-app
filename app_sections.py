from __future__ import annotations

import pandas as pd
import streamlit as st

from config import C
from filters import compute_overall_stats
from enrich import build_top_buyers_dict


# -----------------------------
# Buyer context helpers
# -----------------------------

def compute_buyer_context(fd) -> tuple[pd.DataFrame, dict[str, int], dict[str, set[str]]]:
    """
    Returns:
      df_sold_buyers: fd.df_time_sold with Buyer_clean hardened
      buyer_count_by_county: county -> unique buyer count
      buyers_set_by_county: county -> set of buyers
    """
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

    buyers_set_by_county = (
        df_sold_buyers[df_sold_buyers["Buyer_clean"] != ""]
        .groupby("County_clean_up")["Buyer_clean"]
        .apply(lambda s: set(s.dropna().tolist()))
        .to_dict()
    )

    return df_sold_buyers, buyer_count_by_county, buyers_set_by_county

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
    """
    Renders the Acquisitions sidebar block and handles selection + rerun.
    No output; mutates session_state exactly like your current app.py.
    """
    if team_view != "Acquisitions":
        return

    if "acq_pending_county_title" in st.session_state:
        st.session_state["acq_county_select"] = st.session_state["acq_pending_county_title"]
        del st.session_state["acq_pending_county_title"]

    selected = st.session_state.get("acq_selected_county")
    if not selected:
        selected = "DAVIDSON" if "DAVIDSON" in [c.upper() for c in all_county_options] else (
            all_county_options[0] if all_county_options else ""
        )
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
) -> None:
    """
    Renders your Dispo county quick search block.
    If df_time_sold_override is provided, it is used for sold_scope + top buyers
    (so Dispo Rep filtering stays consistent).
    """
    if team_view != "Dispo":
        return

    df_time_sold_for_stats = df_time_sold_override if df_time_sold_override is not None else fd.df_time_sold

    st.sidebar.markdown("## County stats")
    st.sidebar.caption("County quick search")

    placeholder = "— Select a county —"
    county_titles = [c.title() for c in all_county_options]
    options_title = [placeholder] + county_titles
    title_to_key = {c.title(): c.upper() for c in all_county_options}
    key_to_title = {c.upper(): c.title() for c in all_county_options}

    curr_dd = st.session_state.get("dispo_county_lookup", placeholder)
    prev_dd = st.session_state.get("_dispo_prev_county_lookup", curr_dd)
    user_changed_dropdown = curr_dd != prev_dd

    if st.session_state.get("county_source") == "map" and not user_changed_dropdown:
        sel_key = str(st.session_state.get("selected_county", "")).strip().upper()
        if sel_key and sel_key in key_to_title:
            st.session_state["dispo_county_lookup"] = key_to_title[sel_key]

    st.session_state.setdefault("dispo_county_lookup", placeholder)

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

    st.session_state["_dispo_prev_county_lookup"] = st.session_state.get("dispo_county_lookup", placeholder)
    st.sidebar.caption("Tip: you can also click a county on the map to update this.")

    if chosen_title == placeholder:
        st.sidebar.info("Select a county to see Dispo stats here.")
        st.sidebar.markdown("---")
        return

    new_key = title_to_key.get(chosen_title, "").strip().upper()
    prev_key = str(st.session_state.get("selected_county", "")).strip().upper()

    if new_key and new_key != prev_key:
        st.session_state["selected_county"] = new_key
        st.session_state["county_source"] = "dropdown"
        st.rerun()

    sold_scope = df_time_sold_for_stats[df_time_sold_for_stats["County_clean_up"] == new_key]
    cut_scope = fd.df_time_cut[fd.df_time_cut["County_clean_up"] == new_key]
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

    if clicked_key and clicked_key != prev_map_click:
        st.session_state["last_map_clicked_county"] = clicked_key
        st.session_state["selected_county"] = clicked_key
        st.session_state["county_source"] = "map"

        if team_view == "Dispo":
            st.rerun()

        if team_view == "Acquisitions":
            st.session_state["acq_selected_county"] = clicked_key
            st.session_state["acq_pending_county_title"] = clicked_key.title()
            st.rerun()


# -----------------------------
# Below-map panel
# -----------------------------

def render_below_map_panel(
    team_view: str,
    df_view: pd.DataFrame,
    sold_counts: dict[str, int],
    cut_counts: dict[str, int],
    buyer_count_by_county: dict[str, int],
    mao_tier_by_county: dict[str, str],
    mao_range_by_county: dict[str, str],
) -> None:
    selected_for_panel = st.session_state.get("selected_county")
    if team_view == "Acquisitions":
        selected_for_panel = st.session_state.get("acq_selected_county", selected_for_panel)

    if not selected_for_panel:
        st.caption("Tip: Click a county to see details below the map.")
        return

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

    df_props = df_view[df_view["County_clean_up"] == ckey].copy()
    if df_props.empty:
        st.info("No properties match the current filters for this county.")
        return

    show_cols = [C.address, C.city, C.status, C.buyer, C.date, C.sf_url]
    show_cols = [col for col in show_cols if col in df_props.columns]
    df_props = df_props[show_cols].copy()

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
