# ui_sidebar.py
import pandas as pd
import streamlit as st


def render_team_view_toggle(default: str = "Dispo") -> str:
    """Sidebar toggle between Dispo, Acquisitions, and Admin views."""
    st.sidebar.markdown("## Team view")
    options = ["Dispo", "Acquisitions", "Admin"]
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

    PLACEHOLDER = "- Select a County -"
    
    options_title = [PLACEHOLDER] + [c.title() for c in (county_options or [])]
    key_to_title = {c.upper(): c.title() for c in (county_options or [])}
    title_to_key = {c.title(): c.upper() for c in (county_options or [])}


    default_title = (
        key_to_title.get(selected_county_key.upper())
        if selected_county_key
        else PLACEHOLDER
    )


    chosen_title = st.sidebar.selectbox(
        "County quick search",
        options_title if options_title else ["—"],
        index=(options_title.index(default_title) if options_title and default_title in options_title else 0),
        key="acq_county_select",
        help="Use this if you can’t easily click the county on the map.",
    )

    if chosen_title == PLACEHOLDER:
        chosen_key = selected_county_key.upper()
    else:
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


def render_rankings(
    df_rank,
    *,
    default_rank_metric: str,
    rank_options: list[str],
    sort_by_map: dict[str, str] | None = None,
):
    """
    Renders a rankings table in the sidebar.

    - df_rank: dataframe containing at least 'County' and metric columns
    - default_rank_metric: the default selection in dropdown (must be in rank_options)
    - rank_options: list of columns that user can rank by
    - sort_by_map: optional dict mapping {display_column: numeric_sort_column}
      Example:
        {"Total GP ($)": "Total GP", "Avg GP ($)": "Avg GP"}
    """
    import pandas as pd
    import streamlit as st

    if df_rank is None or df_rank.empty:
        st.sidebar.info("No ranking data available for current filters.")
        return

    st.sidebar.markdown("### County rankings")

    # Dropdown for metric choice
    idx = rank_options.index(default_rank_metric) if default_rank_metric in rank_options else 0
    metric = st.sidebar.selectbox("Rank by", rank_options, index=idx)

    # Determine numeric sort column
    sort_col = metric
    if sort_by_map and metric in sort_by_map:
        sort_col = sort_by_map[metric]

    # If sort_col missing, fallback gracefully
    if sort_col not in df_rank.columns:
        st.sidebar.warning("Selected rank metric is not available.")
        return

    # Sort descending for numeric-like things; if strings, this is still stable
    df_sorted = df_rank.copy()

    # Try to coerce the sort column to numeric for correct sorting
    df_sorted["_sort_num"] = pd.to_numeric(df_sorted[sort_col], errors="coerce")
    if df_sorted["_sort_num"].notna().any():
        df_sorted = df_sorted.sort_values("_sort_num", ascending=False)
    else:
        df_sorted = df_sorted.sort_values(sort_col, ascending=False)

    df_sorted = df_sorted.drop(columns=["_sort_num"], errors="ignore")

    # Show top N
    top_n = st.sidebar.slider("Top N", min_value=5, max_value=50, value=15, step=5)
    df_sorted = df_sorted.head(int(top_n))

    # Hide helper numeric columns if we were sorting by them
    hide_cols = set()
    if sort_by_map:
        hide_cols.update(sort_by_map.values())
    
    show_cols = [c for c in df_sorted.columns if c not in hide_cols]
    st.sidebar.dataframe(df_sorted[show_cols], use_container_width=True, hide_index=True)

