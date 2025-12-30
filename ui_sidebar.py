# ui_sidebar.py
import pandas as pd
import streamlit as st


def render_team_view_toggle(default: str = "Dispo") -> str:
    """Sidebar toggle between Dispo and Acquisitions views."""
    st.sidebar.markdown("## Team view")
    options = ["Dispo", "Acquisitions"]
    index = 0 if default not in options else options.index(default)
    team_view = st.sidebar.radio(
        "Choose a view",
        options,
        index=index,
        label_visibility="collapsed",
    )
    return team_view


def render_overall_stats(
    *,
    year_choice,
    sold_total: int,
    cut_total: int,
    total_deals: int,
    total_buyers: int,
    close_rate_str: str,
    title: str = "Overall stats",
    scope_caption: str | None = None,
):
    """
    Sidebar stats card.
    Backwards compatible with the old signature, but now supports:
    - title="County stats"
    - scope_caption="County: **Davidson**"
    """
    st.sidebar.markdown(f"## {title}")
    st.sidebar.caption(f"Year: **{year_choice}**")
    if scope_caption:
        st.sidebar.caption(scope_caption)

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


def render_acquisitions_guidance(
    *,
    county_options: list[str],
    selected_county_key: str,
    mao_tier: str,
    mao_range: str,
    buyer_count: int,
    neighbor_unique_buyers: int,
    neighbor_breakdown: pd.DataFrame,
) -> str:
    """
    Acquisitions sidebar block.
    Returns the newly selected county (UPPERCASE key).
    """
    st.sidebar.markdown("## MAO guidance")

    options_title = [c.title() for c in (county_options or [])]
    key_to_title = {c.upper(): c.title() for c in (county_options or [])}
    title_to_key = {c.title(): c.upper() for c in (county_options or [])}

    default_title = key_to_title.get(selected_county_key.upper(), options_title[0] if options_title else "—")

    chosen_title = st.sidebar.selectbox(
        "County quick search",
        options_title if options_title else ["—"],
        index=(options_title.index(default_title) if options_title and default_title in options_title else 0),
        key="acq_county_select",
        help="Use this if you can’t easily click the county on the map.",
    )

    chosen_key = title_to_key.get(chosen_title, selected_county_key.upper())

    st.sidebar.caption("Tip: you can also click a county on the map to update this.")

    st.sidebar.markdown(
        f"""<div style="
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.14);
        border-radius: 10px;
        padding: 10px 12px;
    ">
        <div style="margin-bottom:6px;"><b>County:</b> {chosen_title}</div>
        <div style="margin-bottom:6px;"><b>MAO Tier:</b> {mao_tier}</div>
        <div style="margin-bottom:6px;"><b>MAO Range:</b> {mao_range}</div>
        <div style="margin-bottom:6px;"><b># Buyers (this county):</b> {buyer_count}</div>
        <div><b># Buyers (touching counties):</b> {neighbor_unique_buyers}</div>
    </div>""",
        unsafe_allow_html=True,
    )

    if neighbor_breakdown is not None and not neighbor_breakdown.empty:
        st.sidebar.markdown("#### Nearby county buyer breakdown")
        st.sidebar.dataframe(neighbor_breakdown, use_container_width=True, hide_index=True)

    return chosen_key


def render_rankings(rank_df: pd.DataFrame, *, default_rank_metric: str, rank_options: list[str]):
    st.sidebar.markdown("## County rankings")

    available = [c for c in rank_options if c in rank_df.columns]
    if not available:
        st.sidebar.info("No ranking metrics available.")
        return None, None

    if default_rank_metric not in available:
        default_rank_metric = available[0]

    rank_metric = st.sidebar.selectbox(
        "Rank by",
        available,
        index=available.index(default_rank_metric),
    )
    top_n = st.sidebar.slider("Top N", 5, 50, 15, 5)

    st.sidebar.dataframe(
        rank_df.sort_values(rank_metric, ascending=False).head(top_n),
        use_container_width=True,
        hide_index=True,
    )
    return rank_metric, top_n

###################################
#  vvv Phase B update below vvv   #
###################################

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
    Dispo sidebar panel that matches the Acquisitions-style layout:
      - County quick search dropdown (kept in sync with map clicks)
      - Stats: County, MAO Tier/Range, buyer counts
      - Top buyers table (sold only)

    Returns:
      chosen_key (UPPER county key) or "" if placeholder selected.
    """
    st.sidebar.markdown("## County stats")
    st.sidebar.caption("County quick search")

    placeholder = "— Select a county —"
    county_titles = [c.title() for c in county_options]
    options_title = [placeholder] + county_titles

    title_to_key = {c.title(): c.upper() for c in county_options}
    key_to_title = {c.upper(): c.title() for c in county_options}

    # Detect if the user just changed dropdown (Streamlit sets widget state BEFORE rerun)
    curr_dd = st.session_state.get("dispo_county_lookup", placeholder)
    prev_dd = st.session_state.get("_dispo_prev_county_lookup", curr_dd)
    user_changed_dropdown = curr_dd != prev_dd

    # Only auto-sync dropdown from map if map was the source AND user didn't just change dropdown
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

    # Track previous so we can detect real user changes next rerun
    st.session_state["_dispo_prev_county_lookup"] = chosen_title

    # If placeholder, stop here
    if chosen_title == placeholder:
        st.sidebar.info("Select a county from the dropdown or click one on the map.")
        return ""

    chosen_key = title_to_key.get(chosen_title, "").strip().upper()
    if not chosen_key:
        st.sidebar.info("Select a county from the dropdown or click one on the map.")
        return ""

    # Render the Acq-style stats block
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
        st.sidebar.dataframe(
            top_buyers_df,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.sidebar.info("No sold buyers found for this county yet.")

    st.sidebar.markdown("---")
    return chosen_key
