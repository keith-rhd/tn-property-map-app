import pandas as pd
import streamlit as st


def render_team_view_toggle(default: str = "Dispo") -> str:
    st.sidebar.markdown("## Team view")
    options = ["Dispo", "Acquisitions"]
    index = options.index(default) if default in options else 0
    return st.sidebar.radio("Choose a view", options, index=index, label_visibility="collapsed")


def render_overall_stats(overall: dict, title: str = "Overall stats"):
    """Renders overall stats (kept compatible with your current app.py usage)."""
    st.sidebar.markdown(f"## {title}")

    sold_total = int(overall.get("sold_total", 0))
    cut_total = int(overall.get("cut_total", 0))
    total_deals = int(overall.get("total_deals", sold_total + cut_total))
    total_buyers = int(overall.get("total_buyers", 0))
    close_rate_str = str(overall.get("close_rate_str", "0.0%"))
    year_choice = overall.get("year_choice", "All")

    st.sidebar.caption(f"Year: **{year_choice}**")

    st.sidebar.markdown(
        f"""
<div style="
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 10px;
    padding: 10px 12px;
">
    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <span>Sold</span><span><b>{sold_total}</b></span>
    </div>
    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <span>Cut loose</span><span><b>{cut_total}</b></span>
    </div>
    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <span>Total deals</span><span><b>{total_deals}</b></span>
    </div>
    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <span>Total buyers</span><span><b>{total_buyers}</b></span>
    </div>
    <div style="display:flex; justify-content:space-between;">
        <span>Close rate</span><span><b>{close_rate_str}</b></span>
    </div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.sidebar.markdown("---")


def render_rankings(
    rank_df: pd.DataFrame,
    *,
    selected_county_key: str,
    key_name: str,
    label: str = "County rankings",
):
    st.sidebar.markdown(f"## {label}")

    if rank_df is None or rank_df.empty:
        st.sidebar.info("No ranking data available.")
        return

    metric_options = [c for c in ["Health score", "Close rate", "Sold", "Buyer count", "Total"] if c in rank_df.columns]
    metric = st.sidebar.selectbox("Rank by", metric_options, index=0)
    top_n = st.sidebar.slider("Top N", 5, 50, 15, 5)

    st.sidebar.dataframe(
        rank_df.sort_values(metric, ascending=False).head(top_n),
        use_container_width=True,
        hide_index=True,
    )


def render_acquisitions_guidance(
    *,
    county_options: list[str],
    selected_county_key: str,
    mao_tier: str,
    mao_range: str,
    buyer_count: int,
    neighbor_unique_buyers: int,
) -> str:
    """Acquisitions sidebar block. Returns selected county key (UPPER)."""
    st.sidebar.markdown("## MAO guidance")

    options_title = [c.title() for c in (county_options or [])]
    key_to_title = {c.upper(): c.title() for c in (county_options or [])}
    title_to_key = {c.title(): c.upper() for c in (county_options or [])}

    default_title = key_to_title.get(str(selected_county_key).upper(), options_title[0] if options_title else "—")

    chosen_title = st.sidebar.selectbox(
        "County quick search",
        options_title if options_title else ["—"],
        index=(options_title.index(default_title) if options_title and default_title in options_title else 0),
        key="acq_county_select",
        help="Tip: you can also click a county on the map to update this.",
    )
    chosen_key = title_to_key.get(chosen_title, str(selected_county_key).upper())

    st.sidebar.caption("Tip: you can also click a county on the map to update this.")

    st.sidebar.markdown(
        f"""<div style="
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.14);
        border-radius: 10px;
        padding: 10px 12px;
    ">
        <div style="margin-bottom:6px;"><b>County:</b> {chosen_title}</div>
        <div style="margin-bottom:6px;"><b>MAO Tier:</b> {mao_tier or "—"}</div>
        <div style="margin-bottom:6px;"><b>MAO Range:</b> {mao_range or "—"}</div>
        <div style="margin-bottom:6px;"><b># Buyers (this county):</b> {int(buyer_count)}</div>
        <div><b># Buyers (touching counties):</b> {int(neighbor_unique_buyers)}</div>
    </div>""",
        unsafe_allow_html=True,
    )

    return chosen_key


def render_dispo_county_panel(
    county_options: list[str],
    selected_county_key: str,
    mao_tier: str,
    mao_range: str,
    buyer_count: int,
    neighbor_unique_buyers: int,
    top_buyers_df: pd.DataFrame,
) -> str:
    """
    Dispo sidebar panel that matches the Acquisitions-style layout.
    Returns chosen_key (UPPER county key) or "" if placeholder selected.
    """
    st.sidebar.markdown("## County stats")
    st.sidebar.caption("County quick search")

    placeholder = "— Select a county —"
    county_titles = [c.title() for c in county_options]
    options_title = [placeholder] + county_titles

    title_to_key = {c.title(): c.upper() for c in county_options}
    key_to_title = {c.upper(): c.title() for c in county_options}

    curr_dd = st.session_state.get("dispo_county_lookup", placeholder)
    prev_dd = st.session_state.get("_dispo_prev_county_lookup", curr_dd)
    user_changed_dropdown = curr_dd != prev_dd

    if st.session_state.get("county_source") == "map" and not user_changed_dropdown:
        sel_key = str(selected_county_key or "").strip().upper()
        if sel_key and sel_key in key_to_title:
            st.session_state["dispo_county_lookup"] = key_to_title[sel_key]

    chosen_title = st.sidebar.selectbox(
        "County quick search",
        options_title,
        index=options_title.index(st.session_state.get("dispo_county_lookup", placeholder))
        if st.session_state.get("dispo_county_lookup", placeholder) in options_title
        else 0,
        key="dispo_county_lookup",
        label_visibility="collapsed",
        help="Tip: you can also click a county on the map to update this.",
    )

    st.session_state["_dispo_prev_county_lookup"] = chosen_title

    if chosen_title == placeholder:
        st.sidebar.info("Select a county from the dropdown or click one on the map.")
        return ""

    chosen_key = title_to_key.get(chosen_title, "").strip().upper()
    if not chosen_key:
        st.sidebar.info("Select a county from the dropdown or click one on the map.")
        return ""

    st.sidebar.markdown(
        f"""
