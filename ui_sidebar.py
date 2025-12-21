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
    st.sidebar.markdown("---")
    return team_view


def render_overall_stats(*, year_choice, sold_total, cut_total, total_deals, total_buyers, close_rate_str):
    st.sidebar.markdown("## Overall stats")
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


def render_acquisitions_guidance(*, county_choice: str, mao_tier: str, mao_range: str, buyer_count: int):
    st.sidebar.markdown("## MAO guidance")
    st.sidebar.caption("Click a county on the map to update this.")

    st.sidebar.markdown(
        f"""<div style="
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.14);
        border-radius: 10px;
        padding: 10px 12px;
    ">
        <div style="margin-bottom:6px;"><b>County:</b> {county_choice}</div>
        <div style="margin-bottom:6px;"><b>MAO Tier:</b> {mao_tier}</div>
        <div style="margin-bottom:6px;"><b>MAO Range:</b> {mao_range}</div>
        <div><b># Buyers:</b> {buyer_count}</div>
    </div>""",
        unsafe_allow_html=True,
    )


def render_rankings(rank_df: pd.DataFrame, *, default_rank_metric: str, rank_options: list[str]):
    st.sidebar.markdown("## County rankings")

    available = [c for c in rank_options if c in rank_df.columns]
    if not available:
        st.sidebar.warning("No ranking metrics available.")
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
