# ui_sidebar.py
import pandas as pd
import streamlit as st


def render_team_view_toggle(default: str = "Dispo") -> str:
    """Sidebar toggle between Dispo, Acquisitions, and Sales Manager views."""
    st.sidebar.markdown("## Team view")
    options = ["Dispo", "Acquisitions", "Sales Manager"]
    index = 0 if default not in options else options.index(default)
    team_view = st.sidebar.radio(
        "Choose a view",
        options,
        index=index,
        label_visibility="collapsed",
    )
    return team_view


def render_stats_card(
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
    st.sidebar.markdown(f"## {title}")
    if scope_caption:
        st.sidebar.caption(scope_caption)

    st.sidebar.markdown(
        f"""
<div style="
    background: rgba(255,255,255,0.06);
    padding: 14px 14px;
    border-radius: 12px;
    border: 1px solid rgba(255,255,255,0.10);
">
    <div style="display:flex;justify-content:space-between;align-items:center;">
        <span>Year</span><span><b>{year_choice}</b></span>
    </div>
    <div style="height:8px"></div>
    <div style="display:flex;justify-content:space-between;align-items:center;">
        <span>Sold</span><span><b>{sold_total}</b></span>
    </div>
    <div style="display:flex;justify-content:space-between;align-items:center;">
        <span>Cut loose</span><span><b>{cut_total}</b></span>
    </div>
    <div style="display:flex;justify-content:space-between;align-items:center;">
        <span>Total deals</span><span><b>{total_deals}</b></span>
    </div>
    <div style="display:flex;justify-content:space-between;align-items:center;">
        <span>Unique buyers</span><span><b>{total_buyers}</b></span>
    </div>
    <div style="height:10px"></div>
    <div style="display:flex;justify-content:space-between;align-items:center;">
        <span>Close rate</span><span><b>{close_rate_str}</b></span>
    </div>
</div>
        """,
        unsafe_allow_html=True,
    )