**County:** {chosen_title}  
**MAO Tier:** {mao_tier or "—"}  
**MAO Range:** {mao_range or "—"}  
**# Buyers (this county):** {int(buyer_count)}  
**# Buyers (touching counties):** {int(neighbor_unique_buyers)}  
"""
    )

    st.sidebar.markdown("## Top buyers in selected county")
    st.sidebar.caption(f"County: **{chosen_title}** (sold only)")

    if top_buyers_df is not None and not top_buyers_df.empty:
        st.sidebar.dataframe(top_buyers_df, use_container_width=True, hide_index=True)
    else:
        st.sidebar.info("No sold buyers found for this county yet.")

    st.sidebar.markdown("---")
    return chosen_key


# -------------------------------------------------------------------
# Phase B2 wrappers: pass a single ctx dict instead of many parameters
# -------------------------------------------------------------------
def render_dispo_sidebar(ctx: dict) -> str:
    """
    Wrapper that renders the Dispo sidebar panel using ctx.
    Returns chosen county key (UPPER) or "" if unchanged/placeholder.
    """
    selected = str(ctx.get("selected", "")).strip().upper()
    county_options = ctx.get("all_county_options", []) or []
    mao_tier_by = ctx.get("mao_tier_by_county", {}) or {}
    mao_range_by = ctx.get("mao_range_by_county", {}) or {}
    buyer_count_by = ctx.get("buyer_count_by_county", {}) or {}
    neighbor_unique_buyers = int(ctx.get("neighbor_unique_buyers", 0))

    top_buyers_dict = ctx.get("top_buyers_dict", {}) or {}
    top_list = (top_buyers_dict.get(selected, []) or [])[:10]
    top_df = (
        pd.DataFrame(top_list, columns=["Buyer", "Sold deals"])
        if top_list
        else pd.DataFrame(columns=["Buyer", "Sold deals"])
    )

    return render_dispo_county_panel(
        county_options=county_options,
        selected_county_key=selected,
        mao_tier=str(mao_tier_by.get(selected, "")) or "—",
        mao_range=str(mao_range_by.get(selected, "")) or "—",
        buyer_count=int(buyer_count_by.get(selected, 0)),
        neighbor_unique_buyers=neighbor_unique_buyers,
        top_buyers_df=top_df,
    )


def render_acq_sidebar(ctx: dict) -> str:
    """
    Wrapper that renders the Acquisitions guidance using ctx.
    Returns selected county key (UPPER).
    """
    county_options = ctx.get("all_county_options", []) or []
    acq_selected = str(ctx.get("acq_selected", "")).strip().upper()
    mao_tier_by = ctx.get("mao_tier_by_county", {}) or {}
    mao_range_by = ctx.get("mao_range_by_county", {}) or {}
    buyer_count_by = ctx.get("buyer_count_by_county", {}) or {}
    neighbor_unique_buyers = int(ctx.get("neighbor_unique_buyers_acq", 0))

    return render_acquisitions_guidance(
        county_options=county_options,
        selected_county_key=acq_selected,
        mao_tier=str(mao_tier_by.get(acq_selected, "")) or "—",
        mao_range=str(mao_range_by.get(acq_selected, "")) or "—",
        buyer_count=int(buyer_count_by.get(acq_selected, 0)),
        neighbor_unique_buyers=neighbor_unique_buyers,
    )

